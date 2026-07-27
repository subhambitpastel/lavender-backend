from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import models, transaction
from django.utils import timezone

from apps.core.models import TimeStamped
from apps.core.utils import money


class Discount(TimeStamped):
    class Kind(models.TextChoices):
        PERCENT = "percent", "Percentage off"
        FIXED = "fixed", "Fixed amount off"

    code = models.CharField(max_length=40, unique=True)
    description = models.CharField(max_length=255, blank=True)
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.PERCENT)
    value = models.DecimalField(max_digits=10, decimal_places=2)
    min_spend = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    usage_limit = models.PositiveIntegerField(null=True, blank=True)
    used_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return self.code

    def save(self, *args, **kwargs):
        self.code = self.code.strip().upper()
        super().save(*args, **kwargs)

    def is_valid(self, cart_subtotal: Decimal):
        """Return ``(ok, reason)`` for this code against a subtotal."""
        now = timezone.now()
        if not self.is_active:
            return False, "This code is no longer active."
        if self.starts_at and now < self.starts_at:
            return False, "This code isn't active yet."
        if self.ends_at and now > self.ends_at:
            return False, "This code has expired."
        if self.usage_limit is not None and self.used_count >= self.usage_limit:
            return False, "This code has reached its usage limit."
        if self.min_spend and cart_subtotal < self.min_spend:
            return False, f"Spend {self.min_spend} to use this code."
        return True, ""

    def amount_for(self, subtotal: Decimal) -> Decimal:
        if self.kind == self.Kind.PERCENT:
            return money(subtotal * self.value / Decimal("100"))
        return money(min(self.value, subtotal))


class OrderQuerySet(models.QuerySet):
    def paid(self):
        return self.filter(payment_status=Order.PaymentStatus.PAID)


class Order(TimeStamped):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        CONFIRMED = "confirmed", "Confirmed"
        FULFILLMENT = "fulfillment", "Fulfillment"
        SHIPPED = "shipped", "Shipped"
        DELIVERED = "delivered", "Delivered"
        CLOSED = "closed", "Closed"
        CANCELLED = "cancelled", "Cancelled"
        REFUNDED = "refunded", "Refunded"

    # The forward lifecycle a staff member steps an order through, and the button
    # label that advances it FROM each stage. Cancel/refund are off-flow.
    LIFECYCLE = (
        Status.DRAFT,
        Status.CONFIRMED,
        Status.FULFILLMENT,
        Status.SHIPPED,
        Status.DELIVERED,
        Status.CLOSED,
    )
    ADVANCE_LABEL = {
        Status.DRAFT: "Confirm order",
        Status.CONFIRMED: "Start fulfillment",
        Status.FULFILLMENT: "Mark shipped",
        Status.SHIPPED: "Mark delivered",
        Status.DELIVERED: "Close order",
    }

    class PaymentStatus(models.TextChoices):
        UNPAID = "unpaid", "Unpaid"
        PAID = "paid", "Paid"
        REFUNDED = "refunded", "Refunded"

    class ShippingMethod(models.TextChoices):
        STANDARD = "standard", "Standard delivery (3–5 days)"
        EXPRESS = "express", "Express delivery (1–2 days)"

    number = models.CharField(max_length=32, unique=True, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orders",
    )
    email = models.EmailField()
    phone = models.CharField(max_length=32, blank=True)

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    payment_status = models.CharField(
        max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.UNPAID
    )
    payment_ref = models.CharField(max_length=255, blank=True)
    payment_provider = models.CharField(max_length=32, blank=True)

    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))
    discount_total = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))
    shipping_total = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))
    tax_total = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))
    grand_total = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))
    currency = models.CharField(max_length=3, default=settings.DEFAULT_CURRENCY)

    discount_code = models.CharField(max_length=40, blank=True)
    shipping_method = models.CharField(
        max_length=20, choices=ShippingMethod.choices, default=ShippingMethod.STANDARD
    )
    shipping_address = models.JSONField(default=dict, blank=True)
    billing_address = models.JSONField(default=dict, blank=True)
    customer_note = models.TextField(blank=True)
    staff_note = models.TextField(blank=True)
    tracking_number = models.CharField(max_length=120, blank=True)

    placed_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    stock_released = models.BooleanField(
        default=False, help_text="True once cancelled/refunded stock went back."
    )

    objects = OrderQuerySet.as_manager()

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["status", "-created_at"])]

    def __str__(self):
        return self.number

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = self.generate_number()
        # Stamp the delivery time the first time an order is marked delivered, so
        # the storefront can show "Delivered on …" and gate reviews accurately.
        if self.status == self.Status.DELIVERED and self.delivered_at is None:
            self.delivered_at = timezone.now()
        super().save(*args, **kwargs)

    @property
    def is_delivered(self):
        return self.status == self.Status.DELIVERED

    @staticmethod
    def generate_number():
        year = timezone.now().year
        prefix = f"LH-{year}-"
        last = (
            Order.objects.filter(number__startswith=prefix)
            .order_by("-number")
            .values_list("number", flat=True)
            .first()
        )
        sequence = int(last.split("-")[-1]) + 1 if last else 1
        return f"{prefix}{sequence:06d}"

    @property
    def item_count(self):
        return sum(item.quantity for item in self.items.all())

    @property
    def is_cancellable(self):
        # Any pre-delivery lifecycle stage can still be cancelled (and restocked).
        return self.status in {
            self.Status.DRAFT,
            self.Status.CONFIRMED,
            self.Status.FULFILLMENT,
            self.Status.SHIPPED,
        }

    @property
    def return_window_ends(self):
        """When the return window closes — RETURN_WINDOW_DAYS after delivery."""
        reference = self.delivered_at or self.placed_at or self.created_at
        if reference is None:
            return None
        return reference + timedelta(days=settings.RETURN_WINDOW_DAYS)

    @property
    def is_returnable(self):
        """A paid, delivered/closed order still inside its return window, with at
        least one line that hasn't already been fully returned."""
        if self.payment_status != self.PaymentStatus.PAID:
            return False
        if self.status not in {self.Status.DELIVERED, self.Status.CLOSED}:
            return False
        ends = self.return_window_ends
        if ends is not None and timezone.now() > ends:
            return False
        return any(item.returnable_quantity > 0 for item in self.items.all())

    @property
    def next_status(self):
        """The next stage in the forward lifecycle, or None at the end/off-flow."""
        if self.status not in self.LIFECYCLE:
            return None
        index = self.LIFECYCLE.index(self.status)
        return self.LIFECYCLE[index + 1] if index + 1 < len(self.LIFECYCLE) else None

    @property
    def advance_label(self):
        return self.ADVANCE_LABEL.get(self.status)

    def transition_to(self, new_status, actor="", note=""):
        """Move to ``new_status``, recording an audit event. Returns the event."""
        old = self.status
        self.status = new_status
        self.save()  # Order.save() stamps delivered_at on delivery
        return self.status_events.create(
            from_status=old, to_status=new_status, actor=actor, note=note
        )

    @property
    def shipping_name(self):
        addr = self.shipping_address or {}
        return f"{addr.get('first_name', '')} {addr.get('last_name', '')}".strip()

    @transaction.atomic
    def restock(self):
        """Put reserved stock back — used on cancel/refund. Idempotent."""
        if self.stock_released:
            return False
        from apps.catalog.models import ProductVariant

        for item in self.items.select_related("variant"):
            if item.variant_id:
                ProductVariant.objects.filter(pk=item.variant_id).update(
                    stock_quantity=models.F("stock_quantity") + item.quantity
                )
        self.stock_released = True
        self.save(update_fields=["stock_released", "updated_at"])
        return True


class OrderStatusEvent(models.Model):
    """Audit trail of an order's status changes — powers the activity log."""

    order = models.ForeignKey(
        Order, on_delete=models.CASCADE, related_name="status_events"
    )
    from_status = models.CharField(max_length=20, blank=True)
    to_status = models.CharField(max_length=20)
    note = models.TextField(blank=True)
    actor = models.CharField(max_length=254, blank=True, help_text="Who made the change.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.order.number}: {self.from_status or '—'} → {self.to_status}"


class OrderItem(TimeStamped):
    """Line item — every display field is snapshotted at purchase time."""

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    variant = models.ForeignKey(
        "catalog.ProductVariant",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="order_items",
    )
    product_slug = models.SlugField(max_length=220, blank=True)
    product_name = models.CharField(max_length=200)
    colour_name = models.CharField(max_length=80, blank=True)
    size_name = models.CharField(max_length=32, blank=True)
    sku = models.CharField(max_length=64, blank=True)
    image_url = models.CharField(max_length=500, blank=True)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.PositiveIntegerField(default=1)
    line_total = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        ordering = ("id",)

    def __str__(self):
        return f"{self.quantity} × {self.product_name} ({self.sku})"

    @property
    def returned_quantity(self):
        """How many of this line are tied up in a live (non-rejected) return."""
        return sum(
            ri.quantity
            for ri in self.return_items.all()
            if ri.return_request.status != Return.Status.REJECTED
        )

    @property
    def returnable_quantity(self):
        return max(0, self.quantity - self.returned_quantity)


class Return(TimeStamped):
    """A customer's request to send item(s) back. Staff approve (refund + restock)
    or reject; nothing moves until a staff member acts."""

    class Status(models.TextChoices):
        REQUESTED = "requested", "Requested"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    class Reason(models.TextChoices):
        FAULTY = "faulty", "Faulty or damaged"
        WRONG_ITEM = "wrong_item", "Wrong item sent"
        WRONG_SIZE = "wrong_size", "Doesn't fit / wrong size"
        NOT_AS_DESCRIBED = "not_as_described", "Not as described"
        CHANGED_MIND = "changed_mind", "Changed my mind"
        OTHER = "other", "Other"

    number = models.CharField(max_length=32, unique=True, editable=False)
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="returns")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="returns",
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.REQUESTED)
    reason = models.CharField(max_length=20, choices=Reason.choices, default=Reason.OTHER)
    customer_note = models.TextField(blank=True)
    staff_note = models.TextField(blank=True)
    refund_total = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))
    restocked = models.BooleanField(default=False)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["status", "-created_at"])]

    def __str__(self):
        return self.number

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = self.generate_number()
        super().save(*args, **kwargs)

    @staticmethod
    def generate_number():
        year = timezone.now().year
        prefix = f"RET-{year}-"
        last = (
            Return.objects.filter(number__startswith=prefix)
            .order_by("-number")
            .values_list("number", flat=True)
            .first()
        )
        sequence = int(last.split("-")[-1]) + 1 if last else 1
        return f"{prefix}{sequence:06d}"

    @property
    def item_count(self):
        return sum(item.quantity for item in self.items.all())

    def compute_refund_total(self):
        return money(sum(item.line_refund for item in self.items.all()))


class ReturnItem(models.Model):
    return_request = models.ForeignKey(
        Return, on_delete=models.CASCADE, related_name="items"
    )
    order_item = models.ForeignKey(
        OrderItem, on_delete=models.CASCADE, related_name="return_items"
    )
    quantity = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ("id",)

    def __str__(self):
        return f"{self.quantity} × {self.order_item.product_name}"

    @property
    def line_refund(self):
        return self.order_item.unit_price * self.quantity
