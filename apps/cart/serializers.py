from rest_framework import serializers

from apps.catalog.models import ProductVariant
from apps.catalog.serializers import ProductImageSerializer

from .models import Cart, CartItem


class CartItemVariantSerializer(serializers.ModelSerializer):
    size = serializers.CharField(source="size.name", read_only=True)
    colour = serializers.CharField(source="colour.name", read_only=True)
    swatch_hex = serializers.CharField(source="colour.swatch_hex", read_only=True)
    product = serializers.SerializerMethodField()

    class Meta:
        model = ProductVariant
        fields = ("id", "sku", "size", "colour", "swatch_hex", "stock_quantity", "product")

    def get_product(self, obj):
        product = obj.colour.product
        image = obj.colour.primary_image
        return {
            "slug": product.slug,
            "name": product.name,
            "image": ProductImageSerializer(image, context=self.context).data if image else None,
        }


class CartItemSerializer(serializers.ModelSerializer):
    variant = CartItemVariantSerializer(read_only=True)
    unit_price = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    line_total = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    max_qty = serializers.IntegerField(source="max_quantity", read_only=True)

    class Meta:
        model = CartItem
        fields = ("id", "variant", "unit_price", "quantity", "line_total", "max_qty")


class CartSerializer(serializers.ModelSerializer):
    items = CartItemSerializer(many=True, read_only=True)
    subtotal = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    discount = serializers.SerializerMethodField()
    shipping_estimate = serializers.SerializerMethodField()
    total = serializers.SerializerMethodField()
    item_count = serializers.IntegerField(read_only=True)
    free_shipping_remaining = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True
    )

    class Meta:
        model = Cart
        fields = (
            "token",
            "items",
            "item_count",
            "subtotal",
            "discount",
            "shipping_estimate",
            "total",
            "free_shipping_remaining",
        )

    def get_discount(self, obj):
        if not obj.discount_id:
            return None
        return {
            "code": obj.discount.code,
            "kind": obj.discount.kind,
            "value": obj.discount.value,
            "amount": obj.discount_total,
        }

    def get_shipping_estimate(self, obj):
        return obj.shipping_estimate()

    def get_total(self, obj):
        return obj.total()


class CartItemWriteSerializer(serializers.Serializer):
    variant_id = serializers.IntegerField()
    quantity = serializers.IntegerField(min_value=1, default=1)

    def validate(self, attrs):
        try:
            variant = ProductVariant.objects.select_related("colour__product").get(
                pk=attrs["variant_id"], is_active=True
            )
        except ProductVariant.DoesNotExist:
            raise serializers.ValidationError({"variant_id": "That item is not available."})
        if not variant.colour.product.is_active:
            raise serializers.ValidationError({"variant_id": "That item is not available."})
        attrs["variant"] = variant
        return attrs


class CartItemUpdateSerializer(serializers.Serializer):
    quantity = serializers.IntegerField(min_value=0)


class DiscountApplySerializer(serializers.Serializer):
    code = serializers.CharField(max_length=40)
