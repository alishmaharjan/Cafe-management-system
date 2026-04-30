from django.urls import path
from . import views

urlpatterns = [
    # Tables
    path('tables', views.tables_list, name='tables_list'),

    # Dashboard
    path('dashboard/overview', views.dashboard_overview, name='dashboard_overview'),
    path('dashboard/activity-logs', views.activity_logs, name='activity_logs'),

    # Categories & Products
    path('categories', views.categories, name='categories'),
    path('products', views.products, name='products'),

    # Inventory
    path('inventory/ingredients', views.ingredients, name='ingredients'),
    path('inventory/ingredients/low-stock', views.low_stock_ingredients, name='low_stock_ingredients'),
    path('inventory/purchase', views.inventory_purchase, name='inventory_purchase'),
    path('inventory/adjustment', views.inventory_adjustment, name='inventory_adjustment'),
    path('inventory/movements', views.inventory_movements, name='inventory_movements'),

    # Reports
    path('reports/sales', views.report_sales, name='report_sales'),
    path('reports/sales/export', views.report_sales_export, name='report_sales_export'),
    path('reports/inventory', views.report_inventory, name='report_inventory'),
    path('reports/inventory/export', views.report_inventory_export, name='report_inventory_export'),
    path('reports/day-close', views.report_day_close, name='report_day_close'),

    # Shifts
    path('shifts/current', views.current_shift, name='current_shift'),
    path('shifts/open', views.open_shift, name='open_shift'),
    path('shifts/<int:shift_id>/close', views.close_shift, name='close_shift'),

    # Orders
    path('orders', views.orders, name='orders'),
    path('orders/<int:order_id>', views.order_detail, name='order_detail'),
    path('orders/<int:order_id>/items', views.add_order_item, name='add_order_item'),
    path('orders/<int:order_id>/items/<int:item_id>', views.order_item_detail, name='order_item_detail'),
    path('orders/<int:order_id>/confirm', views.confirm_order, name='confirm_order'),
    path('orders/<int:order_id>/cancel', views.cancel_order, name='cancel_order'),
    path('orders/<int:order_id>/payment', views.add_payment, name='add_payment'),
    path('orders/<int:order_id>/checkout', views.checkout_order, name='checkout_order'),
    path('orders/<int:order_id>/close', views.close_order, name='close_order'),
    path('orders/<int:order_id>/credit', views.credit_checkout, name='credit_checkout'),

    # Credit accounts
    path('credit/accounts', views.credit_accounts, name='credit_accounts'),
    path('credit/accounts/<int:account_id>', views.credit_account_detail, name='credit_account_detail'),
    path('credit/accounts/<int:account_id>/repay', views.credit_repay, name='credit_repay'),
]
