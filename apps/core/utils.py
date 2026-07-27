from decimal import Decimal

from django.utils.text import slugify


def unique_slug(model, value, instance=None, field="slug", max_length=255):
    """Return a slug for ``value`` unique across ``model``."""
    base = slugify(value)[:max_length] or "item"
    slug = base
    counter = 2
    queryset = model._default_manager.all()
    if instance is not None and instance.pk:
        queryset = queryset.exclude(pk=instance.pk)
    while queryset.filter(**{field: slug}).exists():
        suffix = f"-{counter}"
        slug = f"{base[: max_length - len(suffix)]}{suffix}"
        counter += 1
    return slug


def money(value) -> Decimal:
    """Quantise any numeric to 2dp for money maths."""
    return Decimal(value or 0).quantize(Decimal("0.01"))
