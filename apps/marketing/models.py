from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import TimeStamped
from apps.core.utils import unique_slug


class JournalCategory(TimeStamped):
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, unique=True, blank=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("sort_order", "name")
        verbose_name_plural = "journal categories"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(JournalCategory, self.name, self)
        super().save(*args, **kwargs)


class JournalPost(TimeStamped):
    title = models.CharField(max_length=220)
    slug = models.SlugField(max_length=240, unique=True, blank=True)
    category = models.ForeignKey(
        JournalCategory, on_delete=models.SET_NULL, null=True, blank=True, related_name="posts"
    )
    excerpt = models.TextField(blank=True)
    body = models.TextField(blank=True, help_text="HTML or Markdown")
    hero_image = models.ImageField(upload_to="journal/", blank=True, null=True)
    author = models.CharField(max_length=120, blank=True)
    read_minutes = models.PositiveIntegerField(default=4)
    is_published = models.BooleanField(default=False)
    is_featured = models.BooleanField(default=False)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-published_at", "-created_at")

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(JournalPost, self.title, self)
        super().save(*args, **kwargs)


class NewsletterSubscriber(TimeStamped):
    email = models.EmailField(unique=True)
    is_active = models.BooleanField(default=True)
    source = models.CharField(max_length=64, blank=True, default="footer")

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return self.email


class SiteSettings(TimeStamped):
    """Singleton row (pk=1) holding storefront chrome the admin can edit."""

    announcement_text = models.CharField(
        max_length=255, blank=True, default="Complimentary UK delivery on orders over £50"
    )
    announcement_href = models.CharField(max_length=255, blank=True)
    announcement_active = models.BooleanField(default=True)
    free_shipping_threshold = models.DecimalField(
        max_digits=10, decimal_places=2, default=50
    )
    usp_items = models.JSONField(
        default=list, blank=True, help_text='[{"icon": "truck", "label": "Free UK delivery"}]'
    )
    social_instagram = models.URLField(blank=True)
    social_facebook = models.URLField(blank=True)
    social_pinterest = models.URLField(blank=True)
    footer_links = models.JSONField(
        default=list,
        blank=True,
        help_text='[{"title": "Help", "links": [{"label": "FAQs", "href": "/faqs"}]}]',
    )
    faqs = models.JSONField(
        default=list, blank=True, help_text='[{"question": "...", "answer": "...", "group": "Orders"}]'
    )
    contact_email = models.EmailField(blank=True, default="hello@lavenderhill.example")
    contact_phone = models.CharField(max_length=32, blank=True)
    studio_address = models.TextField(blank=True)
    about_body = models.TextField(blank=True)
    currency = models.CharField(max_length=3, default=settings.DEFAULT_CURRENCY)

    class Meta:
        verbose_name_plural = "site settings"

    def __str__(self):
        return "Site settings"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("The site settings singleton cannot be deleted.")

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class HomeSection(TimeStamped):
    """Ordered merchandising blocks that drive the storefront homepage."""

    class Kind(models.TextChoices):
        HERO = "hero", "Hero"
        CATEGORY_TILES = "category_tiles", "Category tiles"
        COLLECTION_ROW = "collection_row", "Collection product row"
        EDITORIAL = "editorial", "Editorial banner"
        FABRIC_ROW = "fabric_row", "Fabric row"
        JOURNAL = "journal", "Journal preview"
        INSTAGRAM = "instagram", "Instagram grid"
        SUSTAINABILITY = "sustainability", "Sustainability band"

    kind = models.CharField(max_length=32, choices=Kind.choices)
    title = models.CharField(max_length=200, blank=True)
    subtitle = models.CharField(max_length=400, blank=True)
    eyebrow = models.CharField(max_length=120, blank=True)
    cta_label = models.CharField(max_length=80, blank=True)
    cta_href = models.CharField(max_length=255, blank=True)
    image = models.ImageField(upload_to="home/", blank=True, null=True)
    collection = models.ForeignKey(
        "catalog.Collection", on_delete=models.SET_NULL, null=True, blank=True
    )
    payload = models.JSONField(default=dict, blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("sort_order", "id")

    def __str__(self):
        return f"{self.get_kind_display()} — {self.title or '(untitled)'}"


class ContactMessage(TimeStamped):
    name = models.CharField(max_length=120)
    email = models.EmailField()
    subject = models.CharField(max_length=200, blank=True)
    message = models.TextField()
    is_handled = models.BooleanField(default=False)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.name} — {self.subject or 'Enquiry'}"
