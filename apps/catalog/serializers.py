from rest_framework import serializers

from .models import (
    Category,
    Collection,
    Fabric,
    Product,
    ProductColour,
    ProductImage,
    ProductVariant,
    Review,
    Size,
)


def absolute(request, url):
    if not url:
        return ""
    return request.build_absolute_uri(url) if request else url


class ImageURLMixin:
    def _file_url(self, file_field):
        if not file_field:
            return ""
        try:
            return absolute(self.context.get("request"), file_field.url)
        except ValueError:
            return ""


class SizeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Size
        fields = ("id", "name", "sort_order")


class FabricSerializer(ImageURLMixin, serializers.ModelSerializer):
    image = serializers.SerializerMethodField()
    product_count = serializers.SerializerMethodField()

    class Meta:
        model = Fabric
        fields = ("id", "name", "slug", "description", "image", "sort_order", "product_count")

    def get_image(self, obj):
        return self._file_url(obj.image)

    def get_product_count(self, obj):
        # Annotated by the viewset; fall back to a query for nested use.
        count = getattr(obj, "product_count_annotated", None)
        return count if count is not None else obj.products.filter(is_active=True).count()


class CategorySerializer(ImageURLMixin, serializers.ModelSerializer):
    image = serializers.SerializerMethodField()
    children = serializers.SerializerMethodField()
    product_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Category
        fields = (
            "id",
            "name",
            "slug",
            "description",
            "image",
            "sort_order",
            "product_count",
            "children",
        )

    def get_image(self, obj):
        return self._file_url(obj.image)

    def get_children(self, obj):
        children = [c for c in obj.children.all() if c.is_active]
        return CategorySerializer(children, many=True, context=self.context).data


class CollectionSerializer(ImageURLMixin, serializers.ModelSerializer):
    hero_image = serializers.SerializerMethodField()

    class Meta:
        model = Collection
        fields = ("id", "name", "slug", "description", "hero_image", "sort_order")

    def get_hero_image(self, obj):
        return self._file_url(obj.hero_image)


class ProductImageSerializer(ImageURLMixin, serializers.ModelSerializer):
    url = serializers.SerializerMethodField()
    card = serializers.SerializerMethodField()
    thumb = serializers.SerializerMethodField()
    zoom = serializers.SerializerMethodField()
    alt = serializers.CharField(source="alt_text")

    class Meta:
        model = ProductImage
        fields = ("id", "url", "card", "thumb", "zoom", "alt", "is_primary", "sort_order")

    def get_url(self, obj):
        return self._file_url(obj.image)

    def _spec(self, obj, name):
        try:
            return absolute(self.context.get("request"), getattr(obj, name).url)
        except Exception:
            return self._file_url(obj.image)

    def get_card(self, obj):
        return self._spec(obj, "card")

    def get_thumb(self, obj):
        return self._spec(obj, "thumb")

    def get_zoom(self, obj):
        return self._spec(obj, "zoom")


class ProductVariantSerializer(serializers.ModelSerializer):
    size = serializers.CharField(source="size.name", read_only=True)
    size_id = serializers.IntegerField(read_only=True)
    in_stock = serializers.BooleanField(read_only=True)
    price = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)

    class Meta:
        model = ProductVariant
        fields = ("id", "size", "size_id", "sku", "stock_quantity", "in_stock", "price")


class ProductColourCardSerializer(serializers.ModelSerializer):
    """Slim colour used on product cards — swatch + one image."""

    primary_image = serializers.SerializerMethodField()
    in_stock = serializers.BooleanField(read_only=True)

    class Meta:
        model = ProductColour
        fields = ("id", "name", "swatch_hex", "primary_image", "in_stock")

    def get_primary_image(self, obj):
        image = obj.primary_image
        if not image:
            return None
        return ProductImageSerializer(image, context=self.context).data


class ProductColourSerializer(serializers.ModelSerializer):
    images = serializers.SerializerMethodField()
    variants = serializers.SerializerMethodField()
    stock = serializers.IntegerField(read_only=True)
    in_stock = serializers.BooleanField(read_only=True)

    class Meta:
        model = ProductColour
        fields = ("id", "name", "swatch_hex", "sort_order", "images", "variants", "stock", "in_stock")

    def get_images(self, obj):
        return ProductImageSerializer(obj.images.all(), many=True, context=self.context).data

    def get_variants(self, obj):
        variants = [v for v in obj.variants.all() if v.is_active]
        return ProductVariantSerializer(variants, many=True, context=self.context).data


class ProductCardSerializer(serializers.ModelSerializer):
    price = serializers.DecimalField(source="base_price", max_digits=10, decimal_places=2)
    on_sale = serializers.BooleanField(read_only=True)
    badge = serializers.CharField(read_only=True)
    in_stock = serializers.BooleanField(read_only=True)
    primary_image = serializers.SerializerMethodField()
    hover_image = serializers.SerializerMethodField()
    colours = serializers.SerializerMethodField()
    category = serializers.CharField(source="category.name", read_only=True)
    category_slug = serializers.CharField(source="category.slug", read_only=True)

    class Meta:
        model = Product
        fields = (
            "id",
            "slug",
            "name",
            "price",
            "compare_at_price",
            "currency",
            "on_sale",
            "badge",
            "is_new_in",
            "is_bestseller",
            "in_stock",
            "rating_avg",
            "review_count",
            "primary_image",
            "hover_image",
            "colours",
            "category",
            "category_slug",
        )

    def get_primary_image(self, obj):
        image = obj.primary_image
        if not image:
            return None
        return ProductImageSerializer(image, context=self.context).data

    def get_hover_image(self, obj):
        """A second photo for the listing hover-swap: another shot of the cover
        colour if there is one, else another colourway's cover image."""
        primary = obj.primary_image
        if not primary:
            return None
        for image in primary.colour.images.all():
            if image.pk != primary.pk:
                return ProductImageSerializer(image, context=self.context).data
        for colour in obj.colours.all():
            if colour.pk != primary.colour_id and colour.is_active:
                alt = colour.primary_image
                if alt:
                    return ProductImageSerializer(alt, context=self.context).data
        return None

    def get_colours(self, obj):
        colours = [c for c in obj.colours.all() if c.is_active]
        return ProductColourCardSerializer(colours, many=True, context=self.context).data


class ReviewSerializer(serializers.ModelSerializer):
    class Meta:
        model = Review
        fields = (
            "id",
            "author_name",
            "author_location",
            "rating",
            "title",
            "body",
            "is_verified",
            "created_at",
        )
        read_only_fields = ("id", "is_verified", "created_at")


class ReviewCreateSerializer(serializers.ModelSerializer):
    # The reviewer's name and location come from their (verified) account, not
    # the request, so only the rating and words are accepted here.
    class Meta:
        model = Review
        fields = ("rating", "title", "body")

    def validate_rating(self, value):
        if not 1 <= value <= 5:
            raise serializers.ValidationError("Rating must be between 1 and 5.")
        return value


class ProductDetailSerializer(ProductCardSerializer):
    colours = serializers.SerializerMethodField()
    category = CategorySerializer(read_only=True)
    fabrics = FabricSerializer(many=True, read_only=True)
    collections = CollectionSerializer(many=True, read_only=True)
    related = serializers.SerializerMethodField()
    sizes = serializers.SerializerMethodField()

    class Meta(ProductCardSerializer.Meta):
        fields = (
            "id",
            "slug",
            "name",
            "description",
            "price",
            "compare_at_price",
            "currency",
            "on_sale",
            "badge",
            "is_new_in",
            "is_bestseller",
            "in_stock",
            "rating_avg",
            "review_count",
            "primary_image",
            "colours",
            "sizes",
            "category",
            "fabrics",
            "collections",
            "composition",
            "care_instructions",
            "sustainability_note",
            "meta_title",
            "meta_description",
            "related",
        )

    def get_colours(self, obj):
        colours = [c for c in obj.colours.all() if c.is_active]
        return ProductColourSerializer(colours, many=True, context=self.context).data

    def get_sizes(self, obj):
        """Union of sizes offered across colours, in display order."""
        seen = {}
        for colour in obj.colours.all():
            for variant in colour.variants.all():
                if variant.is_active:
                    seen.setdefault(variant.size_id, variant.size)
        sizes = sorted(seen.values(), key=lambda s: (s.sort_order, s.name))
        return SizeSerializer(sizes, many=True).data

    def get_related(self, obj):
        related = (
            Product.objects.active()
            .with_cards()
            .filter(category_id=obj.category_id)
            .exclude(pk=obj.pk)[:4]
        )
        return ProductCardSerializer(related, many=True, context=self.context).data
