from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.orders.models import Discount

from .models import CartItem
from .serializers import (
    CartItemUpdateSerializer,
    CartItemWriteSerializer,
    CartSerializer,
    DiscountApplySerializer,
)
from .utils import cart_response_headers, get_cart


class CartMixin:
    permission_classes = [AllowAny]

    def cart_payload(self, request, cart, http_status=status.HTTP_200_OK, extra=None):
        cart.refresh_from_db()
        data = CartSerializer(cart, context={"request": request}).data
        if extra:
            data.update(extra)
        return Response(data, status=http_status, headers=cart_response_headers(cart))


class CartView(CartMixin, APIView):
    """GET the active cart for this user / cart-token."""

    @extend_schema(responses=CartSerializer)
    def get(self, request):
        cart = get_cart(request)
        return self.cart_payload(request, cart)

    @extend_schema(description="Empty the cart.")
    def delete(self, request):
        cart = get_cart(request)
        cart.items.all().delete()
        cart.discount = None
        cart.save(update_fields=["discount", "updated_at"])
        return self.cart_payload(request, cart)


class CartItemsView(CartMixin, APIView):
    """POST {variant_id, quantity} to add an item (stock-validated)."""

    @extend_schema(request=CartItemWriteSerializer, responses=CartSerializer)
    def post(self, request):
        serializer = CartItemWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        variant = serializer.validated_data["variant"]
        quantity = serializer.validated_data["quantity"]

        cart = get_cart(request)
        item = cart.items.filter(variant=variant).first()
        wanted = (item.quantity if item else 0) + quantity

        if wanted > variant.stock_quantity:
            if variant.stock_quantity == 0:
                return Response(
                    {"detail": "This size is out of stock.", "code": "out_of_stock"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            return Response(
                {
                    "detail": f"Only {variant.stock_quantity} left in this size.",
                    "code": "insufficient_stock",
                    "available": variant.stock_quantity,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if item:
            item.quantity = wanted
            item.save(update_fields=["quantity", "updated_at"])
        else:
            CartItem.objects.create(cart=cart, variant=variant, quantity=quantity)
        return self.cart_payload(request, cart, http_status=status.HTTP_201_CREATED)


class CartItemDetailView(CartMixin, APIView):
    """PATCH quantity / DELETE a line item."""

    def get_item(self, request, pk):
        cart = get_cart(request, create=False)
        if cart is None:
            return None, None
        return cart, cart.items.filter(pk=pk).select_related("variant").first()

    @extend_schema(request=CartItemUpdateSerializer, responses=CartSerializer)
    def patch(self, request, pk):
        cart, item = self.get_item(request, pk)
        if item is None:
            return Response({"detail": "Item not found."}, status=status.HTTP_404_NOT_FOUND)

        serializer = CartItemUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        quantity = serializer.validated_data["quantity"]

        if quantity == 0:
            item.delete()
            return self.cart_payload(request, cart)
        if quantity > item.variant.stock_quantity:
            return Response(
                {
                    "detail": f"Only {item.variant.stock_quantity} left in this size.",
                    "code": "insufficient_stock",
                    "available": item.variant.stock_quantity,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        item.quantity = quantity
        item.save(update_fields=["quantity", "updated_at"])
        return self.cart_payload(request, cart)

    @extend_schema(responses=CartSerializer)
    def delete(self, request, pk):
        cart, item = self.get_item(request, pk)
        if item is None:
            return Response({"detail": "Item not found."}, status=status.HTTP_404_NOT_FOUND)
        item.delete()
        return self.cart_payload(request, cart)


class CartDiscountView(CartMixin, APIView):
    """POST {code} to apply a promo code; DELETE to clear it."""

    @extend_schema(request=DiscountApplySerializer, responses=CartSerializer)
    def post(self, request):
        serializer = DiscountApplySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        code = serializer.validated_data["code"].strip().upper()

        cart = get_cart(request)
        discount = Discount.objects.filter(code=code).first()
        if discount is None:
            return Response(
                {"detail": "That promo code isn't recognised.", "code": "invalid_discount"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        ok, reason = discount.is_valid(cart.subtotal)
        if not ok:
            return Response(
                {"detail": reason, "code": "invalid_discount"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if discount.redeemed_by(user=request.user):
            return Response(
                {"detail": "You've already used this promo code.", "code": "discount_used"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        cart.discount = discount
        cart.save(update_fields=["discount", "updated_at"])
        return self.cart_payload(request, cart, extra={"detail": f"{code} applied."})

    @extend_schema(responses=CartSerializer)
    def delete(self, request):
        cart = get_cart(request)
        cart.discount = None
        cart.save(update_fields=["discount", "updated_at"])
        return self.cart_payload(request, cart)


class CartMergeView(CartMixin, APIView):
    """POST {cart_token} while authenticated to fold a guest cart in."""

    @extend_schema(responses=CartSerializer)
    def post(self, request):
        from .utils import merge_guest_cart

        if not request.user.is_authenticated:
            return Response(
                {"detail": "Authentication required."}, status=status.HTTP_401_UNAUTHORIZED
            )
        merge_guest_cart(request, request.user)
        cart = get_cart(request)
        return self.cart_payload(request, cart)
