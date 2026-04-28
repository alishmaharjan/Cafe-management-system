from django.db import models
from django.db.models import F
from django.utils import timezone


class BaseTimeModel(models.Model):
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        abstract = True


class Category(BaseTimeModel):
    name = models.CharField(max_length=100, unique=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Product(BaseTimeModel):
    name = models.CharField(max_length=150)
    sku = models.CharField(max_length=50, unique=True, null=True, blank=True)
    category = models.ForeignKey(
        Category, on_delete=models.SET_NULL, null=True, related_name="products"
    )
    price = models.DecimalField(max_digits=10, decimal_places=2)
    tax_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(price__gte=0), name="product_price_gte_zero"
            ),
            models.CheckConstraint(
                condition=models.Q(tax_percent__gte=0), name="product_tax_gte_zero"
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.sku})"


class Ingredient(BaseTimeModel):
    class UnitChoices(models.TextChoices):
        GRAM = "g", "Gram"
        ML = "ml", "Milliliter"
        PIECE = "pcs", "Piece"
        KG = "kg", "Kilogram"
        LITER = "l", "Liter"

    name = models.CharField(max_length=120, unique=True)
    unit = models.CharField(max_length=10, choices=UnitChoices.choices)
    current_qty = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    min_qty_alert = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(current_qty__gte=0),
                name="ingredient_current_qty_gte_zero",
            ),
            models.CheckConstraint(
                condition=models.Q(min_qty_alert__gte=0), name="ingredient_min_qty_gte_zero"
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.current_qty}{self.unit})"


class Recipe(BaseTimeModel):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="recipes")
    ingredient = models.ForeignKey(
        Ingredient, on_delete=models.CASCADE, related_name="recipes"
    )
    qty_per_item = models.DecimalField(max_digits=12, decimal_places=3)

    class Meta:
        ordering = ["product__name", "ingredient__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["product", "ingredient"],
                name="unique_recipe_product_ingredient",
            ),
            models.CheckConstraint(
                condition=models.Q(qty_per_item__gt=0), name="recipe_qty_per_item_gt_zero"
            ),
        ]

    def __str__(self):
        return f"{self.product.name} -> {self.ingredient.name}: {self.qty_per_item}"


class Order(BaseTimeModel):
    class OrderTypeChoices(models.TextChoices):
        DINE_IN = "DINE_IN", "Dine In"
        TAKEAWAY = "TAKEAWAY", "Takeaway"

    class StatusChoices(models.TextChoices):
        OPEN = "OPEN", "Open"
        CONFIRMED = "CONFIRMED", "Confirmed"
        PREPARING = "PREPARING", "Preparing"
        SERVED = "SERVED", "Served"
        PAID = "PAID", "Paid"
        CANCELLED = "CANCELLED", "Cancelled"

    class PaymentStatusChoices(models.TextChoices):
        UNPAID = "UNPAID", "Unpaid"
        PARTIAL = "PARTIAL", "Partial"
        PAID = "PAID", "Paid"
        REFUNDED = "REFUNDED", "Refunded"

    order_no = models.CharField(max_length=30, unique=True, null=True, blank=True)
    order_type = models.CharField(max_length=20, choices=OrderTypeChoices.choices)
    table_no = models.CharField(max_length=20, blank=True, null=True)
    status = models.CharField(
        max_length=20, choices=StatusChoices.choices, default=StatusChoices.OPEN
    )
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    grand_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    payment_status = models.CharField(
        max_length=20,
        choices=PaymentStatusChoices.choices,
        default=PaymentStatusChoices.UNPAID,
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(subtotal__gte=0), name="order_subtotal_gte_zero"
            ),
            models.CheckConstraint(
                condition=models.Q(tax_amount__gte=0), name="order_tax_amount_gte_zero"
            ),
            models.CheckConstraint(
                condition=models.Q(discount_amount__gte=0),
                name="order_discount_amount_gte_zero",
            ),
            models.CheckConstraint(
                condition=models.Q(grand_total__gte=0), name="order_grand_total_gte_zero"
            ),
        ]

    def __str__(self):
        return self.order_no


class OrderItem(BaseTimeModel):
    class ItemStatusChoices(models.TextChoices):
        OPEN = "OPEN", "Open"
        PREPARING = "PREPARING", "Preparing"
        SERVED = "SERVED", "Served"
        CANCELLED = "CANCELLED", "Cancelled"

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="order_items")
    qty = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    line_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    item_status = models.CharField(
        max_length=20, choices=ItemStatusChoices.choices, default=ItemStatusChoices.OPEN
    )

    class Meta:
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(unit_price__gte=0),
                name="order_item_unit_price_gte_zero",
            ),
            models.CheckConstraint(
                condition=models.Q(line_total__gte=0),
                name="order_item_line_total_gte_zero",
            ),
        ]

    def save(self, *args, **kwargs):
        self.line_total = self.qty * self.unit_price
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.order.order_no} - {self.product.name} x {self.qty}"


class InventoryMovement(models.Model):
    class MovementTypeChoices(models.TextChoices):
        PURCHASE = "PURCHASE", "Purchase"
        CONSUME = "CONSUME", "Consume"
        ADJUST = "ADJUST", "Adjust"
        WASTE = "WASTE", "Waste"
        RETURN = "RETURN", "Return"

    class ReferenceTypeChoices(models.TextChoices):
        ORDER = "ORDER", "Order"
        PURCHASE = "PURCHASE", "Purchase"
        MANUAL = "MANUAL", "Manual"

    ingredient = models.ForeignKey(
        Ingredient, on_delete=models.PROTECT, related_name="movements"
    )
    movement_type = models.CharField(max_length=20, choices=MovementTypeChoices.choices)
    qty_change = models.DecimalField(max_digits=12, decimal_places=3)
    reference_type = models.CharField(
        max_length=20, choices=ReferenceTypeChoices.choices, blank=True
    )
    reference_id = models.CharField(max_length=50, blank=True)
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["ingredient", "created_at"]),
        ]

    def save(self, *args, **kwargs):
        is_create = self._state.adding
        super().save(*args, **kwargs)
        if is_create:
            Ingredient.objects.filter(pk=self.ingredient_id).update(
                current_qty=F("current_qty") + self.qty_change
            )

    def __str__(self):
        return f"{self.ingredient.name} {self.movement_type} {self.qty_change}"


class StockReservation(BaseTimeModel):
    class ReservationStatusChoices(models.TextChoices):
        HELD = "HELD", "Held"
        CONSUMED = "CONSUMED", "Consumed"
        RELEASED = "RELEASED", "Released"

    order = models.ForeignKey(
        Order, on_delete=models.CASCADE, related_name="stock_reservations"
    )
    ingredient = models.ForeignKey(
        Ingredient, on_delete=models.PROTECT, related_name="stock_reservations"
    )
    reserved_qty = models.DecimalField(max_digits=12, decimal_places=3)
    status = models.CharField(
        max_length=20,
        choices=ReservationStatusChoices.choices,
        default=ReservationStatusChoices.HELD,
    )

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(reserved_qty__gt=0),
                name="stock_reservation_reserved_qty_gt_zero",
            ),
        ]

    def __str__(self):
        return f"{self.order.order_no} - {self.ingredient.name}: {self.reserved_qty}"


class Payment(BaseTimeModel):
    class MethodChoices(models.TextChoices):
        CASH = "CASH", "Cash"
        CARD = "CARD", "Card"
        QR = "QR", "QR"

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="payments")
    method = models.CharField(max_length=20, choices=MethodChoices.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    txn_ref = models.CharField(max_length=100, blank=True)
    paid_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-paid_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0), name="payment_amount_gt_zero"
            ),
        ]

    def __str__(self):
        return f"{self.order.order_no} - {self.method} {self.amount}"


class Shift(BaseTimeModel):
    class ShiftStatusChoices(models.TextChoices):
        OPEN = "OPEN", "Open"
        CLOSED = "CLOSED", "Closed"

    opened_at = models.DateTimeField(default=timezone.now)
    closed_at = models.DateTimeField(null=True, blank=True)
    staff_name = models.CharField(max_length=120, blank=True)
    counter_name = models.CharField(max_length=120, blank=True)
    opening_cash = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    closing_cash_expected = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    closing_cash_actual = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = models.CharField(
        max_length=20, choices=ShiftStatusChoices.choices, default=ShiftStatusChoices.OPEN
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-opened_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(opening_cash__gte=0), name="shift_opening_cash_gte_zero"
            ),
            models.CheckConstraint(
                condition=models.Q(closing_cash_expected__gte=0),
                name="shift_closing_cash_expected_gte_zero",
            ),
            models.CheckConstraint(
                condition=models.Q(closing_cash_actual__gte=0),
                name="shift_closing_cash_actual_gte_zero",
            ),
        ]

    def __str__(self):
        return f"Shift {self.id} - {self.status}"


class AuditLog(models.Model):
    class EventTypeChoices(models.TextChoices):
        ORDER = "ORDER", "Order"
        PAYMENT = "PAYMENT", "Payment"
        INVENTORY = "INVENTORY", "Inventory"
        SHIFT = "SHIFT", "Shift"
        REPORT = "REPORT", "Report"

    event_type = models.CharField(max_length=20, choices=EventTypeChoices.choices)
    action = models.CharField(max_length=80)
    message = models.CharField(max_length=255)
    reference_id = models.CharField(max_length=80, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["event_type", "created_at"]),
            models.Index(fields=["reference_id", "created_at"]),
        ]

    def __str__(self):
        return f"{self.event_type} {self.action} {self.reference_id}"