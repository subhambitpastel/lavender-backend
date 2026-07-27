from rest_framework import serializers

from apps.catalog.serializers import ProductCardSerializer

from .models import WishlistItem


class WishlistItemSerializer(serializers.ModelSerializer):
    product = ProductCardSerializer(read_only=True)

    class Meta:
        model = WishlistItem
        fields = ("id", "product", "created_at")


class WishlistAddSerializer(serializers.Serializer):
    product = serializers.SlugField(help_text="Product slug")
