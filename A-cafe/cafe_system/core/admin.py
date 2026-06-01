from django.contrib import admin
from django.utils.safestring import mark_safe
from .models import (
    AuditLog, Category, CreditAccount, CreditRecord, Ingredient, InventoryMovement,
    LowStockAlert, Order, OrderItem, Payment, Product, ProductStockMovement, Recipe,
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


class RecipeInline(admin.TabularInline):
    model = Recipe
    extra = 1
    fields = ('ingredient', 'qty_per_item')


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        'name', 'product_type', 'category', 'price', 'current_qty', 'min_qty_alert', 'is_active'
    )
    list_filter = ('product_type', 'category', 'is_active')
    search_fields = ('name', 'sku')
    list_editable = ('price', 'current_qty', 'min_qty_alert', 'is_active')
    inlines = [RecipeInline]
    fieldsets = (
        (None, {'fields': ('name', 'sku', 'category', 'product_type', 'is_active')}),
        ('Pricing', {'fields': ('price', 'tax_percent')}),
        ('Direct sale stock', {'fields': ('current_qty', 'min_qty_alert')}),
    )


@admin.register(Recipe)
class RecipeAdmin(admin.ModelAdmin):
    list_display = ('product', 'ingredient', 'qty_per_item')
    list_filter = ('product',)
    search_fields = ('product__name', 'ingredient__name')


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


@admin.register(InventoryMovement)
class InventoryMovementAdmin(admin.ModelAdmin):
    list_display = ('ingredient', 'movement_type', 'qty_change', 'deduction_source', 'reference_id', 'created_at')
    list_filter = ('movement_type', 'deduction_source', 'created_at')
    search_fields = ('ingredient__name', 'reference_id', 'note')
    readonly_fields = ('created_at',)

    def has_add_permission(self, request):
        return False


@admin.register(ProductStockMovement)
class ProductStockMovementAdmin(admin.ModelAdmin):
    list_display = ('product', 'movement_type', 'qty_change', 'deduction_source', 'order', 'created_at')
    list_filter = ('movement_type', 'deduction_source', 'created_at')
    readonly_fields = ('created_at',)

    def has_add_permission(self, request):
        return False


@admin.register(LowStockAlert)
class LowStockAlertAdmin(admin.ModelAdmin):
    list_display = ('item_type', 'message', 'current_qty', 'min_qty_alert', 'is_resolved', 'created_at')
    list_filter = ('item_type', 'is_resolved', 'created_at')
    list_editable = ('is_resolved',)


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
    readonly_fields = (
        'order_no', 'subtotal', 'tax_amount', 'grand_total',
        'inventory_deducted', 'created_at', 'updated_at',
    )
    inlines = [OrderItemInline, PaymentInline]
    fieldsets = (
        (None, {
            'fields': (
                'order_no', 'order_type', 'table_no', 'status',
                'payment_status', 'inventory_deducted', 'notes',
            )
        }),
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


# ── Credit ────────────────────────────────────────────────────────────────────
class CreditRecordInline(admin.TabularInline):
    model = CreditRecord
    extra = 0
    fields = ('record_type', 'amount', 'payment_method', 'order', 'notes', 'created_at')
    readonly_fields = ('created_at',)


@admin.register(CreditAccount)
class CreditAccountAdmin(admin.ModelAdmin):
    list_display = ('name', 'phone', 'created_at')
    search_fields = ('name', 'phone')
    inlines = [CreditRecordInline]


@admin.register(CreditRecord)
class CreditRecordAdmin(admin.ModelAdmin):
    list_display = ('account', 'record_type', 'amount', 'payment_method', 'order', 'created_at')
    list_filter = ('record_type', 'payment_method', 'created_at')
    search_fields = ('account__name',)
    readonly_fields = ('created_at',)


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
