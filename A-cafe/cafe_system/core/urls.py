from django.urls import path

from . import views

urlpatterns = [
    path("dashboard/overview", views.dashboard_overview, name="dashboard_overview"),
    path("dashboard/activity-logs", views.activity_logs, name="activity_logs"),
    path("categories", views.categories, name="categories"),
    path("products", views.products, name="products"),
    path("inventory/ingredients", views.ingredients, name="ingredients"),
    path("inventory/ingredients/low-stock", views.low_stock_ingredients, name="low_stock_ingredients"),
    path("inventory/purchase", views.inventory_purchase, name="inventory_purchase"),
    path("inventory/adjustment", views.inventory_adjustment, name="inventory_adjustment"),
    path("inventory/movements", views.inventory_movements, name="inventory_movements"),
    path("reports/sales", views.report_sales, name="report_sales"),
    path("reports/sales/export", views.report_sales_export, name="report_sales_export"),
    path("reports/inventory", views.report_inventory, name="report_inventory"),
    path("reports/inventory/export", views.report_inventory_export, name="report_inventory_export"),
    path("reports/day-close", views.report_day_close, name="report_day_close"),
    path("shifts/current", views.current_shift, name="current_shift"),
    path("shifts/open", views.open_shift, name="open_shift"),
    path("shifts/<int:shift_id>/close", views.close_shift, name="close_shift"),
    path("orders", views.orders, name="orders"),
    path("orders/<int:order_id>", views.order_detail, name="order_detail"),
    path("orders/<int:order_id>/items", views.add_order_item, name="add_order_item"),
    path(
        "orders/<int:order_id>/items/<int:item_id>",
        views.order_item_detail,
        name="order_item_detail",
    ),
    path("orders/<int:order_id>/confirm", views.confirm_order, name="confirm_order"),
    path("orders/<int:order_id>/cancel", views.cancel_order, name="cancel_order"),
    path("orders/<int:order_id>/payment", views.add_payment, name="add_payment"),
    path("orders/<int:order_id>/close", views.close_order, name="close_order"),
]
