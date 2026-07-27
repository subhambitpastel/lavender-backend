from rest_framework import serializers

from apps.catalog.serializers import ImageURLMixin, ProductCardSerializer

from .models import (
    ContactMessage,
    HomeSection,
    JournalCategory,
    JournalPost,
    NewsletterSubscriber,
    SiteSettings,
)


class JournalCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = JournalCategory
        fields = ("id", "name", "slug")


class JournalPostListSerializer(ImageURLMixin, serializers.ModelSerializer):
    category = JournalCategorySerializer(read_only=True)
    hero_image = serializers.SerializerMethodField()

    class Meta:
        model = JournalPost
        fields = (
            "id",
            "title",
            "slug",
            "category",
            "excerpt",
            "hero_image",
            "author",
            "read_minutes",
            "is_featured",
            "published_at",
        )

    def get_hero_image(self, obj):
        return self._file_url(obj.hero_image)


class JournalPostDetailSerializer(JournalPostListSerializer):
    related = serializers.SerializerMethodField()

    class Meta(JournalPostListSerializer.Meta):
        fields = JournalPostListSerializer.Meta.fields + ("body", "related")

    def get_related(self, obj):
        queryset = JournalPost.objects.filter(is_published=True).exclude(pk=obj.pk)
        if obj.category_id:
            queryset = queryset.filter(category_id=obj.category_id)
        return JournalPostListSerializer(queryset[:3], many=True, context=self.context).data


class SiteSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = SiteSettings
        fields = (
            "announcement_text",
            "announcement_href",
            "announcement_active",
            "free_shipping_threshold",
            "usp_items",
            "social_instagram",
            "social_facebook",
            "social_pinterest",
            "footer_links",
            "faqs",
            "contact_email",
            "contact_phone",
            "studio_address",
            "about_body",
            "currency",
        )


class HomeSectionSerializer(ImageURLMixin, serializers.ModelSerializer):
    image = serializers.SerializerMethodField()
    collection = serializers.SerializerMethodField()
    products = serializers.SerializerMethodField()

    class Meta:
        model = HomeSection
        fields = (
            "id",
            "kind",
            "eyebrow",
            "title",
            "subtitle",
            "cta_label",
            "cta_href",
            "image",
            "collection",
            "products",
            "payload",
            "sort_order",
        )

    def get_image(self, obj):
        return self._file_url(obj.image)

    def get_collection(self, obj):
        if not obj.collection_id:
            return None
        return {"name": obj.collection.name, "slug": obj.collection.slug}

    def get_products(self, obj):
        """Collection rows carry their products inline so the homepage is one call."""
        if obj.kind != HomeSection.Kind.COLLECTION_ROW or not obj.collection_id:
            return []
        from apps.catalog.models import Product
        from apps.catalog.views import CARD_PREFETCH

        limit = int(obj.payload.get("limit", 4) or 4)
        products = (
            Product.objects.active()
            .filter(collections=obj.collection)
            .select_related("category")
            .prefetch_related(CARD_PREFETCH)[:limit]
        )
        return ProductCardSerializer(products, many=True, context=self.context).data


class NewsletterSerializer(serializers.Serializer):
    """Plain serializer — re-subscribing an existing email must not 400."""

    email = serializers.EmailField()
    source = serializers.CharField(max_length=64, required=False, default="footer")


class ContactMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContactMessage
        fields = ("name", "email", "subject", "message")
