from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.models import Product
from apps.catalog.views import card_prefetch

from .models import WishlistItem
from .serializers import WishlistAddSerializer, WishlistItemSerializer


class WishlistView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=WishlistItemSerializer(many=True))
    def get(self, request):
        items = (
            WishlistItem.objects.filter(user=request.user)
            .select_related("product__category")
            .prefetch_related(card_prefetch("product__colours"))
        )
        return Response(WishlistItemSerializer(items, many=True, context={"request": request}).data)

    @extend_schema(request=WishlistAddSerializer, responses=WishlistItemSerializer)
    def post(self, request):
        serializer = WishlistAddSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        product = Product.objects.filter(slug=serializer.validated_data["product"]).first()
        if product is None:
            return Response({"detail": "Product not found."}, status=status.HTTP_404_NOT_FOUND)
        item, created = WishlistItem.objects.get_or_create(user=request.user, product=product)
        return Response(
            WishlistItemSerializer(item, context={"request": request}).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class WishlistItemView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, slug):
        deleted, _ = WishlistItem.objects.filter(
            user=request.user, product__slug=slug
        ).delete()
        if not deleted:
            return Response({"detail": "Not in your wishlist."}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)
