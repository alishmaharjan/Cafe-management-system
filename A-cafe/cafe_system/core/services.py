from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from .models import (
    Ingredient,
    InventoryMovement,
    LowStockAlert,
    Order,
    OrderItem,
    Product,
    ProductStockMovement,
    Recipe,
)


class StockError(Exception):
    pass


def _aggregate_recipe_requirements(order: Order):
    required = {}
    items = order.items.select_related('product').all()
    for item in items:
        if item.product.product_type != Product.ProductTypeChoices.RECIPE_BASED:
            continue
        recipes = Recipe.objects.select_related('ingredient').filter(product=item.product)
        for recipe in recipes:
            qty_needed = recipe.qty_per_item * item.qty
            required[recipe.ingredient_id] = required.get(recipe.ingredient_id, Decimal('0')) + qty_needed
    return required
def _aggregate_direct_sale_requirements(order: Order):
    required = {}
    items = order.items.select_related('product').all()
    for item in items:
        if item.product.product_type != Product.ProductTypeChoices.DIRECT_SALE:
            continue
        required[item.product_id] = required.get(item.product_id, Decimal('0')) + Decimal(item.qty)
    return required


def check_stock_for_order(order: Order):
    insufficient = []

    recipe_required = _aggregate_recipe_requirements(order)
    if recipe_required:
        ingredients = Ingredient.objects.filter(id__in=recipe_required.keys())
        ingredient_map = {ing.id: ing for ing in ingredients}
        for ingredient_id, qty_needed in recipe_required.items():
            ing = ingredient_map.get(ingredient_id)
            if not ing or ing.current_qty < qty_needed:
                insufficient.append(
                    {
                        'type': 'ingredient',
                        'ingredient_id': ingredient_id,
                        'ingredient_name': ing.name if ing else 'Unknown',
                        'required_qty': str(qty_needed),
                        'available_qty': str(ing.current_qty if ing else Decimal('0')),
                    }
                )

    direct_required = _aggregate_direct_sale_requirements(order)
    if direct_required:
        products = Product.objects.filter(id__in=direct_required.keys())
        product_map = {p.id: p for p in products}
        for product_id, qty_needed in direct_required.items():
            product = product_map.get(product_id)
            if not product or product.current_qty < qty_needed:
                insufficient.append(
                    {
                        'type': 'product',
                        'product_id': product_id,
                        'product_name': product.name if product else 'Unknown',
                        'required_qty': str(qty_needed),
                        'available_qty': str(product.current_qty if product else Decimal('0')),
                    }
                )

    return {
        'recipe_required': recipe_required,
        'direct_required': direct_required,
        'insufficient': insufficient,
    }


def _order_already_has_sale_movements(order: Order) -> bool:
    if ProductStockMovement.objects.filter(
        order=order,
        movement_type=ProductStockMovement.MovementTypeChoices.SALE,
    ).exists():
        return True
    return InventoryMovement.objects.filter(
        reference_type=InventoryMovement.ReferenceTypeChoices.ORDER,
        reference_id=str(order.id),
        movement_type=InventoryMovement.MovementTypeChoices.CONSUME,
        deduction_source='sale',
    ).exists()


def _check_low_stock_and_alert(product=None, ingredient=None):
    if product and product.is_low_stock:
        exists = LowStockAlert.objects.filter(
            item_type=LowStockAlert.ItemTypeChoices.PRODUCT,
            product=product,
            is_resolved=False,
        ).exists()
        if not exists:
            LowStockAlert.objects.create(
                item_type=LowStockAlert.ItemTypeChoices.PRODUCT,
                product=product,
                current_qty=product.current_qty,
                min_qty_alert=product.min_qty_alert,
                message=f'Low stock: {product.name} ({product.current_qty} remaining, min {product.min_qty_alert})',
            )

    if ingredient and ingredient.current_qty <= ingredient.min_qty_alert:
        exists = LowStockAlert.objects.filter(
            item_type=LowStockAlert.ItemTypeChoices.INGREDIENT,
            ingredient=ingredient,
            is_resolved=False,
        ).exists()
        if not exists:
            LowStockAlert.objects.create(
                item_type=LowStockAlert.ItemTypeChoices.INGREDIENT,
                ingredient=ingredient,
                current_qty=ingredient.current_qty,
                min_qty_alert=ingredient.min_qty_alert,
                message=(
                    f'Low stock: {ingredient.name} '
                    f'({ingredient.current_qty}{ingredient.unit} remaining, '
                    f'min {ingredient.min_qty_alert}{ingredient.unit})'
                ),
            )


@transaction.atomic
def consume_stock_for_order(order: Order, *, force: bool = False):
    """Deduct inventory for an order. Idempotent unless force=True."""
    order = Order.objects.select_for_update().get(pk=order.pk)

    if order.inventory_deducted and not force:
        return {'deducted': False, 'reason': 'already_deducted'}

    if _order_already_has_sale_movements(order) and not force:
        order.inventory_deducted = True
        order.save(update_fields=['inventory_deducted', 'updated_at'])
        return {'deducted': False, 'reason': 'movements_exist'}

    stock_result = check_stock_for_order(order)
    if stock_result['insufficient']:
        raise StockError('INSUFFICIENT_STOCK')

    recipe_required = stock_result['recipe_required']
    direct_required = stock_result['direct_required']

    if not recipe_required and not direct_required:
        order.inventory_deducted = True
        order.save(update_fields=['inventory_deducted', 'updated_at'])
        return {'deducted': True, 'reason': 'nothing_to_deduct'}

    if recipe_required:
        ingredients = (
            Ingredient.objects.select_for_update()
            .filter(id__in=recipe_required.keys())
            .order_by('id')
        )
        ingredient_map = {ing.id: ing for ing in ingredients}
        for ingredient_id, qty_needed in recipe_required.items():
            ing = ingredient_map.get(ingredient_id)
            if ing.current_qty < qty_needed:
                raise StockError('INSUFFICIENT_STOCK')
            InventoryMovement.objects.create(
                ingredient=ing,
                movement_type=InventoryMovement.MovementTypeChoices.CONSUME,
                qty_change=-qty_needed,
                reference_type=InventoryMovement.ReferenceTypeChoices.ORDER,
                reference_id=str(order.id),
                deduction_source='sale',
                note=f'Recipe sale: order {order.order_no or order.id}',
            )
            ing.refresh_from_db()
            _check_low_stock_and_alert(ingredient=ing)

    if direct_required:
        products = (
            Product.objects.select_for_update()
            .filter(id__in=direct_required.keys())
            .order_by('id')
        )
        product_map = {p.id: p for p in products}
        for product_id, qty_needed in direct_required.items():
            product = product_map.get(product_id)
            if product.current_qty < qty_needed:
                raise StockError('INSUFFICIENT_STOCK')
            ProductStockMovement.objects.create(
                product=product,
                movement_type=ProductStockMovement.MovementTypeChoices.SALE,
                qty_change=-qty_needed,
                deduction_source=ProductStockMovement.DeductionSourceChoices.SALE,
                order=order,
                note=f'Direct sale: order {order.order_no or order.id}',
            )
            product.refresh_from_db()
            _check_low_stock_and_alert(product=product)

    order.inventory_deducted = True
    order.updated_at = timezone.now()
    order.save(update_fields=['inventory_deducted', 'updated_at'])
    return {'deducted': True, 'reason': 'success'}


def finalize_order_inventory(order: Order):
    """Trigger inventory deduction when a sale is completed (paid)."""
    if order.status == Order.StatusChoices.CANCELLED:
        return {'deducted': False, 'reason': 'cancelled'}
    if order.inventory_deducted:
        return {'deducted': False, 'reason': 'already_deducted'}
    is_paid = (
        order.status == Order.StatusChoices.PAID
        or order.payment_status == Order.PaymentStatusChoices.PAID
    )
    if not is_paid:
        return {'deducted': False, 'reason': 'not_paid'}
    return consume_stock_for_order(order)


@transaction.atomic
def restore_stock_for_order(order: Order):
    if not order.inventory_deducted and not _order_already_has_sale_movements(order):
        return

    consumed = (
        InventoryMovement.objects.filter(
            reference_type=InventoryMovement.ReferenceTypeChoices.ORDER,
            reference_id=str(order.id),
            movement_type=InventoryMovement.MovementTypeChoices.CONSUME,
        )
        .values('ingredient_id')
        .annotate(total_consumed=Sum('qty_change'))
    )

    if consumed:
        ingredients = (
            Ingredient.objects.select_for_update()
            .filter(id__in=[row['ingredient_id'] for row in consumed])
            .order_by('id')
        )
        ingredient_map = {ing.id: ing for ing in ingredients}
        for row in consumed:
            ingredient = ingredient_map.get(row['ingredient_id'])
            qty_to_restore = abs(row['total_consumed'])
            if qty_to_restore <= 0:
                continue
            InventoryMovement.objects.create(
                ingredient=ingredient,
                movement_type=InventoryMovement.MovementTypeChoices.RETURN,
                qty_change=qty_to_restore,
                reference_type=InventoryMovement.ReferenceTypeChoices.ORDER,
                reference_id=str(order.id),
                deduction_source='sale',
                note=f'Restored for canceled order {order.order_no or order.id}',
            )

    sold = (
        ProductStockMovement.objects.filter(
            order=order,
            movement_type=ProductStockMovement.MovementTypeChoices.SALE,
        )
        .values('product_id')
        .annotate(total_sold=Sum('qty_change'))
    )

    if sold:
        products = (
            Product.objects.select_for_update()
            .filter(id__in=[row['product_id'] for row in sold])
            .order_by('id')
        )
        product_map = {p.id: p for p in products}
        for row in sold:
            product = product_map.get(row['product_id'])
            qty_to_restore = abs(row['total_sold'])
            if qty_to_restore <= 0:
                continue
            ProductStockMovement.objects.create(
                product=product,
                movement_type=ProductStockMovement.MovementTypeChoices.RETURN,
                qty_change=qty_to_restore,
                deduction_source=ProductStockMovement.DeductionSourceChoices.SALE,
                order=order,
                note=f'Restored for canceled order {order.order_no or order.id}',
            )

    order.inventory_deducted = False
    order.updated_at = timezone.now()
    order.save(update_fields=['inventory_deducted', 'updated_at'])


def recompute_order_totals(order: Order):
    subtotal = Decimal('0')
    tax_total = Decimal('0')

    items = order.items.select_related('product').all()
    for item in items:
        line_total = item.qty * item.unit_price
        if item.line_total != line_total:
            item.line_total = line_total
            item.save(update_fields=['line_total'])
        subtotal += line_total
        tax_total += (line_total * item.product.tax_percent) / Decimal('100')

    order.subtotal = subtotal
    order.tax_amount = tax_total.quantize(Decimal('0.01'))
    order.grand_total = order.subtotal + order.tax_amount - order.discount_amount
    order.updated_at = timezone.now()
    order.save(update_fields=['subtotal', 'tax_amount', 'grand_total', 'updated_at'])
