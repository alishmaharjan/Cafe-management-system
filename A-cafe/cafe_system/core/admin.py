from django.contrib import admin
from django.utils.safestring import mark_safe
from .models import (
    AuditLog, Category, Ingredient, InventoryMovement,
    Order, OrderItem, Payment, Product, Recipe,
    Shift, StockReservation, Table,
)

admin.site.site_header = 'Chiya Garden — Admin'
admin.site.site_title = 'Chiya Garden'
admin.site.index_title = 'Cafe Management'


# ── Tables ────────────────────────────────────────────────────────────────────
@admin.register(Table)
class TableAdmin(admin.ModelAdmin):
    list_display = ('name', 'capacity', 'is_active')
    list_editable = ('capacity', 'is_active')
    ordering = ('name',)


# ── Menu ─────────────────────────────────────────────────────────────────────
@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_active')
    list_editable = ('is_active',)
    search_fields = ('name',)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'price', 'is_active')
    list_filter = ('category', 'is_active')
    search_fields = ('name',)
    list_editable = ('price', 'is_active')
    fieldsets = (
        (None, {'fields': ('name', 'category', 'is_active')}),
        ('Pricing', {'fields': ('price', 'tax_percent')}),
    )


# ── Inventory ─────────────────────────────────────────────────────────────────
@admin.register(Ingredient)
class IngredientAdmin(admin.ModelAdmin):
    list_display = ('name', 'unit', 'current_qty', 'min_qty_alert', 'stock_status', 'is_active')
    list_editable = ('current_qty', 'min_qty_alert', 'is_active')
    list_filter = ('unit', 'is_active')
    search_fields = ('name',)
    ordering = ('name',)

    @admin.display(description='Status')
    def stock_status(self, obj):
        if obj.current_qty <= obj.min_qty_alert:
            return mark_safe('<span style="color:#c0392b;font-weight:bold;">⚠ Low</span>')
        return mark_safe('<span style="color:#27ae60;">✔ OK</span>')


# ── Orders ────────────────────────────────────────────────────────────────────
class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    fields = ('product', 'qty', 'unit_price', 'line_total', 'item_status')
    readonly_fields = ('unit_price', 'line_total')


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0
    fields = ('method', 'amount', 'txn_ref', 'paid_at')
    readonly_fields = ('paid_at',)


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('order_no', 'order_type', 'table_no', 'status', 'grand_total', 'created_at')
    list_filter = ('status', 'order_type', 'created_at')
    search_fields = ('order_no', 'table_no')
    readonly_fields = ('order_no', 'subtotal', 'tax_amount', 'grand_total', 'created_at', 'updated_at')
    inlines = [OrderItemInline, PaymentInline]
    fieldsets = (
        (None, {'fields': ('order_no', 'order_type', 'table_no', 'status', 'payment_status', 'notes')}),
        ('Totals', {'fields': ('subtotal', 'tax_amount', 'discount_amount', 'grand_total')}),
        ('Timestamps', {'fields': ('created_at', 'updated_at')}),
    )


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('order', 'method', 'amount', 'txn_ref', 'paid_at')
    list_filter = ('method', 'paid_at')
    search_fields = ('order__order_no', 'txn_ref')
    readonly_fields = ('paid_at',)


# ── Shift ─────────────────────────────────────────────────────────────────────
@admin.register(Shift)
class ShiftAdmin(admin.ModelAdmin):
    list_display = ('id', 'staff_name', 'counter_name', 'status', 'opening_cash', 'closing_cash_actual', 'opened_at')
    list_filter = ('status',)
    readonly_fields = ('opened_at',)


# ── Audit Log (read-only) ─────────────────────────────────────────────────────
@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('event_type', 'action', 'message', 'reference_id', 'created_at')
    list_filter = ('event_type', 'created_at')
    search_fields = ('message', 'reference_id')
    readonly_fields = ('event_type', 'action', 'message', 'reference_id', 'created_at')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
