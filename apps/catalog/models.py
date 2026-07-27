from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Sum
from django.utils import timezone
from imagekit.models import ImageSpecField
from imagekit.processors import ResizeToFill

from apps.core.models import TimeStamped
from apps.core.utils import unique_slug


class Category(TimeStamped):
    """Navigational taxonomy, optionally nested (Clothing › Loungewear)."""

    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, unique=True, blank=True)
    description = models.TextField(blank=True)
    image = models.ImageField(upload_to="categories/", blank=True, null=True)
    parent = models.ForeignKey(
        "self", on_delete=models.CASCADE, null=True, blank=True, related_name="children"
    )
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    show_in_nav = models.BooleanField(default=True)

    class Meta:
        ordering = ("sort_order", "name")
        verbose_name_plural = "categories"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(Category, self.name, self)
        super().save(*args, **kwargs)

    @property
    def product_count(self):
        return self.products.filter(is_active=True).count()


class Collection(TimeStamped):
    """Curated merchandising group: New Arrivals, Sale, Gift Guide, Bestsellers."""

    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, unique=True, blank=True)
    description = models.TextField(blank=True)
    hero_image = models.ImageField(upload_to="collections/", blank=True, null=True)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("sort_order", "name")

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(Collection, self.name, self)
        super().save(*args, **kwargs)


class Fabric(TimeStamped):
    """Shop-by-fabric facet: Cashmere, Linen, Modal, Organic Cotton, Merino."""

    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, unique=True, blank=True)
    description = models.TextField(blank=True)
    image = models.ImageField(upload_to="fabrics/", blank=True, null=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("sort_order", "name")

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(Fabric, self.name, self)
        super().save(*args, **kwargs)


class Size(TimeStamped):
    """Admin-managed, ordered size list (XS…XL, One size)."""

    name = models.CharField(max_length=32, unique=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("sort_order", "name")

    def __str__(self):
        return self.name


class ProductQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)

    def with_cards(self):
        """Prefetch everything a ProductCard serializer touches."""
        return self.select_related("category").prefetch_related(
            "colours__images", "colours__variants", "fabrics", "collections"
        )

    def in_stock(self):
        return self.filter(
            colours__variants__is_active=True, colours__variants__stock_quantity__gt=0
        ).distinct()


class Product(TimeStamped):
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    description = models.TextField(blank=True)
    category = models.ForeignKey(
        Category, on_delete=models.PROTECT, related_name="products"
    )
    fabrics = models.ManyToManyField(Fabric, blank=True, related_name="products")
    collections = models.ManyToManyField(Collection, blank=True, related_name="products")

    base_price = models.DecimalField(max_digits=10, decimal_places=2)
    compare_at_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Original price. Set this to put the product on sale.",
    )
    currency = models.CharField(max_length=3, default=settings.DEFAULT_CURRENCY)

    is_active = models.BooleanField(default=True)
    is_featured = models.BooleanField(default=False)
    is_new_in = models.BooleanField(default=False)
    is_bestseller = models.BooleanField(default=False)

    composition = models.TextField(blank=True)
    care_instructions = models.TextField(blank=True)
    sustainability_note = models.TextField(blank=True)

    rating_avg = models.DecimalField(max_digits=3, decimal_places=2, default=Decimal("0"))
    review_count = models.PositiveIntegerField(default=0)

    meta_title = models.CharField(max_length=255, blank=True)
    meta_description = models.CharField(max_length=500, blank=True)

    sort_order = models.PositiveIntegerField(default=0)

    objects = ProductQuerySet.as_manager()

    class Meta:
        ordering = ("sort_order", "-created_at")
        indexes = [
            models.Index(fields=["is_active", "-created_at"]),
            models.Index(fields=["base_price"]),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(Product, self.name, self)
        super().save(*args, **kwargs)

    # ----------------------------------------------------------- derived data

    @property
    def on_sale(self):
        return bool(self.compare_at_price and self.compare_at_price > self.base_price)

    @property
    def discount_percent(self):
        if not self.on_sale:
            return 0
        return int(
            round((self.compare_at_price - self.base_price) / self.compare_at_price * 100)
        )

    @property
    def total_stock(self):
        return (
            ProductVariant.objects.filter(colour__product=self, is_active=True).aggregate(
                total=Sum("stock_quantity")
            )["total"]
            or 0
        )

    @property
    def in_stock(self):
        return any(
            v.stock_quantity > 0
            for colour in self.colours.all()
            for v in colour.variants.all()
            if v.is_active
        )

    @property
    def badge(self):
        """Single badge shown on the product card, most specific first."""
        if self.on_sale:
            return "Sale"
        if self.is_new_in:
            return "New in"
        if self.is_bestseller:
            return "Bestseller"
        return ""

    @property
    def primary_image(self):
        for colour in self.colours.all():
            image = colour.primary_image
            if image:
                return image
        return None

    def recalculate_rating(self, save=True):
        stats = self.reviews.filter(is_approved=True).aggregate(
            avg=models.Avg("rating"), count=models.Count("id")
        )
        self.rating_avg = Decimal(stats["avg"] or 0).quantize(Decimal("0.01"))
        self.review_count = stats["count"] or 0
        if save:
            Product.objects.filter(pk=self.pk).update(
                rating_avg=self.rating_avg, review_count=self.review_count
            )
        return self.rating_avg


class ProductColour(TimeStamped):
    """A colourway of a product — "colours available"."""

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="colours")
    name = models.CharField(max_length=80)
    swatch_hex = models.CharField(max_length=9, default="#DCD3C6")
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("sort_order", "id")
        unique_together = ("product", "name")

    def __str__(self):
        return f"{self.product.name} — {self.name}"

    @property
    def stock(self):
        """Stock available for this colour = sum of its variants."""
        return sum(v.stock_quantity for v in self.variants.all() if v.is_active)

    @property
    def in_stock(self):
        return self.stock > 0

    @property
    def primary_image(self):
        images = list(self.images.all())
        if not images:
            return None
        for image in images:
            if image.is_primary:
                return image
        return images[0]


class ProductImage(TimeStamped):
    """Images belong to a colour, so the PDP gallery swaps with the swatch."""

    colour = models.ForeignKey(
        ProductColour, on_delete=models.CASCADE, related_name="images"
    )
    image = models.ImageField(upload_to="products/%Y/%m/")
    alt_text = models.CharField(max_length=255, blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_primary = models.BooleanField(default=False)

    card = ImageSpecField(
        source="image", processors=[ResizeToFill(600, 750)], format="JPEG", options={"quality": 85}
    )
    thumb = ImageSpecField(
        source="image", processors=[ResizeToFill(160, 200)], format="JPEG", options={"quality": 80}
    )
    zoom = ImageSpecField(
        source="image", processors=[ResizeToFill(1200, 1500)], format="JPEG", options={"quality": 88}
    )

    class Meta:
        ordering = ("-is_primary", "sort_order", "id")

    def __str__(self):
        return f"{self.colour} image {self.pk}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.is_primary:
            ProductImage.objects.filter(colour=self.colour).exclude(pk=self.pk).update(
                is_primary=False
            )


class ProductVariant(TimeStamped):
    """SKU = colour × size. Holds the stock left."""

    colour = models.ForeignKey(
        ProductColour, on_delete=models.CASCADE, related_name="variants"
    )
    size = models.ForeignKey(Size, on_delete=models.PROTECT, related_name="variants")
    sku = models.CharField(max_length=64, unique=True)
    stock_quantity = models.PositiveIntegerField(default=0)
    price_override = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("size__sort_order", "id")
        unique_together = ("colour", "size")

    def __str__(self):
        return self.sku

    @property
    def in_stock(self):
        return self.is_active and self.stock_quantity > 0

    @property
    def price(self):
        return self.price_override or self.colour.product.base_price

    @property
    def product(self):
        return self.colour.product

    @property
    def is_low_stock(self):
        return 0 < self.stock_quantity <= settings.LOW_STOCK_THRESHOLD

    def build_sku(self):
        product = self.colour.product
        parts = [
            "LH",
            product.slug[:12].upper().replace("-", ""),
            self.colour.name[:6].upper().replace(" ", ""),
            self.size.name.upper().replace(" ", ""),
        ]
        return "-".join(parts)

    def save(self, *args, **kwargs):
        if not self.sku:
            candidate = self.build_sku()
            sku = candidate
            counter = 2
            while ProductVariant.objects.filter(sku=sku).exclude(pk=self.pk).exists():
                sku = f"{candidate}-{counter}"
                counter += 1
            self.sku = sku
        super().save(*args, **kwargs)


class Review(TimeStamped):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="reviews")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviews",
    )
    class Status(models.TextChoices):
        PENDING = "pending", "Pending approval"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Changes requested"

    author_name = models.CharField(max_length=120)
    author_location = models.CharField(max_length=120, blank=True)
    rating = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    title = models.CharField(max_length=200, blank=True)
    body = models.TextField()
    is_verified = models.BooleanField(default=False)
    # Moderation workflow. `status` drives it; `is_approved` stays as the single
    # "is this published?" flag the rating aggregate and PDP listing read, and is
    # always kept == (status == APPROVED).
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    is_approved = models.BooleanField(default=False)
    # The most recent reason a staff member gave when requesting changes; shown
    # to the shopper so they know what to fix. Cleared once re-approved.
    rejection_reason = models.TextField(blank=True)

    # A shopper may edit / resubmit their review only within this window of first
    # posting it; after that it's locked (approved or not).
    EDIT_WINDOW = timedelta(hours=24)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.product.name} — {self.rating}★ by {self.author_name}"

    @property
    def edit_deadline(self):
        """When the shopper's 24-hour window to make changes runs out."""
        return self.created_at + self.EDIT_WINDOW

    @property
    def is_editable(self):
        return timezone.now() < self.edit_deadline

    def matches(self, *, rating, title, body):
        """True when a resubmission is identical to what's already stored — used
        to reject a no-op edit so the shopper must actually change something."""
        return (
            self.rating == rating
            and (self.title or "") == (title or "")
            and (self.body or "") == (body or "")
        )

    def add_event(self, action, *, actor=None, reason="", snapshot=False):
        """Append a moderation-history entry. `snapshot` captures the review's
        current words, so a resubmission's history shows what was written then."""
        return self.events.create(
            action=action,
            actor=actor,
            reason=reason or "",
            rating=self.rating if snapshot else None,
            title=self.title if snapshot else "",
            body=self.body if snapshot else "",
        )


class ReviewEvent(TimeStamped):
    """Audit trail for a review's moderation — one row per submit/approve/reject,
    kept forever and shown to both the shopper and staff."""

    class Action(models.TextChoices):
        SUBMITTED = "submitted", "Submitted"
        RESUBMITTED = "resubmitted", "Resubmitted"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Changes requested"

    review = models.ForeignKey(Review, on_delete=models.CASCADE, related_name="events")
    action = models.CharField(max_length=12, choices=Action.choices)
    reason = models.TextField(blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    # A snapshot of the words as submitted, so history can show each revision.
    rating = models.PositiveSmallIntegerField(null=True, blank=True)
    title = models.CharField(max_length=200, blank=True)
    body = models.TextField(blank=True)

    class Meta:
        ordering = ("created_at",)

    def __str__(self):
        return f"{self.get_action_display()} · review #{self.review_id}"
