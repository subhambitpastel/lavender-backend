from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.core.mail import send_mail
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Address
from apps.cart.models import Cart
from apps.cart.utils import get_cart, read_cart_token

from .models import Discount, Order
from .serializers import (
    CheckoutSerializer,
    OrderSerializer,
    ReturnCreateSerializer,
    ReturnSerializer,
)
from .services import CheckoutError, ReturnError, place_order, request_return


class DiscountPreviewView(APIView):
    """POST {code, subtotal} → preview a promo code for the checkout summary.

    Stateless on purpose: the storefront cart lives in the browser, so it sends
    the subtotal directly rather than needing a server cart. This is UX only —
    checkout re-validates the code and recomputes the amount under a row lock, so
    a tampered preview can never change what's actually charged.
    """

    permission_classes = [AllowAny]

    def post(self, request):
        code = (request.data.get("code") or "").strip().upper()
        if not code:
            return Response(
                {"detail": "Enter a promo code.", "code": "invalid_discount"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            subtotal = Decimal(str(request.data.get("subtotal", "0")))
        except (InvalidOperation, TypeError, ValueError):
            subtotal = Decimal("0")
        subtotal = max(subtotal, Decimal("0"))

        discount = Discount.objects.filter(code=code).first()
        if discount is None:
            return Response(
                {"detail": "That promo code isn't recognised.", "code": "invalid_discount"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        ok, reason = discount.is_valid(subtotal)
        if not ok:
            return Response(
                {"detail": reason, "code": "invalid_discount"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            {
                "code": discount.code,
                "description": discount.description,
                "kind": discount.kind,
                "value": str(discount.value),
                "amount": str(discount.amount_for(subtotal)),
            }
        )


class CheckoutView(APIView):
    """POST → creates the order, decrements stock, runs the payment provider."""

    permission_classes = [AllowAny]

    @extend_schema(request=CheckoutSerializer, responses=OrderSerializer)
    def post(self, request):
        serializer = CheckoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # The storefront rebuilds the bag as a fresh guest cart (X-Cart-Token) on
        # every checkout, so honour that token even for a signed-in shopper —
        # otherwise get_cart would return their (empty) account cart and the sale
        # would fail with "empty bag". The order is still attributed to
        # request.user below, so a signed-in checkout lands in their "My Orders".
        cart = None
        token = read_cart_token(request)
        if token:
            cart = Cart.objects.filter(token=token, is_active=True).first()
        if cart is None:
            cart = get_cart(request, create=False)
        if cart is None or not cart.items.exists():
            return Response(
                {"detail": "Your bag is empty.", "code": "empty_cart"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            order = place_order(
                cart=cart,
                data=data,
                user=request.user if request.user.is_authenticated else None,
                request=request,
            )
        except CheckoutError as exc:
            return Response(
                {"detail": exc.message, "code": exc.code, **exc.detail},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if data.get("save_address") and request.user.is_authenticated:
            Address.objects.get_or_create(
                user=request.user,
                line1=data["shipping"]["line1"],
                postcode=data["shipping"]["postcode"],
                defaults={**data["shipping"], "is_default_shipping": True},
            )

        self._send_confirmation(order)

        payload = OrderSerializer(order, context={"request": request}).data
        payload["payment"] = {
            "provider": order.payment_provider,
            "payment_ref": order.payment_ref,
            "client_secret": getattr(order, "payment_client_secret", ""),
            "status": order.payment_status,
        }
        return Response(payload, status=status.HTTP_201_CREATED)

    @staticmethod
    def _send_confirmation(order):
        lines = "\n".join(
            f"  {i.quantity} × {i.product_name} ({i.colour_name} / {i.size_name}) — "
            f"{order.currency} {i.line_total}"
            for i in order.items.all()
        )
        send_mail(
            f"Your Lavender Hill order {order.number}",
            f"Thank you for your order.\n\n{lines}\n\n"
            f"Total: {order.currency} {order.grand_total}\n",
            settings.DEFAULT_FROM_EMAIL,
            [order.email],
            fail_silently=True,
        )


class OrderViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Signed-in customers' order history."""

    serializer_class = OrderSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = "number"
    lookup_value_regex = "[^/]+"
    filter_backends = []

    def get_queryset(self):
        return Order.objects.filter(user=self.request.user).prefetch_related("items")

    def get_serializer_context(self):
        context = super().get_serializer_context()
        # One query for every product this shopper has reviewed, so each order
        # line can flag itself as reviewed without an N+1.
        from apps.catalog.models import Review

        reviews = (
            Review.objects.filter(user=self.request.user)
            .select_related("product")
            .prefetch_related("events")
        )
        by_slug = {review.product.slug: review for review in reviews}
        context["reviews_by_slug"] = by_slug
        context["reviewed_slugs"] = set(by_slug.keys())
        return context

    @action(detail=True, methods=["get", "post"], url_path="returns")
    def returns(self, request, number=None):
        """GET the order's returns; POST to request a new one for chosen lines."""
        order = self.get_object()
        if request.method.lower() == "get":
            data = ReturnSerializer(
                order.returns.prefetch_related("items__order_item"), many=True
            ).data
            return Response({"returns": data})

        serializer = ReturnCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data
        items = {line["order_item"]: line["quantity"] for line in payload["items"]}
        try:
            ret = request_return(
                order=order,
                user=request.user,
                items=items,
                reason=payload["reason"],
                note=payload.get("note", ""),
            )
        except ReturnError as exc:
            return Response({"detail": exc.message, "code": exc.code}, status=status.HTTP_400_BAD_REQUEST)
        return Response(ReturnSerializer(ret).data, status=status.HTTP_201_CREATED)


class OrderLookupView(APIView):
    """Guest order confirmation: /orders/lookup/?number=…&email=…"""

    permission_classes = [AllowAny]

    def get(self, request):
        number = (request.query_params.get("number") or "").strip()
        email = (request.query_params.get("email") or "").strip()
        if not number or not email:
            return Response(
                {"detail": "Order number and email are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        order = Order.objects.filter(number=number, email__iexact=email).first()
        if order is None:
            return Response(
                {"detail": "No order matches those details."}, status=status.HTTP_404_NOT_FOUND
            )
        return Response(OrderSerializer(order, context={"request": request}).data)
