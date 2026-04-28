# core/admin.py
from django.contrib import admin
from .models import (
    Category,
    AuditLog,
    Ingredient,
    InventoryMovement,
    Order,
    OrderItem,
    Payment,
    Product,
    Recipe,
    Shift,
    StockReservation,
)

admin.site.register(Category)
admin.site.register(Product)
admin.site.register(Ingredient)
admin.site.register(Recipe)
admin.site.register(InventoryMovement)
admin.site.register(Order)
admin.site.register(OrderItem)
admin.site.register(StockReservation)
admin.site.register(Payment)
admin.site.register(Shift)
admin.site.register(AuditLog)
