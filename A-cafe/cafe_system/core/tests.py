import json
from decimal import Decimal

from django.test import TestCase

from .models import Category, Ingredient, InventoryMovement, Order, Product, Recipe


class OrderInventoryPaymentFlowTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Coffee")
        self.product = Product.objects.create(
            name="Latte",
            sku="LATTE-001",
            category=self.category,
            price=Decimal("200.00"),
            tax_percent=Decimal("0.00"),
            is_active=True,
        )
        self.ingredient = Ingredient.objects.create(
            name="Milk",
            unit=Ingredient.UnitChoices.ML,
            current_qty=Decimal("1000.000"),
            min_qty_alert=Decimal("200.000"),
        )
        Recipe.objects.create(
            product=self.product,
            ingredient=self.ingredient,
            qty_per_item=Decimal("100.000"),
        )

    def _create_order_with_item(self, qty=2):
        response = self.client.post(
            "/api/orders",
            data=json.dumps(
                {
                    "order_type": "DINE_IN",
                    "table_no": "T1",
                    "auto_confirm": False,
                    "items": [{"product_id": self.product.id, "qty": qty}],
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        return response.json()["data"]

    def test_auto_confirm_order_deducts_stock(self):
        response = self.client.post(
            "/api/orders",
            data=json.dumps(
                {
                    "order_type": "DINE_IN",
                    "table_no": "T3",
                    "auto_confirm": True,
                    "items": [{"product_id": self.product.id, "qty": 2}],
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()["data"]
        self.assertEqual(payload["status"], Order.StatusChoices.CONFIRMED)

        self.ingredient.refresh_from_db()
        self.assertEqual(self.ingredient.current_qty, Decimal("800.000"))
        self.assertEqual(
            InventoryMovement.objects.filter(
                movement_type=InventoryMovement.MovementTypeChoices.CONSUME
            ).count(),
            1,
        )

    def test_confirm_fails_with_insufficient_stock(self):
        order_payload = self._create_order_with_item(qty=2)
        order_id = order_payload["id"]

        self.ingredient.current_qty = Decimal("50.000")
        self.ingredient.save(update_fields=["current_qty"])

        response = self.client.post(f"/api/orders/{order_id}/confirm")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error_code"], "INSUFFICIENT_STOCK")

        order = Order.objects.get(pk=order_id)
        self.assertEqual(order.status, Order.StatusChoices.OPEN)
        self.assertFalse(
            InventoryMovement.objects.filter(
                movement_type=InventoryMovement.MovementTypeChoices.CONSUME,
                reference_id=str(order_id),
            ).exists()
        )

    def test_cancel_order_restores_stock_after_confirm(self):
        order_payload = self._create_order_with_item(qty=3)
        order_id = order_payload["id"]

        confirm_response = self.client.post(f"/api/orders/{order_id}/confirm")
        self.assertEqual(confirm_response.status_code, 200)
        self.ingredient.refresh_from_db()
        self.assertEqual(self.ingredient.current_qty, Decimal("700.000"))

        cancel_response = self.client.post(f"/api/orders/{order_id}/cancel")
        self.assertEqual(cancel_response.status_code, 200)
        self.ingredient.refresh_from_db()
        self.assertEqual(self.ingredient.current_qty, Decimal("1000.000"))
        self.assertTrue(
            InventoryMovement.objects.filter(
                movement_type=InventoryMovement.MovementTypeChoices.RETURN,
                reference_id=str(order_id),
            ).exists()
        )

    def test_duplicate_confirm_is_blocked(self):
        order_payload = self._create_order_with_item(qty=1)
        order_id = order_payload["id"]

        first = self.client.post(f"/api/orders/{order_id}/confirm")
        self.assertEqual(first.status_code, 200)

        second = self.client.post(f"/api/orders/{order_id}/confirm")
        self.assertEqual(second.status_code, 400)
        self.assertEqual(second.json()["error_code"], "INVALID_STATE")

    def test_payment_cannot_exceed_due_and_updates_status(self):
        order_payload = self._create_order_with_item(qty=2)
        order_id = order_payload["id"]

        order = Order.objects.get(pk=order_id)
        self.assertEqual(order.grand_total, Decimal("400.00"))

        overpay = self.client.post(
            f"/api/orders/{order_id}/payment",
            data=json.dumps({"method": "CASH", "amount": "401.00"}),
            content_type="application/json",
        )
        self.assertEqual(overpay.status_code, 400)
        self.assertEqual(overpay.json()["error_code"], "OVERPAYMENT")

        partial = self.client.post(
            f"/api/orders/{order_id}/payment",
            data=json.dumps({"method": "CASH", "amount": "150.00"}),
            content_type="application/json",
        )
        self.assertEqual(partial.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.payment_status, Order.PaymentStatusChoices.PARTIAL)

        full = self.client.post(
            f"/api/orders/{order_id}/payment",
            data=json.dumps({"method": "CARD", "amount": "250.00"}),
            content_type="application/json",
        )
        self.assertEqual(full.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.payment_status, Order.PaymentStatusChoices.PAID)
        self.assertEqual(order.status, Order.StatusChoices.PAID)

    def test_sales_report_endpoint_returns_summary(self):
        self._create_order_with_item(qty=1)
        response = self.client.get("/api/reports/sales")
        self.assertEqual(response.status_code, 200)
        payload = response.json()["data"]
        self.assertIn("summary", payload)
        self.assertIn("order_count", payload["summary"])

    def test_inventory_report_endpoint_returns_sections(self):
        response = self.client.get("/api/reports/inventory")
        self.assertEqual(response.status_code, 200)
        payload = response.json()["data"]
        self.assertIn("low_stock", payload)
        self.assertIn("movement_summary", payload)

    def test_shift_open_and_close_flow(self):
        open_response = self.client.post(
            "/api/shifts/open",
            data=json.dumps({"opening_cash": "100.00"}),
            content_type="application/json",
        )
        self.assertEqual(open_response.status_code, 201)
        shift_id = open_response.json()["data"]["id"]

        current_response = self.client.get("/api/shifts/current")
        self.assertEqual(current_response.status_code, 200)
        self.assertEqual(current_response.json()["data"]["id"], shift_id)

        close_response = self.client.post(
            f"/api/shifts/{shift_id}/close",
            data=json.dumps({"closing_cash_actual": "120.00"}),
            content_type="application/json",
        )
        self.assertEqual(close_response.status_code, 200)
        self.assertEqual(close_response.json()["data"]["status"], "CLOSED")
