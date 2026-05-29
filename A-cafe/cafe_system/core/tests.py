import json
from decimal import Decimal

from django.test import TestCase

from .models import (
    Category,
    Ingredient,
    InventoryMovement,
    LowStockAlert,
    Order,
    Product,
    ProductStockMovement,
    Recipe,
)


class OrderInventoryPaymentFlowTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name='Coffee')
        self.product = Product.objects.create(
            name='Latte',
            sku='LATTE-001',
            category=self.category,
            price=Decimal('200.00'),
            tax_percent=Decimal('0.00'),
            product_type=Product.ProductTypeChoices.RECIPE_BASED,
            is_active=True,
        )
        self.ingredient = Ingredient.objects.create(
            name='Milk',
            unit=Ingredient.UnitChoices.ML,
            current_qty=Decimal('1000.000'),
            min_qty_alert=Decimal('200.000'),
        )
        Recipe.objects.create(
            product=self.product,
            ingredient=self.ingredient,
            qty_per_item=Decimal('100.000'),
        )

    def _create_order_with_item(self, qty=2, product=None):
        product = product or self.product
        response = self.client.post(
            '/api/orders',
            data=json.dumps(
                {
                    'order_type': 'DINE_IN',
                    'table_no': 'T1',
                    'auto_confirm': False,
                    'items': [{'product_id': product.id, 'qty': qty}],
                }
            ),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 201)
        return response.json()['data']

    def _checkout_order(self, order_id, total):
        return self.client.post(
            f'/api/orders/{order_id}/checkout',
            data=json.dumps({'payments': [{'method': 'CASH', 'amount': str(total)}]}),
            content_type='application/json',
        )

    def test_auto_confirm_does_not_deduct_stock(self):
        response = self.client.post(
            '/api/orders',
            data=json.dumps(
                {
                    'order_type': 'DINE_IN',
                    'table_no': 'T3',
                    'auto_confirm': True,
                    'items': [{'product_id': self.product.id, 'qty': 2}],
                }
            ),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()['data']
        self.assertEqual(payload['status'], Order.StatusChoices.CONFIRMED)

        self.ingredient.refresh_from_db()
        self.assertEqual(self.ingredient.current_qty, Decimal('1000.000'))
        self.assertFalse(InventoryMovement.objects.filter(movement_type='CONSUME').exists())

    def test_checkout_deducts_recipe_stock_once(self):
        order_payload = self._create_order_with_item(qty=2)
        order_id = order_payload['id']
        order = Order.objects.get(pk=order_id)

        response = self._checkout_order(order_id, order.grand_total)
        self.assertEqual(response.status_code, 200)

        self.ingredient.refresh_from_db()
        self.assertEqual(self.ingredient.current_qty, Decimal('800.000'))
        order.refresh_from_db()
        self.assertTrue(order.inventory_deducted)
        self.assertEqual(
            InventoryMovement.objects.filter(
                movement_type=InventoryMovement.MovementTypeChoices.CONSUME,
                deduction_source='sale',
            ).count(),
            1,
        )

        # Second checkout attempt should not double-deduct
        dup = self._checkout_order(order_id, order.grand_total)
        self.assertEqual(dup.status_code, 400)
        self.ingredient.refresh_from_db()
        self.assertEqual(self.ingredient.current_qty, Decimal('800.000'))

    def test_confirm_fails_with_insufficient_stock(self):
        order_payload = self._create_order_with_item(qty=2)
        order_id = order_payload['id']

        self.ingredient.current_qty = Decimal('50.000')
        self.ingredient.save(update_fields=['current_qty'])

        response = self.client.post(f'/api/orders/{order_id}/confirm')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['error_code'], 'INSUFFICIENT_STOCK')

        order = Order.objects.get(pk=order_id)
        self.assertEqual(order.status, Order.StatusChoices.OPEN)
        self.assertFalse(order.inventory_deducted)

    def test_cancel_order_restores_stock_after_checkout(self):
        order_payload = self._create_order_with_item(qty=3)
        order_id = order_payload['id']
        order = Order.objects.get(pk=order_id)

        checkout_response = self._checkout_order(order_id, order.grand_total)
        self.assertEqual(checkout_response.status_code, 200)
        self.ingredient.refresh_from_db()
        self.assertEqual(self.ingredient.current_qty, Decimal('700.000'))

        cancel_response = self.client.post(f'/api/orders/{order_id}/cancel')
        self.assertEqual(cancel_response.status_code, 400)

    def test_duplicate_confirm_is_blocked(self):
        order_payload = self._create_order_with_item(qty=1)
        order_id = order_payload['id']

        first = self.client.post(f'/api/orders/{order_id}/confirm')
        self.assertEqual(first.status_code, 200)

        second = self.client.post(f'/api/orders/{order_id}/confirm')
        self.assertEqual(second.status_code, 400)
        self.assertEqual(second.json()['error_code'], 'INVALID_STATE')

    def test_payment_cannot_exceed_due_and_updates_status(self):
        order_payload = self._create_order_with_item(qty=2)
        order_id = order_payload['id']

        order = Order.objects.get(pk=order_id)
        self.assertEqual(order.grand_total, Decimal('400.00'))

        overpay = self.client.post(
            f'/api/orders/{order_id}/payment',
            data=json.dumps({'method': 'CASH', 'amount': '401.00'}),
            content_type='application/json',
        )
        self.assertEqual(overpay.status_code, 400)
        self.assertEqual(overpay.json()['error_code'], 'OVERPAYMENT')

        partial = self.client.post(
            f'/api/orders/{order_id}/payment',
            data=json.dumps({'method': 'CASH', 'amount': '150.00'}),
            content_type='application/json',
        )
        self.assertEqual(partial.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.payment_status, Order.PaymentStatusChoices.PARTIAL)
        self.assertFalse(order.inventory_deducted)

        full = self.client.post(
            f'/api/orders/{order_id}/payment',
            data=json.dumps({'method': 'CASH', 'amount': '250.00'}),
            content_type='application/json',
        )
        self.assertEqual(full.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.payment_status, Order.PaymentStatusChoices.PAID)
        self.assertEqual(order.status, Order.StatusChoices.PAID)
        self.assertTrue(order.inventory_deducted)
        self.ingredient.refresh_from_db()
        self.assertEqual(self.ingredient.current_qty, Decimal('800.000'))

    def test_sales_report_endpoint_returns_summary(self):
        self._create_order_with_item(qty=1)
        response = self.client.get('/api/reports/sales')
        self.assertEqual(response.status_code, 200)
        payload = response.json()['data']
        self.assertIn('summary', payload)
        self.assertIn('order_count', payload['summary'])

    def test_inventory_report_endpoint_returns_sections(self):
        response = self.client.get('/api/reports/inventory')
        self.assertEqual(response.status_code, 200)
        payload = response.json()['data']
        self.assertIn('low_stock', payload)
        self.assertIn('movement_summary', payload)

    def test_shift_open_and_close_flow(self):
        open_response = self.client.post(
            '/api/shifts/open',
            data=json.dumps({'opening_cash': '100.00'}),
            content_type='application/json',
        )
        self.assertEqual(open_response.status_code, 201)
        shift_id = open_response.json()['data']['id']

        current_response = self.client.get('/api/shifts/current')
        self.assertEqual(current_response.status_code, 200)
        self.assertEqual(current_response.json()['data']['id'], shift_id)

        close_response = self.client.post(
            f'/api/shifts/{shift_id}/close',
            data=json.dumps({'closing_cash_actual': '120.00'}),
            content_type='application/json',
        )
        self.assertEqual(close_response.status_code, 200)
        self.assertEqual(close_response.json()['data']['status'], 'CLOSED')


class DirectSaleInventoryTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name='Beverages')
        self.beer = Product.objects.create(
            name='Beer Bottle',
            category=self.category,
            price=Decimal('350.00'),
            product_type=Product.ProductTypeChoices.DIRECT_SALE,
            current_qty=Decimal('50.000'),
            min_qty_alert=Decimal('10.000'),
            is_active=True,
        )

    def test_checkout_deducts_direct_sale_product_stock(self):
        response = self.client.post(
            '/api/orders',
            data=json.dumps(
                {
                    'order_type': 'TAKEAWAY',
                    'items': [{'product_id': self.beer.id, 'qty': 2}],
                }
            ),
            content_type='application/json',
        )
        order_id = response.json()['data']['id']
        order = Order.objects.get(pk=order_id)

        checkout = self.client.post(
            f'/api/orders/{order_id}/checkout',
            data=json.dumps({'payments': [{'method': 'CASH', 'amount': str(order.grand_total)}]}),
            content_type='application/json',
        )
        self.assertEqual(checkout.status_code, 200)

        self.beer.refresh_from_db()
        self.assertEqual(self.beer.current_qty, Decimal('48.000'))
        self.assertEqual(
            ProductStockMovement.objects.filter(
                product=self.beer,
                movement_type=ProductStockMovement.MovementTypeChoices.SALE,
                deduction_source='sale',
            ).count(),
            1,
        )

    def test_low_stock_alert_after_direct_sale(self):
        self.beer.current_qty = Decimal('11.000')
        self.beer.save(update_fields=['current_qty'])

        response = self.client.post(
            '/api/orders',
            data=json.dumps({'items': [{'product_id': self.beer.id, 'qty': 2}]}),
            content_type='application/json',
        )
        order_id = response.json()['data']['id']
        order = Order.objects.get(pk=order_id)
        self.client.post(
            f'/api/orders/{order_id}/checkout',
            data=json.dumps({'payments': [{'method': 'CASH', 'amount': str(order.grand_total)}]}),
            content_type='application/json',
        )

        self.assertTrue(
            LowStockAlert.objects.filter(
                item_type=LowStockAlert.ItemTypeChoices.PRODUCT,
                product=self.beer,
                is_resolved=False,
            ).exists()
        )

    def test_manual_adjust_direct_sale_stock(self):
        response = self.client.post(
            '/api/inventory/direct-sale-products/adjust-stock',
            data=json.dumps(
                {
                    'product_id': self.beer.id,
                    'qty_change': '-5',
                    'note': 'Count correction',
                }
            ),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        self.beer.refresh_from_db()
        self.assertEqual(self.beer.current_qty, Decimal('45.000'))
        self.assertEqual(
            ProductStockMovement.objects.filter(
                product=self.beer,
                movement_type=ProductStockMovement.MovementTypeChoices.ADJUST,
                deduction_source='manual',
            ).count(),
            1,
        )


class RecipeBasedMultiIngredientTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name='Food')
        self.burger = Product.objects.create(
            name='Burger',
            category=self.category,
            price=Decimal('450.00'),
            product_type=Product.ProductTypeChoices.RECIPE_BASED,
            is_active=True,
        )
        self.bun = Ingredient.objects.create(name='Bun', unit='pcs', current_qty=Decimal('20'))
        self.patty = Ingredient.objects.create(name='Patty', unit='pcs', current_qty=Decimal('20'))
        self.mayo = Ingredient.objects.create(name='Mayo', unit='g', current_qty=Decimal('500'))
        Recipe.objects.create(product=self.burger, ingredient=self.bun, qty_per_item=Decimal('1'))
        Recipe.objects.create(product=self.burger, ingredient=self.patty, qty_per_item=Decimal('1'))
        Recipe.objects.create(product=self.burger, ingredient=self.mayo, qty_per_item=Decimal('20'))

    def test_selling_two_burgers_deducts_all_ingredients(self):
        response = self.client.post(
            '/api/orders',
            data=json.dumps({'items': [{'product_id': self.burger.id, 'qty': 2}]}),
            content_type='application/json',
        )
        order_id = response.json()['data']['id']
        order = Order.objects.get(pk=order_id)
        self.client.post(
            f'/api/orders/{order_id}/checkout',
            data=json.dumps({'payments': [{'method': 'CASH', 'amount': str(order.grand_total)}]}),
            content_type='application/json',
        )

        self.bun.refresh_from_db()
        self.patty.refresh_from_db()
        self.mayo.refresh_from_db()
        self.assertEqual(self.bun.current_qty, Decimal('18'))
        self.assertEqual(self.patty.current_qty, Decimal('18'))
        self.assertEqual(self.mayo.current_qty, Decimal('460'))
