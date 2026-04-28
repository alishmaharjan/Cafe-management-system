import json
import csv
from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta

from django.db import transaction
from django.db.models import F, Q
from django.db.models import Sum, Count
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .models import (
    AuditLog,
    Category,
    Ingredient,
    InventoryMovement,
    Order,
    OrderItem,
    Payment,
    Product,
    Shift,
)
from .services import (
    StockError,
    consume_stock_for_order,
    recompute_order_totals,
    restore_stock_for_order,
)


def _json_body(request):
    if not request.body:
        return {}
    try:
        return json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return None


def _response(success, message, data=None, error_code=None, status=200):
    payload = {"success": success, "message": message}
    if success:
        payload["data"] = data if data is not None else {}
    else:
        payload["error_code"] = error_code
    return JsonResponse(payload, status=status)


def dashboard(request):
    return render(request, "core/dashboard.html")


def _audit(event_type, action, message, reference_id=""):
    AuditLog.objects.create(
        event_type=event_type,
        action=action,
        message=message[:255],
        reference_id=str(reference_id)[:80] if reference_id else "",
    )


def _order_payload(order):
    return {
        "id": order.id,
        "order_no": order.order_no,
        "order_type": order.order_type,
        "status": order.status,
        "payment_status": order.payment_status,
        "table_no": order.table_no,
        "subtotal": str(order.subtotal),
        "tax_amount": str(order.tax_amount),
        "discount_amount": str(order.discount_amount),
        "grand_total": str(order.grand_total),
        "notes": order.notes,
        "created_at": order.created_at.isoformat() if order.created_at else None,
        "items": [
            {
                "id": item.id,
                "product_id": item.product_id,
                "product_name": item.product.name,
                "qty": item.qty,
                "unit_price": str(item.unit_price),
                "line_total": str(item.line_total),
                "item_status": item.item_status,
            }
            for item in order.items.select_related("product").all()
        ],
        "payments": [
            {
                "id": payment.id,
                "method": payment.method,
                "amount": str(payment.amount),
                "txn_ref": payment.txn_ref,
                "paid_at": payment.paid_at.isoformat() if payment.paid_at else None,
            }
            for payment in order.payments.all()
        ],
    }


def _next_order_no():
    stamp = timezone.now().strftime("%Y%m%d")
    last = Order.objects.filter(order_no__startswith=f"ORD-{stamp}-").order_by("-id").first()
    if not last or not last.order_no:
        return f"ORD-{stamp}-0001"
    last_seq = int(last.order_no.split("-")[-1])
    return f"ORD-{stamp}-{last_seq + 1:04d}"


@csrf_exempt
@require_http_methods(["GET", "POST"])
def orders(request):
    if request.method == "GET":
        status_filter = request.GET.get("status")
        payment_status = request.GET.get("payment_status")
        search = request.GET.get("q")
        start_date = request.GET.get("start_date")
        end_date = request.GET.get("end_date")
        active_only = request.GET.get("active_only")
        qs = Order.objects.prefetch_related("items__product", "payments").all()
        if status_filter:
            qs = qs.filter(status=status_filter)
        if payment_status:
            qs = qs.filter(payment_status=payment_status)
        if active_only == "true":
            qs = qs.exclude(status__in=[Order.StatusChoices.CANCELLED, Order.StatusChoices.PAID])
        if search:
            qs = qs.filter(
                Q(order_no__icontains=search)
                | Q(table_no__icontains=search)
                | Q(items__product__name__icontains=search)
            ).distinct()
        if start_date:
            qs = qs.filter(created_at__date__gte=start_date)
        if end_date:
            qs = qs.filter(created_at__date__lte=end_date)
        return _response(True, "Orders fetched", [_order_payload(order) for order in qs])

    payload = _json_body(request)
    if payload is None:
        return _response(False, "Invalid JSON body", error_code="BAD_JSON", status=400)

    order_type = payload.get("order_type", Order.OrderTypeChoices.DINE_IN)
    if order_type not in Order.OrderTypeChoices.values:
        return _response(False, "Invalid order type", error_code="INVALID_ORDER_TYPE", status=400)

    with transaction.atomic():
        order = Order.objects.create(
            order_no=_next_order_no(),
            order_type=order_type,
            table_no=payload.get("table_no"),
            notes=payload.get("notes", ""),
        )

        items_payload = payload.get("items", [])
        for raw_item in items_payload:
            product = get_object_or_404(Product, pk=raw_item.get("product_id"), is_active=True)
            try:
                qty = int(raw_item.get("qty", 1))
            except (TypeError, ValueError):
                return _response(False, "Invalid quantity in order items", error_code="INVALID_QTY", status=400)
            if qty <= 0:
                return _response(False, "Quantity must be greater than zero", error_code="INVALID_QTY", status=400)
            OrderItem.objects.create(order=order, product=product, qty=qty, unit_price=product.price)

        if items_payload:
            recompute_order_totals(order)

        auto_confirm = bool(payload.get("auto_confirm", False))
        if auto_confirm:
            if not order.items.exists():
                return _response(False, "Cannot auto confirm empty order", error_code="EMPTY_ORDER", status=400)
            try:
                consume_stock_for_order(order)
            except StockError:
                return _response(
                    False,
                    "Order cannot be auto confirmed due to insufficient stock",
                    error_code="INSUFFICIENT_STOCK",
                    status=400,
                )
            order.status = Order.StatusChoices.CONFIRMED
            order.save(update_fields=["status"])

    order.refresh_from_db()
    _audit(
        AuditLog.EventTypeChoices.ORDER,
        "CREATE",
        f"Order {order.order_no or order.id} created with status {order.status}",
        order.id,
    )
    return _response(True, "Order created", _order_payload(order), status=201)


@csrf_exempt
@require_http_methods(["GET"])
def order_detail(request, order_id):
    order = get_object_or_404(Order.objects.prefetch_related("items__product", "payments"), pk=order_id)
    return _response(True, "Order fetched", _order_payload(order))


@csrf_exempt
@require_http_methods(["POST"])
def add_order_item(request, order_id):
    order = get_object_or_404(Order, pk=order_id)
    if order.status not in [Order.StatusChoices.OPEN, Order.StatusChoices.CONFIRMED]:
        return _response(
            False,
            "Only OPEN/CONFIRMED orders can be edited",
            error_code="ORDER_NOT_EDITABLE",
            status=400,
        )

    payload = _json_body(request)
    if payload is None:
        return _response(False, "Invalid JSON body", error_code="BAD_JSON", status=400)

    product = get_object_or_404(Product, pk=payload.get("product_id"), is_active=True)
    qty = int(payload.get("qty", 1))
    if qty <= 0:
        return _response(False, "Quantity must be greater than zero", error_code="INVALID_QTY", status=400)

    unit_price = product.price
    OrderItem.objects.create(order=order, product=product, qty=qty, unit_price=unit_price)
    recompute_order_totals(order)
    order.refresh_from_db()
    return _response(True, "Item added to order", _order_payload(order), status=201)


@csrf_exempt
@require_http_methods(["PATCH", "DELETE"])
def order_item_detail(request, order_id, item_id):
    order = get_object_or_404(Order, pk=order_id)
    item = get_object_or_404(OrderItem, pk=item_id, order_id=order.id)

    if request.method == "DELETE":
        item.delete()
        recompute_order_totals(order)
        order.refresh_from_db()
        return _response(True, "Item removed", _order_payload(order))

    payload = _json_body(request)
    if payload is None:
        return _response(False, "Invalid JSON body", error_code="BAD_JSON", status=400)

    qty = payload.get("qty")
    if qty is not None:
        qty = int(qty)
        if qty <= 0:
            return _response(False, "Quantity must be greater than zero", error_code="INVALID_QTY", status=400)
        item.qty = qty

    unit_price = payload.get("unit_price")
    if unit_price is not None:
        try:
            item.unit_price = Decimal(str(unit_price))
        except InvalidOperation:
            return _response(False, "Invalid unit_price value", error_code="INVALID_PRICE", status=400)

    item.save()
    recompute_order_totals(order)
    order.refresh_from_db()
    return _response(True, "Item updated", _order_payload(order))


@csrf_exempt
@require_http_methods(["POST"])
def confirm_order(request, order_id):
    order = get_object_or_404(Order, pk=order_id)
    if order.status != Order.StatusChoices.OPEN:
        return _response(False, "Only OPEN order can be confirmed", error_code="INVALID_STATE", status=400)
    if not order.items.exists():
        return _response(False, "Cannot confirm an empty order", error_code="EMPTY_ORDER", status=400)

    try:
        with transaction.atomic():
            consume_stock_for_order(order)
            order.status = Order.StatusChoices.CONFIRMED
            order.save(update_fields=["status"])
    except StockError:
        return _response(
            False,
            "Order cannot be confirmed due to insufficient stock",
            error_code="INSUFFICIENT_STOCK",
            status=400,
        )

    order.refresh_from_db()
    _audit(
        AuditLog.EventTypeChoices.ORDER,
        "CONFIRM",
        f"Order {order.order_no or order.id} confirmed",
        order.id,
    )
    return _response(True, "Order confirmed", _order_payload(order))


@csrf_exempt
@require_http_methods(["POST"])
def cancel_order(request, order_id):
    order = get_object_or_404(Order, pk=order_id)
    if order.status == Order.StatusChoices.CANCELLED:
        return _response(True, "Order already cancelled", _order_payload(order))

    with transaction.atomic():
        if order.status in [Order.StatusChoices.CONFIRMED, Order.StatusChoices.PREPARING, Order.StatusChoices.SERVED]:
            restore_stock_for_order(order)
        order.status = Order.StatusChoices.CANCELLED
        order.save(update_fields=["status"])

    order.refresh_from_db()
    _audit(
        AuditLog.EventTypeChoices.ORDER,
        "CANCEL",
        f"Order {order.order_no or order.id} cancelled",
        order.id,
    )
    return _response(True, "Order cancelled", _order_payload(order))


@csrf_exempt
@require_http_methods(["POST"])
def add_payment(request, order_id):
    with transaction.atomic():
        order = get_object_or_404(Order.objects.select_for_update(), pk=order_id)
        payload = _json_body(request)
        if payload is None:
            return _response(False, "Invalid JSON body", error_code="BAD_JSON", status=400)

        method = payload.get("method")
        if method not in Payment.MethodChoices.values:
            return _response(False, "Invalid payment method", error_code="INVALID_METHOD", status=400)

        try:
            amount = Decimal(str(payload.get("amount", "0")))
        except InvalidOperation:
            return _response(False, "Invalid amount", error_code="INVALID_AMOUNT", status=400)

        if amount <= 0:
            return _response(False, "Amount must be greater than zero", error_code="INVALID_AMOUNT", status=400)

        paid = order.payments.aggregate(paid=Sum("amount"))
        total_paid = paid["paid"] or Decimal("0")
        due = order.grand_total - total_paid

        if amount > due:
            return _response(False, "Payment exceeds due amount", error_code="OVERPAYMENT", status=400)

        Payment.objects.create(
            order=order, method=method, amount=amount, txn_ref=payload.get("txn_ref", "")
        )
        total_paid = total_paid + amount
        if total_paid == order.grand_total:
            order.payment_status = Order.PaymentStatusChoices.PAID
            order.status = Order.StatusChoices.PAID
        else:
            order.payment_status = Order.PaymentStatusChoices.PARTIAL
        order.save(update_fields=["payment_status", "status"])
        order.refresh_from_db()
    _audit(
        AuditLog.EventTypeChoices.PAYMENT,
        "ADD",
        f"Payment added for order {order.order_no or order.id}: {method} {amount}",
        order.id,
    )
    return _response(True, "Payment added", _order_payload(order))


@csrf_exempt
@require_http_methods(["POST"])
def close_order(request, order_id):
    order = get_object_or_404(Order, pk=order_id)
    if order.payment_status != Order.PaymentStatusChoices.PAID:
        return _response(False, "Order is not fully paid", error_code="UNPAID_ORDER", status=400)
    if order.status != Order.StatusChoices.PAID:
        order.status = Order.StatusChoices.PAID
        order.save(update_fields=["status"])
    order.refresh_from_db()
    return _response(True, "Order closed", _order_payload(order))


@require_http_methods(["GET"])
def categories(request):
    data = list(Category.objects.filter(is_active=True).values("id", "name"))
    return _response(True, "Categories fetched", data)


@require_http_methods(["GET"])
def products(request):
    category_id = request.GET.get("category_id")
    qs = Product.objects.filter(is_active=True).select_related("category")
    if category_id:
        qs = qs.filter(category_id=category_id)
    data = [
        {
            "id": p.id,
            "name": p.name,
            "sku": p.sku,
            "price": str(p.price),
            "tax_percent": str(p.tax_percent),
            "category_id": p.category_id,
            "category_name": p.category.name if p.category else None,
        }
        for p in qs
    ]
    return _response(True, "Products fetched", data)


@require_http_methods(["GET"])
def ingredients(request):
    qs = Ingredient.objects.filter(is_active=True)
    data = [
        {
            "id": i.id,
            "name": i.name,
            "unit": i.unit,
            "current_qty": str(i.current_qty),
            "min_qty_alert": str(i.min_qty_alert),
            "is_low_stock": i.current_qty <= i.min_qty_alert,
        }
        for i in qs
    ]
    return _response(True, "Ingredients fetched", data)


@require_http_methods(["GET"])
def low_stock_ingredients(request):
    qs = Ingredient.objects.filter(is_active=True, current_qty__lte=F("min_qty_alert"))
    data = [
        {
            "id": i.id,
            "name": i.name,
            "unit": i.unit,
            "current_qty": str(i.current_qty),
            "min_qty_alert": str(i.min_qty_alert),
        }
        for i in qs
    ]
    return _response(True, "Low stock ingredients fetched", data)


@csrf_exempt
@require_http_methods(["POST"])
def inventory_purchase(request):
    payload = _json_body(request)
    if payload is None:
        return _response(False, "Invalid JSON body", error_code="BAD_JSON", status=400)

    ingredient = get_object_or_404(Ingredient, pk=payload.get("ingredient_id"))
    try:
        qty = Decimal(str(payload.get("qty", "0")))
    except InvalidOperation:
        return _response(False, "Invalid quantity", error_code="INVALID_QTY", status=400)
    if qty <= 0:
        return _response(False, "Quantity must be greater than zero", error_code="INVALID_QTY", status=400)

    InventoryMovement.objects.create(
        ingredient=ingredient,
        movement_type=InventoryMovement.MovementTypeChoices.PURCHASE,
        qty_change=qty,
        reference_type=InventoryMovement.ReferenceTypeChoices.PURCHASE,
        reference_id=str(payload.get("reference_id", "")),
        note=payload.get("note", ""),
    )
    ingredient.refresh_from_db()
    _audit(
        AuditLog.EventTypeChoices.INVENTORY,
        "PURCHASE",
        f"Inventory purchase for {ingredient.name}: +{qty}",
        ingredient.id,
    )
    return _response(
        True,
        "Inventory purchase added",
        {"ingredient_id": ingredient.id, "current_qty": str(ingredient.current_qty)},
        status=201,
    )


@csrf_exempt
@require_http_methods(["POST"])
def inventory_adjustment(request):
    payload = _json_body(request)
    if payload is None:
        return _response(False, "Invalid JSON body", error_code="BAD_JSON", status=400)

    ingredient = get_object_or_404(Ingredient, pk=payload.get("ingredient_id"))
    try:
        qty_change = Decimal(str(payload.get("qty_change", "0")))
    except InvalidOperation:
        return _response(False, "Invalid qty_change", error_code="INVALID_QTY_CHANGE", status=400)
    if qty_change == 0:
        return _response(False, "qty_change cannot be zero", error_code="INVALID_QTY_CHANGE", status=400)

    if ingredient.current_qty + qty_change < 0:
        return _response(False, "Adjustment would make stock negative", error_code="NEGATIVE_STOCK", status=400)

    InventoryMovement.objects.create(
        ingredient=ingredient,
        movement_type=InventoryMovement.MovementTypeChoices.ADJUST,
        qty_change=qty_change,
        reference_type=InventoryMovement.ReferenceTypeChoices.MANUAL,
        reference_id=str(payload.get("reference_id", "")),
        note=payload.get("note", ""),
    )
    ingredient.refresh_from_db()
    _audit(
        AuditLog.EventTypeChoices.INVENTORY,
        "ADJUST",
        f"Inventory adjusted for {ingredient.name}: {qty_change}",
        ingredient.id,
    )
    return _response(
        True,
        "Inventory adjusted",
        {"ingredient_id": ingredient.id, "current_qty": str(ingredient.current_qty)},
    )


@require_http_methods(["GET"])
def inventory_movements(request):
    ingredient_id = request.GET.get("ingredient_id")
    qs = InventoryMovement.objects.select_related("ingredient").all()
    if ingredient_id:
        qs = qs.filter(ingredient_id=ingredient_id)
    data = [
        {
            "id": m.id,
            "ingredient_id": m.ingredient_id,
            "ingredient_name": m.ingredient.name,
            "movement_type": m.movement_type,
            "qty_change": str(m.qty_change),
            "reference_type": m.reference_type,
            "reference_id": m.reference_id,
            "note": m.note,
            "created_at": m.created_at.isoformat(),
        }
        for m in qs[:200]
    ]
    return _response(True, "Inventory movements fetched", data)


def _date_range(request):
    date_format = "%Y-%m-%d"
    end_str = request.GET.get("end_date")
    start_str = request.GET.get("start_date")
    today = timezone.localdate()

    if end_str:
        end_date = datetime.strptime(end_str, date_format).date()
    else:
        end_date = today

    if start_str:
        start_date = datetime.strptime(start_str, date_format).date()
    else:
        start_date = end_date - timedelta(days=6)

    start_dt = timezone.make_aware(datetime.combine(start_date, datetime.min.time()))
    end_dt = timezone.make_aware(datetime.combine(end_date, datetime.max.time()))
    return start_date, end_date, start_dt, end_dt


def _sales_report_data(start_dt, end_dt):
    orders_qs = Order.objects.filter(created_at__range=[start_dt, end_dt])
    paid_qs = orders_qs.filter(payment_status=Order.PaymentStatusChoices.PAID)

    orders_by_status = list(orders_qs.values("status").annotate(count=Count("id")).order_by("status"))
    payment_breakdown = list(
        Payment.objects.filter(order__created_at__range=[start_dt, end_dt])
        .values("method")
        .annotate(total_amount=Sum("amount"), count=Count("id"))
        .order_by("method")
    )
    payment_breakdown = [
        {
            "method": row["method"],
            "count": row["count"],
            "total_amount": str(row["total_amount"] or Decimal("0")),
        }
        for row in payment_breakdown
    ]

    top_products = list(
        paid_qs.values("items__product_id", "items__product__name")
        .annotate(total_qty=Sum("items__qty"), revenue=Sum("items__line_total"))
        .order_by("-total_qty")[:10]
    )
    top_products = [
        {
            "product_id": row["items__product_id"],
            "product_name": row["items__product__name"],
            "total_qty": row["total_qty"] or 0,
            "revenue": str(row["revenue"] or Decimal("0")),
        }
        for row in top_products
    ]

    summary = {
        "order_count": orders_qs.count(),
        "paid_order_count": paid_qs.count(),
        "gross_sales": str(paid_qs.aggregate(total=Sum("grand_total"))["total"] or Decimal("0")),
        "discount_total": str(orders_qs.aggregate(total=Sum("discount_amount"))["total"] or Decimal("0")),
        "tax_total": str(orders_qs.aggregate(total=Sum("tax_amount"))["total"] or Decimal("0")),
    }

    return {
        "summary": summary,
        "orders_by_status": orders_by_status,
        "payment_breakdown": payment_breakdown,
        "top_products": top_products,
    }


@require_http_methods(["GET"])
def report_sales(request):
    try:
        start_date, end_date, start_dt, end_dt = _date_range(request)
    except ValueError:
        return _response(False, "Invalid date format. Use YYYY-MM-DD", error_code="INVALID_DATE", status=400)
    data = _sales_report_data(start_dt, end_dt)
    data["start_date"] = str(start_date)
    data["end_date"] = str(end_date)
    return _response(True, "Sales report fetched", data)


@require_http_methods(["GET"])
def report_sales_export(request):
    try:
        start_date, end_date, start_dt, end_dt = _date_range(request)
    except ValueError:
        return _response(False, "Invalid date format. Use YYYY-MM-DD", error_code="INVALID_DATE", status=400)

    data = _sales_report_data(start_dt, end_dt)
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = (
        f'attachment; filename="sales_report_{start_date}_{end_date}.csv"'
    )

    writer = csv.writer(response)
    writer.writerow(["Sales Report", str(start_date), str(end_date)])
    writer.writerow([])
    writer.writerow(["Summary"])
    for key, value in data["summary"].items():
        writer.writerow([key, value])
    writer.writerow([])
    writer.writerow(["Orders by Status"])
    writer.writerow(["status", "count"])
    for row in data["orders_by_status"]:
        writer.writerow([row["status"], row["count"]])
    writer.writerow([])
    writer.writerow(["Payment Breakdown"])
    writer.writerow(["method", "count", "total_amount"])
    for row in data["payment_breakdown"]:
        writer.writerow([row["method"], row["count"], row["total_amount"]])
    writer.writerow([])
    writer.writerow(["Top Products"])
    writer.writerow(["product_id", "product_name", "total_qty", "revenue"])
    for row in data["top_products"]:
        writer.writerow([row["product_id"], row["product_name"], row["total_qty"], row["revenue"]])
    return response


def _inventory_report_data(start_dt, end_dt):
    low_stock = list(
        Ingredient.objects.filter(is_active=True, current_qty__lte=F("min_qty_alert"))
        .values("id", "name", "unit", "current_qty", "min_qty_alert")
        .order_by("name")
    )
    low_stock = [
        {
            "id": row["id"],
            "name": row["name"],
            "unit": row["unit"],
            "current_qty": str(row["current_qty"]),
            "min_qty_alert": str(row["min_qty_alert"]),
        }
        for row in low_stock
    ]

    movement_summary = list(
        InventoryMovement.objects.filter(created_at__range=[start_dt, end_dt])
        .values("movement_type")
        .annotate(total_qty=Sum("qty_change"), count=Count("id"))
        .order_by("movement_type")
    )
    movement_summary = [
        {
            "movement_type": row["movement_type"],
            "count": row["count"],
            "total_qty": str(row["total_qty"] or Decimal("0")),
        }
        for row in movement_summary
    ]

    top_consumed = list(
        InventoryMovement.objects.filter(
            created_at__range=[start_dt, end_dt],
            movement_type=InventoryMovement.MovementTypeChoices.CONSUME,
        )
        .values("ingredient_id", "ingredient__name", "ingredient__unit")
        .annotate(total_qty=Sum("qty_change"))
        .order_by("total_qty")[:10]
    )
    top_consumed = [
        {
            "ingredient_id": row["ingredient_id"],
            "ingredient_name": row["ingredient__name"],
            "unit": row["ingredient__unit"],
            "total_qty": str(abs(row["total_qty"] or Decimal("0"))),
        }
        for row in top_consumed
    ]

    return {
        "low_stock": low_stock,
        "movement_summary": movement_summary,
        "top_consumed": top_consumed,
    }


@require_http_methods(["GET"])
def report_inventory(request):
    try:
        start_date, end_date, start_dt, end_dt = _date_range(request)
    except ValueError:
        return _response(False, "Invalid date format. Use YYYY-MM-DD", error_code="INVALID_DATE", status=400)
    data = _inventory_report_data(start_dt, end_dt)
    data["start_date"] = str(start_date)
    data["end_date"] = str(end_date)
    return _response(True, "Inventory report fetched", data)


@require_http_methods(["GET"])
def report_inventory_export(request):
    try:
        start_date, end_date, start_dt, end_dt = _date_range(request)
    except ValueError:
        return _response(False, "Invalid date format. Use YYYY-MM-DD", error_code="INVALID_DATE", status=400)

    data = _inventory_report_data(start_dt, end_dt)
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = (
        f'attachment; filename="inventory_report_{start_date}_{end_date}.csv"'
    )

    writer = csv.writer(response)
    writer.writerow(["Inventory Report", str(start_date), str(end_date)])
    writer.writerow([])
    writer.writerow(["Low Stock"])
    writer.writerow(["id", "name", "unit", "current_qty", "min_qty_alert"])
    for row in data["low_stock"]:
        writer.writerow([row["id"], row["name"], row["unit"], row["current_qty"], row["min_qty_alert"]])
    writer.writerow([])
    writer.writerow(["Movement Summary"])
    writer.writerow(["movement_type", "count", "total_qty"])
    for row in data["movement_summary"]:
        writer.writerow([row["movement_type"], row["count"], row["total_qty"]])
    writer.writerow([])
    writer.writerow(["Top Consumed Ingredients"])
    writer.writerow(["ingredient_id", "ingredient_name", "unit", "total_qty"])
    for row in data["top_consumed"]:
        writer.writerow([row["ingredient_id"], row["ingredient_name"], row["unit"], row["total_qty"]])
    return response


def _day_close_data(target_date):
    start_dt = timezone.make_aware(datetime.combine(target_date, datetime.min.time()))
    end_dt = timezone.make_aware(datetime.combine(target_date, datetime.max.time()))
    day_orders = Order.objects.filter(created_at__range=[start_dt, end_dt])
    payments = Payment.objects.filter(order__created_at__range=[start_dt, end_dt])
    by_method = {
        row["method"]: str(row["total"] or Decimal("0"))
        for row in payments.values("method").annotate(total=Sum("amount"))
    }

    return {
        "date": str(target_date),
        "total_orders": day_orders.count(),
        "paid_orders": day_orders.filter(payment_status=Order.PaymentStatusChoices.PAID).count(),
        "cancelled_orders": day_orders.filter(status=Order.StatusChoices.CANCELLED).count(),
        "gross_sales": str(
            day_orders.filter(payment_status=Order.PaymentStatusChoices.PAID).aggregate(
                total=Sum("grand_total")
            )["total"]
            or Decimal("0")
        ),
        "cash_total": by_method.get(Payment.MethodChoices.CASH, "0"),
        "card_total": by_method.get(Payment.MethodChoices.CARD, "0"),
        "qr_total": by_method.get(Payment.MethodChoices.QR, "0"),
    }


@require_http_methods(["GET"])
def report_day_close(request):
    date_str = request.GET.get("date")
    try:
        target_date = datetime.strptime(date_str, "%Y-%m-%d").date() if date_str else timezone.localdate()
    except ValueError:
        return _response(False, "Invalid date format. Use YYYY-MM-DD", error_code="INVALID_DATE", status=400)
    return _response(True, "Day close report fetched", _day_close_data(target_date))


@require_http_methods(["GET"])
def dashboard_overview(request):
    try:
        start_date, end_date, start_dt, end_dt = _date_range(request)
    except ValueError:
        return _response(False, "Invalid date format. Use YYYY-MM-DD", error_code="INVALID_DATE", status=400)

    sales_data = _sales_report_data(start_dt, end_dt)
    active_orders = Order.objects.exclude(status__in=[Order.StatusChoices.CANCELLED, Order.StatusChoices.PAID]).count()
    low_stock_count = Ingredient.objects.filter(is_active=True, current_qty__lte=F("min_qty_alert")).count()
    current = Shift.objects.filter(status=Shift.ShiftStatusChoices.OPEN).order_by("-opened_at").first()

    return _response(
        True,
        "Dashboard overview fetched",
        {
            "start_date": str(start_date),
            "end_date": str(end_date),
            "summary": sales_data["summary"],
            "active_orders": active_orders,
            "low_stock_count": low_stock_count,
            "current_shift": {
                "id": current.id,
                "staff_name": current.staff_name,
                "counter_name": current.counter_name,
                "opened_at": current.opened_at.isoformat(),
                "opening_cash": str(current.opening_cash),
            }
            if current
            else None,
        },
    )


@require_http_methods(["GET"])
def activity_logs(request):
    limit = int(request.GET.get("limit", 50))
    limit = min(max(limit, 1), 200)
    logs = [
        {
            "type": row.event_type,
            "timestamp": row.created_at.isoformat(),
            "action": row.action,
            "message": row.message,
            "reference_id": row.reference_id,
        }
        for row in AuditLog.objects.order_by("-created_at")[:limit]
    ]
    return _response(True, "Activity logs fetched", logs)


@csrf_exempt
@require_http_methods(["GET"])
def current_shift(request):
    shift = Shift.objects.filter(status=Shift.ShiftStatusChoices.OPEN).order_by("-opened_at").first()
    if not shift:
        return _response(True, "No active shift", None)
    return _response(
        True,
        "Current shift fetched",
        {
            "id": shift.id,
            "opened_at": shift.opened_at.isoformat(),
            "status": shift.status,
            "staff_name": shift.staff_name,
            "counter_name": shift.counter_name,
            "opening_cash": str(shift.opening_cash),
            "closing_cash_expected": str(shift.closing_cash_expected),
            "closing_cash_actual": str(shift.closing_cash_actual),
            "notes": shift.notes,
        },
    )


@csrf_exempt
@require_http_methods(["POST"])
def open_shift(request):
    if Shift.objects.filter(status=Shift.ShiftStatusChoices.OPEN).exists():
        return _response(False, "An active shift already exists", error_code="SHIFT_ALREADY_OPEN", status=400)

    payload = _json_body(request)
    if payload is None:
        return _response(False, "Invalid JSON body", error_code="BAD_JSON", status=400)
    try:
        opening_cash = Decimal(str(payload.get("opening_cash", "0")))
    except InvalidOperation:
        return _response(False, "Invalid opening_cash", error_code="INVALID_AMOUNT", status=400)
    if opening_cash < 0:
        return _response(False, "opening_cash cannot be negative", error_code="INVALID_AMOUNT", status=400)

    shift = Shift.objects.create(
        staff_name=payload.get("staff_name", ""),
        counter_name=payload.get("counter_name", ""),
        opening_cash=opening_cash,
        notes=payload.get("notes", ""),
    )
    _audit(
        AuditLog.EventTypeChoices.SHIFT,
        "OPEN",
        f"Shift {shift.id} opened by {shift.staff_name or 'N/A'} on {shift.counter_name or 'N/A'}",
        shift.id,
    )
    return _response(
        True,
        "Shift opened",
        {
            "id": shift.id,
            "opened_at": shift.opened_at.isoformat(),
            "status": shift.status,
            "staff_name": shift.staff_name,
            "counter_name": shift.counter_name,
            "opening_cash": str(shift.opening_cash),
        },
        status=201,
    )


@csrf_exempt
@require_http_methods(["POST"])
def close_shift(request, shift_id):
    shift = get_object_or_404(Shift, pk=shift_id)
    if shift.status == Shift.ShiftStatusChoices.CLOSED:
        return _response(False, "Shift already closed", error_code="SHIFT_ALREADY_CLOSED", status=400)

    payload = _json_body(request)
    if payload is None:
        return _response(False, "Invalid JSON body", error_code="BAD_JSON", status=400)

    try:
        actual_cash = Decimal(str(payload.get("closing_cash_actual", "0")))
    except InvalidOperation:
        return _response(False, "Invalid closing_cash_actual", error_code="INVALID_AMOUNT", status=400)
    if actual_cash < 0:
        return _response(False, "closing_cash_actual cannot be negative", error_code="INVALID_AMOUNT", status=400)

    close_data = _day_close_data(timezone.localdate())
    expected_cash = Decimal(close_data["cash_total"]) + shift.opening_cash

    shift.closing_cash_expected = expected_cash
    shift.closing_cash_actual = actual_cash
    shift.status = Shift.ShiftStatusChoices.CLOSED
    shift.closed_at = timezone.now()
    shift.notes = payload.get("notes", shift.notes)
    shift.staff_name = payload.get("staff_name", shift.staff_name)
    shift.counter_name = payload.get("counter_name", shift.counter_name)
    shift.save(
        update_fields=[
            "closing_cash_expected",
            "closing_cash_actual",
            "status",
            "closed_at",
            "notes",
            "staff_name",
            "counter_name",
        ]
    )

    _audit(
        AuditLog.EventTypeChoices.SHIFT,
        "CLOSE",
        f"Shift {shift.id} closed. Variance {shift.closing_cash_actual - shift.closing_cash_expected}",
        shift.id,
    )
    return _response(
        True,
        "Shift closed",
        {
            "id": shift.id,
            "status": shift.status,
            "staff_name": shift.staff_name,
            "counter_name": shift.counter_name,
            "opened_at": shift.opened_at.isoformat(),
            "closed_at": shift.closed_at.isoformat() if shift.closed_at else None,
            "opening_cash": str(shift.opening_cash),
            "closing_cash_expected": str(shift.closing_cash_expected),
            "closing_cash_actual": str(shift.closing_cash_actual),
            "variance": str(shift.closing_cash_actual - shift.closing_cash_expected),
        },
    )
