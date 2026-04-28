from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from .models import Ingredient, InventoryMovement, Order, OrderItem, Recipe


class StockError(Exception):
    pass


def check_stock_for_order(order: Order):
    required = {}
    insufficient = []

    items = order.items.select_related("product").all()
    for item in items:
        recipes = Recipe.objects.select_related("ingredient").filter(product=item.product)
        for recipe in recipes:
            qty_needed = recipe.qty_per_item * item.qty
            required[recipe.ingredient_id] = required.get(recipe.ingredient_id, Decimal("0")) + qty_needed

    if not required:
        return {"required": required, "insufficient": insufficient}

    ingredients = Ingredient.objects.filter(id__in=required.keys())
    ingredient_map = {ing.id: ing for ing in ingredients}

    for ingredient_id, qty_needed in required.items():
        ing = ingredient_map.get(ingredient_id)
        if not ing or ing.current_qty < qty_needed:
            insufficient.append(
                {
                    "ingredient_id": ingredient_id,
                    "ingredient_name": ing.name if ing else "Unknown",
                    "required_qty": str(qty_needed),
                    "available_qty": str(ing.current_qty if ing else Decimal("0")),
                }
            )

    return {"required": required, "insufficient": insufficient}


@transaction.atomic
def consume_stock_for_order(order: Order):
    stock_result = check_stock_for_order(order)
    if stock_result["insufficient"]:
        raise StockError("INSUFFICIENT_STOCK")

    required = stock_result["required"]
    if not required:
        return

    ingredients = (
        Ingredient.objects.select_for_update().filter(id__in=required.keys()).order_by("id")
    )
    ingredient_map = {ing.id: ing for ing in ingredients}

    for ingredient_id, qty_needed in required.items():
        ing = ingredient_map.get(ingredient_id)
        if ing.current_qty < qty_needed:
            raise StockError("INSUFFICIENT_STOCK")

        InventoryMovement.objects.create(
            ingredient=ing,
            movement_type=InventoryMovement.MovementTypeChoices.CONSUME,
            qty_change=-qty_needed,
            reference_type=InventoryMovement.ReferenceTypeChoices.ORDER,
            reference_id=str(order.id),
            note=f"Consumed for order {order.order_no or order.id}",
        )


@transaction.atomic
def restore_stock_for_order(order: Order):
    consumed = (
        InventoryMovement.objects.filter(
            reference_type=InventoryMovement.ReferenceTypeChoices.ORDER,
            reference_id=str(order.id),
            movement_type=InventoryMovement.MovementTypeChoices.CONSUME,
        )
        .values("ingredient_id")
        .annotate(total_consumed=Sum("qty_change"))
    )

    if not consumed:
        return

    ingredients = (
        Ingredient.objects.select_for_update()
        .filter(id__in=[row["ingredient_id"] for row in consumed])
        .order_by("id")
    )
    ingredient_map = {ing.id: ing for ing in ingredients}

    for row in consumed:
        ingredient = ingredient_map.get(row["ingredient_id"])
        qty_to_restore = abs(row["total_consumed"])
        if qty_to_restore <= 0:
            continue
        InventoryMovement.objects.create(
            ingredient=ingredient,
            movement_type=InventoryMovement.MovementTypeChoices.RETURN,
            qty_change=qty_to_restore,
            reference_type=InventoryMovement.ReferenceTypeChoices.ORDER,
            reference_id=str(order.id),
            note=f"Restored for canceled order {order.order_no or order.id}",
        )


def recompute_order_totals(order: Order):
    subtotal = Decimal("0")
    tax_total = Decimal("0")

    items = order.items.select_related("product").all()
    for item in items:
        line_total = item.qty * item.unit_price
        if item.line_total != line_total:
            item.line_total = line_total
            item.save(update_fields=["line_total"])
        subtotal += line_total
        tax_total += (line_total * item.product.tax_percent) / Decimal("100")

    order.subtotal = subtotal
    order.tax_amount = tax_total.quantize(Decimal("0.01"))
    order.grand_total = order.subtotal + order.tax_amount - order.discount_amount
    order.updated_at = timezone.now()
    order.save(update_fields=["subtotal", "tax_amount", "grand_total", "updated_at"])

