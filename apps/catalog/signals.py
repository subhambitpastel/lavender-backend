from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import Review


@receiver([post_save, post_delete], sender=Review)
def refresh_product_rating(sender, instance, **kwargs):
    """Keep Product.rating_avg / review_count in step with approved reviews."""
    instance.product.recalculate_rating()
