from django.conf import settings
from django.db import models

from apps.core.models import TimeStamped


class WishlistItem(TimeStamped):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="wishlist"
    )
    product = models.ForeignKey(
        "catalog.Product", on_delete=models.CASCADE, related_name="wishlisted_by"
    )

    class Meta:
        ordering = ("-created_at",)
        unique_together = ("user", "product")

    def __str__(self):
        return f"{self.user.email} ♥ {self.product.name}"
