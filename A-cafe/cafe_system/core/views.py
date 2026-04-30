import csv
import json
from decimal import Decimal, InvalidOperation
from functools import wraps

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .models import (
    AuditLog, Category, CreditAccount, CreditRecord, Ingredient, InventoryMovement,
    Order, OrderItem, Payment, Product, Shift, Table,
)
from .services import StockError, consume_stock_for_order, recompute_order_totals, restore_stock_for_order


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _json_body(request):
    if not request.body:
        return {}
    try:
        return json.loads(request.body.decode('utf-8'))
    except json.JSONDecodeError:
        return None


def _response(success, message, data=None, error_code=None, status=200):
    payload = {'success': success, 'message': message}
    if success:
        payload['data'] = data if data is not None else {}
    else:
        payload['error_code'] = error_code
    return JsonResponse(payload, status=status)


def _audit(event_type, action, message, reference_id=''):
    AuditLog.objects.create(
        event_type=event_type,
        action=action,
        message=message[:255],
        reference_id=str(reference_id)[:80],
    )


def _order_payload(order):
    items = []
    for item in order.items.select_related('product').all():
        items.append({
            'item_id': item.id,
            'product_id': item.product_id,
            'product_name': item.product.name,
            'qty': item.qty,
            'unit_price': str(item.unit_price),
            'line_total': str(item.line_total),
            'item_status': item.item_status,
        })
    payments = []
    for p in order.payments.all():
        payments.append({
            'id': p.id,
            'method': p.method,
            'amount': str(p.amount),
            'txn_ref': p.txn_ref,
            'paid_at': p.paid_at.isoformat(),
        })
    return {
        'id': order.id,
        'order_no': order.order_no,
        'order_type': order.order_type,
        'table_no': order.table_no,
        'status': order.status,
        'subtotal': str(order.subtotal),
        'tax_amount': str(order.tax_amount),
        'discount_amount': str(order.discount_amount),
        'grand_total': str(order.grand_total),
        'payment_status': order.payment_status,
        'notes': order.notes,
        'created_at': order.created_at.isoformat(),
        'items': items,
        'payments': payments,
    }


def _next_order_no():
    prefix = f"ORD-{timezone.now().strftime('%Y%m%d')}-"
    last = (
        Order.objects.filter(order_no__startswith=prefix)
        .order_by('-order_no')
        .values_list('order_no', flat=True)
        .first()
    )
    if last:
        try:
            seq = int(last.split('-')[-1]) + 1
        except (ValueError, IndexError):
            seq = 1
    else:
        seq = 1
    return f'{prefix}{seq:04d}'


def _date_range(request):
    start_str = request.GET.get('start_date', '')
    end_str = request.GET.get('end_date', '')
    now = timezone.now()
    try:
        start_dt = timezone.datetime.strptime(start_str, '%Y-%m-%d').replace(
            hour=0, minute=0, second=0, microsecond=0, tzinfo=now.tzinfo
        )
    except ValueError:
        start_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        end_dt = timezone.datetime.strptime(end_str, '%Y-%m-%d').replace(
            hour=23, minute=59, second=59, microsecond=999999, tzinfo=now.tzinfo
        )
    except ValueError:
        end_dt = now
    return start_dt, end_dt


def api_login_required(view_func):
    """Decorator for API views — returns JSON 401 instead of redirect."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return _response(False, 'Authentication required.', error_code='AUTH_REQUIRED', status=401)
        return view_func(request, *args, **kwargs)
    return wrapper


def admin_required(view_func):
    """Page view decorator — only Django staff users (is_staff=True or is_superuser)."""
    @wraps(view_func)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.is_staff:
            return redirect('pos')
        return view_func(request, *args, **kwargs)
    return wrapper


# ---------------------------------------------------------------------------
# Auth views
# ---------------------------------------------------------------------------

def login_view(request):
    if request.user.is_authenticated:
        return redirect('pos')
    error = None
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect(request.GET.get('next') or 'pos')
        error = 'Invalid username or password.'
    return render(request, 'core/login.html', {'error': error})


def logout_view(request):
    logout(request)
    return redirect('login')


# ---------------------------------------------------------------------------
# Page views (render templates)
# ---------------------------------------------------------------------------

@login_required
def pos_view(request):
    return render(request, 'core/pos.html')


@admin_required
def dashboard_view(request):
    return render(request, 'core/dashboard.html')


@admin_required
def inventory_view(request):
    return render(request, 'core/inventory.html')


@admin_required
def reports_view(request):
    return render(request, 'core/reports.html')


@login_required
def shifts_view(request):
    return render(request, 'core/shifts.html')


# ---------------------------------------------------------------------------
# API: Tables
# ---------------------------------------------------------------------------

@api_login_required
@csrf_exempt
@require_http_methods(['GET'])
def tables_list(request):
    tables = Table.objects.filter(is_active=True)
    active_orders = (
        Order.objects.filter(
            status__in=[
                Order.StatusChoices.OPEN,
                Order.StatusChoices.CONFIRMED,
                Order.StatusChoices.PREPARING,
                Order.StatusChoices.SERVED,
            ],
            table_no__isnull=False,
        )
        .exclude(table_no='')
        .values('table_no', 'id', 'order_no', 'grand_total')
    )
    order_map = {o['table_no']: o for o in active_orders}

    result = []
    for t in tables:
        active = order_map.get(t.name)
        result.append({
            'id': t.id,
            'name': t.name,
            'capacity': t.capacity,
            'status': 'OCCUPIED' if active else 'FREE',
            'order_id': active['id'] if active else None,
            'order_no': active['order_no'] if active else None,
            'grand_total': str(active['grand_total']) if active else None,
        })
    return _response(True, 'OK', result)


# ---------------------------------------------------------------------------
# API: Dashboard
# ---------------------------------------------------------------------------

@api_login_required
@csrf_exempt
@require_http_methods(['GET'])
def dashboard_overview(request):
    start_dt, end_dt = _date_range(request)
    summary = _sales_report_data(start_dt, end_dt)
    active_orders = Order.objects.filter(
        status__in=[Order.StatusChoices.OPEN, Order.StatusChoices.CONFIRMED, Order.StatusChoices.PREPARING]
    ).count()
    low_stock_count = Ingredient.objects.filter(
        is_active=True, current_qty__lte=models_min_qty_alert_f()
    ).count()
    shift = Shift.objects.filter(status=Shift.ShiftStatusChoices.OPEN).order_by('-opened_at').first()
    shift_data = None
    if shift:
        shift_data = {
            'id': shift.id,
            'staff_name': shift.staff_name,
            'counter_name': shift.counter_name,
            'opened_at': shift.opened_at.isoformat(),
            'opening_cash': str(shift.opening_cash),
        }
    return _response(True, 'OK', {
        'start_date': start_dt.date().isoformat(),
        'end_date': end_dt.date().isoformat(),
        'summary': summary,
        'active_orders': active_orders,
        'low_stock_count': low_stock_count,
        'current_shift': shift_data,
    })


def models_min_qty_alert_f():
    from django.db.models import F
    return F('min_qty_alert')


@api_login_required
@csrf_exempt
@require_http_methods(['GET'])
def activity_logs(request):
    try:
        limit = min(int(request.GET.get('limit', 50)), 200)
    except ValueError:
        limit = 50
    logs = AuditLog.objects.all()[:limit]
    data = [
        {
            'id': log.id,
            'type': log.event_type,
            'action': log.action,
            'message': log.message,
            'reference_id': log.reference_id,
            'timestamp': log.created_at.strftime('%Y-%m-%d %H:%M'),
        }
        for log in logs
    ]
    return _response(True, 'OK', data)


# ---------------------------------------------------------------------------
# API: Categories & Products
# ---------------------------------------------------------------------------

@api_login_required
@csrf_exempt
@require_http_methods(['GET'])
def categories(request):
    cats = Category.objects.filter(is_active=True)
    return _response(True, 'OK', [{'id': c.id, 'name': c.name} for c in cats])


@api_login_required
@csrf_exempt
@require_http_methods(['GET'])
def products(request):
    qs = Product.objects.filter(is_active=True).select_related('category')
    cat_id = request.GET.get('category_id')
    if cat_id:
        qs = qs.filter(category_id=cat_id)
    data = [
        {
            'id': p.id,
            'name': p.name,
            'sku': p.sku,
            'price': str(p.price),
            'tax_percent': str(p.tax_percent),
            'category_id': p.category_id,
            'category_name': p.category.name if p.category else '',
        }
        for p in qs
    ]
    return _response(True, 'OK', data)


# ---------------------------------------------------------------------------
# API: Orders
# ---------------------------------------------------------------------------

@api_login_required
@csrf_exempt
@require_http_methods(['GET', 'POST'])
def orders(request):
    if request.method == 'GET':
        qs = Order.objects.prefetch_related('items__product', 'payments')
        status_filter = request.GET.get('status')
        payment_filter = request.GET.get('payment_status')
        search = request.GET.get('q', '').strip()
        active_only = request.GET.get('active_only', '') == 'true'
        start_dt, end_dt = _date_range(request)

        if active_only:
            qs = qs.filter(
                status__in=[
                    Order.StatusChoices.OPEN,
                    Order.StatusChoices.CONFIRMED,
                    Order.StatusChoices.PREPARING,
                    Order.StatusChoices.SERVED,
                ]
            )
        else:
            qs = qs.filter(created_at__gte=start_dt, created_at__lte=end_dt)
        if status_filter:
            qs = qs.filter(status=status_filter)
        if payment_filter:
            qs = qs.filter(payment_status=payment_filter)
        if search:
            qs = qs.filter(
                Q(order_no__icontains=search)
                | Q(table_no__icontains=search)
                | Q(items__product__name__icontains=search)
            ).distinct()
        return _response(True, 'OK', [_order_payload(o) for o in qs[:100]])

    # POST — create order
    body = _json_body(request)
    if body is None:
        return _response(False, 'Invalid JSON', status=400)

    order_type = body.get('order_type', 'DINE_IN').upper()
    if order_type not in Order.OrderTypeChoices.values:
        return _response(False, 'Invalid order_type', status=400)

    table_no = body.get('table_no') or None

    with transaction.atomic():
        order = Order.objects.create(
            order_no=_next_order_no(),
            order_type=order_type,
            table_no=table_no,
        )
        items_data = body.get('items', [])
        for item_data in items_data:
            try:
                product = Product.objects.get(pk=item_data['product_id'], is_active=True)
            except (Product.DoesNotExist, KeyError):
                continue
            qty = max(1, int(item_data.get('qty', 1)))
            OrderItem.objects.create(order=order, product=product, qty=qty, unit_price=product.price)
        if items_data:
            recompute_order_totals(order)
        if body.get('auto_confirm'):
            try:
                consume_stock_for_order(order)
                order.status = Order.StatusChoices.CONFIRMED
                order.save(update_fields=['status'])
            except StockError:
                pass

    _audit('ORDER', 'create', f'Order {order.order_no} created ({order_type})', order.id)
    return _response(True, 'Order created', _order_payload(order), status=201)


@api_login_required
@csrf_exempt
@require_http_methods(['GET'])
def order_detail(request, order_id):
    order = get_object_or_404(Order, pk=order_id)
    return _response(True, 'OK', _order_payload(order))


@api_login_required
@csrf_exempt
@require_http_methods(['POST'])
def add_order_item(request, order_id):
    body = _json_body(request)
    if body is None:
        return _response(False, 'Invalid JSON', status=400)
    order = get_object_or_404(Order, pk=order_id)
    if order.status in [Order.StatusChoices.PAID, Order.StatusChoices.CANCELLED]:
        return _response(False, 'Cannot modify a closed order', status=400)
    try:
        product = Product.objects.get(pk=body['product_id'], is_active=True)
    except (Product.DoesNotExist, KeyError):
        return _response(False, 'Product not found', status=404)
    qty = max(1, int(body.get('qty', 1)))
    with transaction.atomic():
        existing = order.items.filter(product=product, item_status=OrderItem.ItemStatusChoices.OPEN).first()
        if existing:
            existing.qty += qty
            existing.save()
            item = existing
        else:
            item = OrderItem.objects.create(order=order, product=product, qty=qty, unit_price=product.price)
        recompute_order_totals(order)
    return _response(True, 'Item added', {
        'item_id': item.id,
        'product_id': item.product_id,
        'product_name': item.product.name,
        'qty': item.qty,
        'unit_price': str(item.unit_price),
        'line_total': str(item.line_total),
        'order_subtotal': str(order.subtotal),
        'order_tax': str(order.tax_amount),
        'order_total': str(order.grand_total),
    })


@api_login_required
@csrf_exempt
@require_http_methods(['PATCH', 'DELETE'])
def order_item_detail(request, order_id, item_id):
    order = get_object_or_404(Order, pk=order_id)
    item = get_object_or_404(OrderItem, pk=item_id, order=order)
    if order.status in [Order.StatusChoices.PAID, Order.StatusChoices.CANCELLED]:
        return _response(False, 'Cannot modify a closed order', status=400)

    if request.method == 'DELETE':
        item.delete()
        recompute_order_totals(order)
        return _response(True, 'Item removed', {
            'order_subtotal': str(order.subtotal),
            'order_tax': str(order.tax_amount),
            'order_total': str(order.grand_total),
        })

    body = _json_body(request)
    if body is None:
        return _response(False, 'Invalid JSON', status=400)
    if 'qty' in body:
        qty = int(body['qty'])
        if qty <= 0:
            item.delete()
            recompute_order_totals(order)
            return _response(True, 'Item removed', {})
        item.qty = qty
        item.save()
    recompute_order_totals(order)
    return _response(True, 'Item updated', {
        'item_id': item.id,
        'qty': item.qty,
        'line_total': str(item.line_total),
        'order_subtotal': str(order.subtotal),
        'order_tax': str(order.tax_amount),
        'order_total': str(order.grand_total),
    })


@api_login_required
@csrf_exempt
@require_http_methods(['POST'])
def confirm_order(request, order_id):
    order = get_object_or_404(Order, pk=order_id)
    if order.status not in [Order.StatusChoices.OPEN, Order.StatusChoices.CONFIRMED]:
        return _response(False, f'Cannot confirm order in status {order.status}', status=400)
    if not order.items.filter(item_status=OrderItem.ItemStatusChoices.OPEN).exists():
        return _response(False, 'Order has no items', status=400)
    try:
        consume_stock_for_order(order)
    except StockError as e:
        return _response(False, str(e), error_code='INSUFFICIENT_STOCK', status=409)
    order.status = Order.StatusChoices.CONFIRMED
    order.updated_at = timezone.now()
    order.save(update_fields=['status', 'updated_at'])
    _audit('ORDER', 'confirm', f'Order {order.order_no} confirmed', order.id)
    return _response(True, 'Order confirmed', _order_payload(order))


@api_login_required
@csrf_exempt
@require_http_methods(['POST'])
def cancel_order(request, order_id):
    order = get_object_or_404(Order, pk=order_id)
    if order.status in [Order.StatusChoices.PAID, Order.StatusChoices.CANCELLED]:
        return _response(False, f'Cannot cancel order in status {order.status}', status=400)
    with transaction.atomic():
        if order.status == Order.StatusChoices.CONFIRMED:
            restore_stock_for_order(order)
        order.status = Order.StatusChoices.CANCELLED
        order.updated_at = timezone.now()
        order.save(update_fields=['status', 'updated_at'])
    _audit('ORDER', 'cancel', f'Order {order.order_no} cancelled', order.id)
    return _response(True, 'Order cancelled', _order_payload(order))


@api_login_required
@csrf_exempt
@require_http_methods(['POST'])
def add_payment(request, order_id):
    body = _json_body(request)
    if body is None:
        return _response(False, 'Invalid JSON', status=400)
    order = get_object_or_404(Order, pk=order_id)
    if order.status == Order.StatusChoices.CANCELLED:
        return _response(False, 'Order is cancelled', status=400)
    method = body.get('method', '').upper()
    if method not in Payment.MethodChoices.values:
        return _response(False, f'Invalid method. Use: {", ".join(Payment.MethodChoices.values)}', status=400)
    try:
        amount = Decimal(str(body.get('amount', '')))
        if amount <= 0:
            raise InvalidOperation
    except InvalidOperation:
        return _response(False, 'Invalid amount', status=400)
    txn_ref = body.get('txn_ref', '')
    with transaction.atomic():
        Payment.objects.create(order=order, method=method, amount=amount, txn_ref=txn_ref)
        paid_total = order.payments.aggregate(total=Sum('amount'))['total'] or Decimal('0')
        if paid_total >= order.grand_total:
            order.payment_status = Order.PaymentStatusChoices.PAID
        elif paid_total > 0:
            order.payment_status = Order.PaymentStatusChoices.PARTIAL
        order.updated_at = timezone.now()
        order.save(update_fields=['payment_status', 'updated_at'])
    _audit('PAYMENT', 'add', f'Payment {method} NPR {amount} for {order.order_no}', order.id)
    return _response(True, 'Payment recorded', _order_payload(order))


@api_login_required
@csrf_exempt
@require_http_methods(['POST'])
def checkout_order(request, order_id):
    """Single-step POS checkout: confirm stock + record payment(s) + close order.
    Accepts a 'payments' list to support split payments (cash + fonepay)."""
    body = _json_body(request)
    if body is None:
        return _response(False, 'Invalid JSON', status=400)

    # Parse payments list (supports single or split)
    raw_payments = body.get('payments')
    if not raw_payments:
        return _response(False, 'No payments provided', status=400)

    parsed = []
    for p in raw_payments:
        method = str(p.get('method', '')).upper()
        if method not in Payment.MethodChoices.values:
            return _response(False, f'Invalid method: {method}', status=400)
        try:
            amount = Decimal(str(p.get('amount', '')))
            if amount <= 0:
                raise InvalidOperation
        except InvalidOperation:
            return _response(False, f'Invalid amount for {method}', status=400)
        parsed.append({'method': method, 'amount': amount, 'txn_ref': str(p.get('txn_ref', '') or '')})

    discount_raw = body.get('discount', '0')
    try:
        discount = max(Decimal(str(discount_raw)), Decimal('0'))
    except InvalidOperation:
        discount = Decimal('0')

    with transaction.atomic():
        order = get_object_or_404(Order.objects.select_for_update(), pk=order_id)
        if order.status == Order.StatusChoices.PAID:
            return _response(False, 'Order already paid', status=400)
        if order.status == Order.StatusChoices.CANCELLED:
            return _response(False, 'Order is cancelled', status=400)
        if not order.items.exists():
            return _response(False, 'Order has no items', status=400)

        # Apply discount and recompute grand total
        if discount > 0:
            order.discount_amount = discount
            order.grand_total = max(order.subtotal + order.tax_amount - discount, Decimal('0'))
            order.save(update_fields=['discount_amount', 'grand_total'])

        # Validate total paid covers the bill
        total_paid = sum(p['amount'] for p in parsed)
        if total_paid < order.grand_total - Decimal('0.01'):
            return _response(
                False,
                f'Total paid (NPR {total_paid}) is less than order total (NPR {order.grand_total})',
                status=400,
            )

        # Deduct stock if not already confirmed
        if order.status == Order.StatusChoices.OPEN:
            try:
                consume_stock_for_order(order)
            except StockError:
                pass  # Don't block payment for missing recipes

        # Record one Payment row per method
        for p in parsed:
            Payment.objects.create(order=order, method=p['method'], amount=p['amount'], txn_ref=p['txn_ref'])

        order.status = Order.StatusChoices.PAID
        order.payment_status = Order.PaymentStatusChoices.PAID
        order.updated_at = timezone.now()
        order.save(update_fields=['status', 'payment_status', 'updated_at'])

    summary = ', '.join(f"{p['method']} NPR {p['amount']}" for p in parsed)
    _audit('PAYMENT', 'checkout', f'Order {order.order_no} paid: {summary}', order.id)
    return _response(True, 'Payment successful', _order_payload(order))


@api_login_required
@csrf_exempt
@require_http_methods(['POST'])
def close_order(request, order_id):
    order = get_object_or_404(Order, pk=order_id)
    if order.payment_status != Order.PaymentStatusChoices.PAID:
        return _response(False, 'Order is not fully paid', status=400)
    order.status = Order.StatusChoices.PAID
    order.updated_at = timezone.now()
    order.save(update_fields=['status', 'updated_at'])
    return _response(True, 'Order closed', _order_payload(order))


# ---------------------------------------------------------------------------
# API: Inventory
# ---------------------------------------------------------------------------

@api_login_required
@csrf_exempt
@require_http_methods(['GET'])
def ingredients(request):
    from django.db.models import F
    qs = Ingredient.objects.filter(is_active=True)
    data = [
        {
            'id': i.id,
            'name': i.name,
            'unit': i.unit,
            'current_qty': str(i.current_qty),
            'min_qty_alert': str(i.min_qty_alert),
            'is_low_stock': i.current_qty <= i.min_qty_alert,
        }
        for i in qs
    ]
    return _response(True, 'OK', data)


@api_login_required
@csrf_exempt
@require_http_methods(['GET'])
def low_stock_ingredients(request):
    from django.db.models import F
    qs = Ingredient.objects.filter(is_active=True, current_qty__lte=F('min_qty_alert'))
    data = [
        {
            'id': i.id,
            'name': i.name,
            'unit': i.unit,
            'current_qty': str(i.current_qty),
            'min_qty_alert': str(i.min_qty_alert),
        }
        for i in qs
    ]
    return _response(True, 'OK', data)


@api_login_required
@csrf_exempt
@require_http_methods(['POST'])
def inventory_purchase(request):
    body = _json_body(request)
    if body is None:
        return _response(False, 'Invalid JSON', status=400)
    try:
        ingredient = Ingredient.objects.get(pk=body['ingredient_id'], is_active=True)
    except (Ingredient.DoesNotExist, KeyError):
        return _response(False, 'Ingredient not found', status=404)
    try:
        qty = Decimal(str(body['qty']))
        if qty <= 0:
            raise InvalidOperation
    except (InvalidOperation, KeyError):
        return _response(False, 'Invalid qty', status=400)
    InventoryMovement.objects.create(
        ingredient=ingredient,
        movement_type=InventoryMovement.MovementTypeChoices.PURCHASE,
        qty_change=qty,
        reference_type=InventoryMovement.ReferenceTypeChoices.PURCHASE,
        note=body.get('note', 'Purchase entry'),
    )
    _audit('INVENTORY', 'purchase', f'Purchased {qty}{ingredient.unit} of {ingredient.name}', ingredient.id)
    ingredient.refresh_from_db()
    return _response(True, 'Purchase recorded', {
        'ingredient_id': ingredient.id,
        'name': ingredient.name,
        'new_qty': str(ingredient.current_qty),
    })


@api_login_required
@csrf_exempt
@require_http_methods(['POST'])
def inventory_adjustment(request):
    body = _json_body(request)
    if body is None:
        return _response(False, 'Invalid JSON', status=400)
    try:
        ingredient = Ingredient.objects.get(pk=body['ingredient_id'], is_active=True)
    except (Ingredient.DoesNotExist, KeyError):
        return _response(False, 'Ingredient not found', status=404)
    try:
        qty_change = Decimal(str(body['qty_change']))
    except (InvalidOperation, KeyError):
        return _response(False, 'Invalid qty_change', status=400)
    if ingredient.current_qty + qty_change < 0:
        return _response(False, 'Adjustment would result in negative stock', status=400)
    InventoryMovement.objects.create(
        ingredient=ingredient,
        movement_type=InventoryMovement.MovementTypeChoices.ADJUST,
        qty_change=qty_change,
        reference_type=InventoryMovement.ReferenceTypeChoices.MANUAL,
        note=body.get('note', 'Manual adjustment'),
    )
    _audit('INVENTORY', 'adjust', f'Adjusted {ingredient.name} by {qty_change}', ingredient.id)
    ingredient.refresh_from_db()
    return _response(True, 'Adjustment recorded', {'new_qty': str(ingredient.current_qty)})


@api_login_required
@csrf_exempt
@require_http_methods(['GET'])
def inventory_movements(request):
    qs = InventoryMovement.objects.select_related('ingredient').order_by('-created_at')
    ing_id = request.GET.get('ingredient_id')
    if ing_id:
        qs = qs.filter(ingredient_id=ing_id)
    qs = qs[:200]
    data = [
        {
            'id': m.id,
            'ingredient': m.ingredient.name,
            'movement_type': m.movement_type,
            'qty_change': str(m.qty_change),
            'note': m.note,
            'created_at': m.created_at.strftime('%Y-%m-%d %H:%M'),
        }
        for m in qs
    ]
    return _response(True, 'OK', data)


# ---------------------------------------------------------------------------
# API: Shifts
# ---------------------------------------------------------------------------

@api_login_required
@csrf_exempt
@require_http_methods(['GET'])
def current_shift(request):
    shift = Shift.objects.filter(status=Shift.ShiftStatusChoices.OPEN).order_by('-opened_at').first()
    if not shift:
        return _response(True, 'No active shift', None)
    return _response(True, 'OK', {
        'id': shift.id,
        'staff_name': shift.staff_name,
        'counter_name': shift.counter_name,
        'opening_cash': str(shift.opening_cash),
        'opened_at': shift.opened_at.isoformat(),
        'status': shift.status,
    })


@api_login_required
@csrf_exempt
@require_http_methods(['POST'])
def open_shift(request):
    if Shift.objects.filter(status=Shift.ShiftStatusChoices.OPEN).exists():
        return _response(False, 'A shift is already open', status=400)
    body = _json_body(request)
    if body is None:
        return _response(False, 'Invalid JSON', status=400)
    try:
        opening_cash = Decimal(str(body.get('opening_cash', 0)))
    except InvalidOperation:
        opening_cash = Decimal('0')
    shift = Shift.objects.create(
        staff_name=body.get('staff_name', ''),
        counter_name=body.get('counter_name', ''),
        opening_cash=opening_cash,
    )
    _audit('SHIFT', 'open', f'Shift #{shift.id} opened by {shift.staff_name}', shift.id)
    return _response(True, 'Shift opened', {'id': shift.id, 'opened_at': shift.opened_at.isoformat()}, status=201)


@api_login_required
@csrf_exempt
@require_http_methods(['POST'])
def close_shift(request, shift_id):
    shift = get_object_or_404(Shift, pk=shift_id, status=Shift.ShiftStatusChoices.OPEN)
    body = _json_body(request) or {}
    try:
        closing_cash_actual = Decimal(str(body.get('closing_cash_actual', 0)))
    except InvalidOperation:
        closing_cash_actual = Decimal('0')
    cash_sales = Payment.objects.filter(
        method=Payment.MethodChoices.CASH,
        paid_at__gte=shift.opened_at,
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
    closing_cash_expected = shift.opening_cash + cash_sales
    shift.closed_at = timezone.now()
    shift.closing_cash_expected = closing_cash_expected
    shift.closing_cash_actual = closing_cash_actual
    shift.status = Shift.ShiftStatusChoices.CLOSED
    shift.notes = body.get('notes', '')
    shift.save()
    _audit('SHIFT', 'close', f'Shift #{shift.id} closed', shift.id)
    return _response(True, 'Shift closed', {
        'id': shift.id,
        'opening_cash': str(shift.opening_cash),
        'cash_sales': str(cash_sales),
        'closing_cash_expected': str(closing_cash_expected),
        'closing_cash_actual': str(closing_cash_actual),
        'variance': str(closing_cash_actual - closing_cash_expected),
    })


# ---------------------------------------------------------------------------
# API: Reports
# ---------------------------------------------------------------------------

def _sales_report_data(start_dt, end_dt):
    paid_orders = Order.objects.filter(
        status=Order.StatusChoices.PAID,
        created_at__gte=start_dt,
        created_at__lte=end_dt,
    )
    agg = paid_orders.aggregate(
        gross_sales=Sum('grand_total'),
        order_count=Count('id'),
    )
    top_products = (
        OrderItem.objects.filter(
            order__status=Order.StatusChoices.PAID,
            order__created_at__gte=start_dt,
            order__created_at__lte=end_dt,
            item_status=OrderItem.ItemStatusChoices.OPEN,
        )
        .values('product__name')
        .annotate(total_qty=Sum('qty'), revenue=Sum('line_total'))
        .order_by('-revenue')[:10]
    )
    payment_breakdown = (
        Payment.objects.filter(paid_at__gte=start_dt, paid_at__lte=end_dt)
        .values('method')
        .annotate(total=Sum('amount'), count=Count('id'))
    )
    return {
        'gross_sales': str(agg['gross_sales'] or 0),
        'order_count': agg['order_count'],
        'paid_order_count': paid_orders.filter(payment_status=Order.PaymentStatusChoices.PAID).count(),
        'top_products': [
            {
                'product_name': p['product__name'],
                'total_qty': p['total_qty'],
                'revenue': str(p['revenue'] or 0),
            }
            for p in top_products
        ],
        'payment_breakdown': [
            {
                'method': pb['method'],
                'total': str(pb['total'] or 0),
                'count': pb['count'],
            }
            for pb in payment_breakdown
        ],
    }


@api_login_required
@csrf_exempt
@require_http_methods(['GET'])
def report_sales(request):
    start_dt, end_dt = _date_range(request)
    data = _sales_report_data(start_dt, end_dt)
    data['start_date'] = start_dt.date().isoformat()
    data['end_date'] = end_dt.date().isoformat()
    _audit('REPORT', 'sales', f'Sales report {data["start_date"]} to {data["end_date"]}')
    return _response(True, 'OK', data)


@api_login_required
@csrf_exempt
@require_http_methods(['GET'])
def report_sales_export(request):
    start_dt, end_dt = _date_range(request)
    orders_qs = Order.objects.filter(
        status=Order.StatusChoices.PAID,
        created_at__gte=start_dt,
        created_at__lte=end_dt,
    ).prefetch_related('payments')
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="sales_{start_dt.date()}_{end_dt.date()}.csv"'
    writer = csv.writer(response)
    writer.writerow(['Order No', 'Date', 'Type', 'Table', 'Subtotal', 'Tax', 'Discount', 'Grand Total', 'Payment Methods'])
    for o in orders_qs:
        methods = ', '.join(set(p.method for p in o.payments.all()))
        writer.writerow([
            o.order_no, o.created_at.strftime('%Y-%m-%d %H:%M'),
            o.order_type, o.table_no or '-',
            o.subtotal, o.tax_amount, o.discount_amount, o.grand_total,
            methods,
        ])
    return response


def _inventory_report_data(start_dt, end_dt):
    from django.db.models import F
    low_stock = Ingredient.objects.filter(is_active=True, current_qty__lte=F('min_qty_alert'))
    movement_summary = (
        InventoryMovement.objects.filter(created_at__gte=start_dt, created_at__lte=end_dt)
        .values('movement_type')
        .annotate(count=Count('id'), total_qty=Sum('qty_change'))
    )
    top_consumed = (
        InventoryMovement.objects.filter(
            movement_type=InventoryMovement.MovementTypeChoices.CONSUME,
            created_at__gte=start_dt,
            created_at__lte=end_dt,
        )
        .values('ingredient__name', 'ingredient__unit')
        .annotate(total_consumed=Sum('qty_change'))
        .order_by('total_consumed')[:10]
    )
    return {
        'low_stock': [
            {'name': i.name, 'unit': i.unit, 'current_qty': str(i.current_qty), 'min_qty_alert': str(i.min_qty_alert)}
            for i in low_stock
        ],
        'movement_summary': [
            {'movement_type': m['movement_type'], 'count': m['count'], 'total_qty': str(m['total_qty'] or 0)}
            for m in movement_summary
        ],
        'top_consumed': [
            {'name': t['ingredient__name'], 'unit': t['ingredient__unit'], 'consumed': str(abs(t['total_consumed'] or 0))}
            for t in top_consumed
        ],
    }


@api_login_required
@csrf_exempt
@require_http_methods(['GET'])
def report_inventory(request):
    start_dt, end_dt = _date_range(request)
    data = _inventory_report_data(start_dt, end_dt)
    data['start_date'] = start_dt.date().isoformat()
    data['end_date'] = end_dt.date().isoformat()
    return _response(True, 'OK', data)


@api_login_required
@csrf_exempt
@require_http_methods(['GET'])
def report_inventory_export(request):
    start_dt, end_dt = _date_range(request)
    qs = Ingredient.objects.filter(is_active=True)
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="inventory_{start_dt.date()}_{end_dt.date()}.csv"'
    writer = csv.writer(response)
    writer.writerow(['Ingredient', 'Unit', 'Current Qty', 'Min Alert', 'Status'])
    from django.db.models import F
    for i in qs:
        status = 'LOW' if i.current_qty <= i.min_qty_alert else 'OK'
        writer.writerow([i.name, i.unit, i.current_qty, i.min_qty_alert, status])
    return response


@api_login_required
@csrf_exempt
@require_http_methods(['GET'])
def report_day_close(request):
    date_str = request.GET.get('date', timezone.now().strftime('%Y-%m-%d'))
    try:
        target_date = timezone.datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        target_date = timezone.now().date()
    start_dt = timezone.datetime.combine(target_date, timezone.datetime.min.time()).replace(tzinfo=timezone.get_current_timezone())
    end_dt = timezone.datetime.combine(target_date, timezone.datetime.max.time()).replace(tzinfo=timezone.get_current_timezone())

    day_orders = Order.objects.filter(created_at__gte=start_dt, created_at__lte=end_dt)
    payments = Payment.objects.filter(paid_at__gte=start_dt, paid_at__lte=end_dt)
    agg = payments.aggregate(total=Sum('amount'))
    cash_total = payments.filter(method=Payment.MethodChoices.CASH).aggregate(t=Sum('amount'))['t'] or 0
    fonepay_total = payments.filter(method=Payment.MethodChoices.FONEPAY).aggregate(t=Sum('amount'))['t'] or 0

    return _response(True, 'OK', {
        'date': target_date.isoformat(),
        'total_orders': day_orders.count(),
        'paid_orders': day_orders.filter(status=Order.StatusChoices.PAID).count(),
        'cancelled_orders': day_orders.filter(status=Order.StatusChoices.CANCELLED).count(),
        'gross_sales': str(agg['total'] or 0),
        'cash_total': str(cash_total),
        'fonepay_total': str(fonepay_total),
    })


# ---------------------------------------------------------------------------
# Credit System
# ---------------------------------------------------------------------------

@login_required
def credit_view(request):
    return render(request, 'core/credit.html')


def _credit_balance(account):
    agg = account.records.aggregate(
        credit=Sum('amount', filter=Q(record_type='CREDIT')),
        repaid=Sum('amount', filter=Q(record_type='REPAYMENT')),
    )
    credit = agg['credit'] or Decimal('0')
    repaid = agg['repaid'] or Decimal('0')
    return credit, repaid, credit - repaid


@api_login_required
@csrf_exempt
@require_http_methods(['POST'])
def credit_checkout(request, order_id):
    """Close an order as credit — marks it PAID and records a CreditRecord."""
    body = _json_body(request)
    if body is None:
        return _response(False, 'Invalid JSON', status=400)

    customer_name = body.get('customer_name', '').strip()
    if not customer_name:
        return _response(False, 'Customer name is required', status=400)

    try:
        amount = Decimal(str(body.get('amount', '')))
        if amount <= 0:
            raise InvalidOperation
    except InvalidOperation:
        return _response(False, 'Invalid amount', status=400)

    phone = body.get('phone', '').strip()
    notes = body.get('notes', '').strip()
    discount_raw = body.get('discount', '0')
    try:
        discount = max(Decimal(str(discount_raw)), Decimal('0'))
    except InvalidOperation:
        discount = Decimal('0')

    with transaction.atomic():
        order = get_object_or_404(Order.objects.select_for_update(), pk=order_id)
        if order.status == Order.StatusChoices.PAID:
            return _response(False, 'Order already paid', status=400)
        if order.status == Order.StatusChoices.CANCELLED:
            return _response(False, 'Order is cancelled', status=400)
        if not order.items.exists():
            return _response(False, 'Order has no items', status=400)

        if discount > 0:
            order.discount_amount = discount
            order.grand_total = max(order.subtotal + order.tax_amount - discount, Decimal('0'))
            order.save(update_fields=['discount_amount', 'grand_total'])

        if order.status == Order.StatusChoices.OPEN:
            try:
                consume_stock_for_order(order)
            except StockError:
                pass

        # Find or create the credit account (case-insensitive match)
        try:
            account = CreditAccount.objects.get(name__iexact=customer_name)
        except CreditAccount.DoesNotExist:
            account = CreditAccount.objects.create(name=customer_name, phone=phone)
        if phone and not account.phone:
            account.phone = phone
            account.save(update_fields=['phone', 'updated_at'])

        CreditRecord.objects.create(
            account=account,
            record_type=CreditRecord.RecordType.CREDIT,
            amount=amount,
            order=order,
            notes=notes,
        )

        order.status = Order.StatusChoices.PAID
        order.payment_status = Order.PaymentStatusChoices.PAID
        order.updated_at = timezone.now()
        order.save(update_fields=['status', 'payment_status', 'updated_at'])

    _audit('PAYMENT', 'credit', f'Order {order.order_no} credited NPR {amount} to {customer_name}', order.id)
    return _response(True, f'Recorded as credit for {customer_name}', _order_payload(order))


@api_login_required
@csrf_exempt
@require_http_methods(['GET'])
def credit_accounts(request):
    accounts = CreditAccount.objects.prefetch_related('records').order_by('name')
    result = []
    for a in accounts:
        credit, repaid, balance = _credit_balance(a)
        result.append({
            'id': a.id,
            'name': a.name,
            'phone': a.phone,
            'total_credit': str(credit),
            'total_repaid': str(repaid),
            'balance': str(balance),
        })
    return _response(True, 'OK', result)


@api_login_required
@csrf_exempt
@require_http_methods(['GET'])
def credit_account_detail(request, account_id):
    account = get_object_or_404(CreditAccount, pk=account_id)
    credit, repaid, balance = _credit_balance(account)
    records = [{
        'id': r.id,
        'record_type': r.record_type,
        'amount': str(r.amount),
        'order_no': r.order.order_no if r.order_id else None,
        'payment_method': r.payment_method,
        'notes': r.notes,
        'created_at': r.created_at.isoformat(),
    } for r in account.records.select_related('order').all()]
    return _response(True, 'OK', {
        'id': account.id,
        'name': account.name,
        'phone': account.phone,
        'total_credit': str(credit),
        'total_repaid': str(repaid),
        'balance': str(balance),
        'records': records,
    })


@api_login_required
@csrf_exempt
@require_http_methods(['POST'])
def credit_repay(request, account_id):
    body = _json_body(request)
    if body is None:
        return _response(False, 'Invalid JSON', status=400)

    account = get_object_or_404(CreditAccount, pk=account_id)
    _, _, balance = _credit_balance(account)

    if balance <= 0:
        return _response(False, 'No outstanding credit balance', status=400)

    try:
        amount = Decimal(str(body.get('amount', '')))
        if amount <= 0:
            raise InvalidOperation
    except InvalidOperation:
        return _response(False, 'Invalid amount', status=400)

    if amount > balance + Decimal('0.01'):
        return _response(
            False, f'Repayment NPR {amount} exceeds outstanding balance NPR {balance}', status=400
        )

    payment_method = body.get('payment_method', '').upper() or 'CASH'
    notes = body.get('notes', '').strip()

    CreditRecord.objects.create(
        account=account,
        record_type=CreditRecord.RecordType.REPAYMENT,
        amount=min(amount, balance),
        payment_method=payment_method,
        notes=notes,
    )

    new_balance = balance - amount
    _audit(
        'PAYMENT', 'credit_repay',
        f'{account.name} repaid NPR {amount} via {payment_method}. Balance: NPR {new_balance}',
        str(account.id),
    )
    return _response(True, f'Repayment recorded. Remaining balance: NPR {max(new_balance, Decimal("0"))}', {
        'account_id': account.id,
        'repaid': str(amount),
        'new_balance': str(max(new_balance, Decimal('0'))),
    })
