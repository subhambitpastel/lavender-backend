import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models

from apps.core.models import TimeStamped
from apps.core.utils import money


class Cart(TimeStamped):
    """A cart belongs to a user, or to a guest identified by ``token``."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="carts",
    )
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    discount = models.ForeignKey(
        "orders.Discount", on_delete=models.SET_NULL, null=True, blank=True
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("-updated_at",)

    def __str__(self):
        owner = self.user.email if self.user_id else f"guest {self.token}"
        return f"Cart<{owner}>"

    @property
    def subtotal(self) -> Decimal:
        return money(sum((item.line_total for item in self.items.all()), Decimal("0")))

    @property
    def item_count(self) -> int:
        return sum(item.quantity for item in self.items.all())

    @property
    def discount_total(self) -> Decimal:
        if not self.discount_id:
            return Decimal("0.00")
        valid, _ = self.discount.is_valid(self.subtotal)
        if not valid:
            return Decimal("0.00")
        return self.discount.amount_for(self.subtotal)

    @property
    def free_shipping_remaining(self) -> Decimal:
        remaining = Decimal(settings.FREE_SHIPPING_THRESHOLD) - self.subtotal
        return money(max(remaining, Decimal("0")))

    def shipping_estimate(self, method="standard") -> Decimal:
        if self.subtotal >= Decimal(settings.FREE_SHIPPING_THRESHOLD):
            return Decimal("0.00")
        if method == "express":
            return money(settings.EXPRESS_SHIPPING_FEE)
        return money(settings.STANDARD_SHIPPING_FEE)

    def total(self, method="standard") -> Decimal:
        return money(
            self.subtotal - self.discount_total + self.shipping_estimate(method)
        )

    def merge_from(self, other: "Cart"):
        """Fold a guest cart into this one, capping quantities at available stock."""
        for item in other.items.select_related("variant"):
            existing = self.items.filter(variant=item.variant).first()
            if existing:
                existing.quantity = min(
                    existing.quantity + item.quantity, item.variant.stock_quantity
                ) or existing.quantity
                existing.save(update_fields=["quantity", "updated_at"])
            else:
                item.cart = self
                item.save(update_fields=["cart", "updated_at"])
        if other.discount_id and not self.discount_id:
            self.discount_id = other.discount_id
            self.save(update_fields=["discount", "updated_at"])
        other.items.all().delete()
        other.delete()
        return self


class CartItem(TimeStamped):
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name="items")
    variant = models.ForeignKey(
        "catalog.ProductVariant", on_delete=models.CASCADE, related_name="cart_items"
    )
    quantity = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ("created_at",)
        unique_together = ("cart", "variant")

    def __str__(self):
        return f"{self.quantity} × {self.variant.sku}"

    @property
    def unit_price(self) -> Decimal:
        return money(self.variant.price)

    @property
    def line_total(self) -> Decimal:
        return money(self.unit_price * self.quantity)

    @property
    def max_quantity(self) -> int:
        return self.variant.stock_quantity
