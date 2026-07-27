"""Cart resolution: a request maps to exactly one cart, user or guest."""

import uuid

from django.conf import settings

from .models import Cart

CART_TOKEN_HEADER = "HTTP_X_CART_TOKEN"


def _as_uuid(value):
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


def read_cart_token(request):
    """Cart token from the header, a query/body param, or a cookie — in that order."""
    candidates = [request.META.get(CART_TOKEN_HEADER)]
    query_params = getattr(request, "query_params", None) or request.GET
    candidates.append(query_params.get("cart_token"))
    data = getattr(request, "data", None)
    if isinstance(data, dict):
        candidates.append(data.get("cart_token"))
    candidates.append(request.COOKIES.get("cart-token"))

    for candidate in candidates:
        token = _as_uuid(candidate)
        if token:
            return token
    return None


def get_cart(request, create=True):
    """Return the cart for this request, creating one when needed."""
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        cart = Cart.objects.filter(user=user, is_active=True).order_by("-updated_at").first()
        if cart is None and create:
            cart = Cart.objects.create(user=user)
        return cart

    token = read_cart_token(request)
    cart = None
    if token:
        cart = Cart.objects.filter(token=token, is_active=True).first()
    if cart is None and create:
        cart = Cart.objects.create(token=token or uuid.uuid4())
    return cart


def merge_guest_cart(request, user):
    """After login/register, fold the guest cart into the user's cart."""
    token = read_cart_token(request)
    if not token:
        return None

    guest_cart = Cart.objects.filter(token=token, user__isnull=True, is_active=True).first()
    if guest_cart is None:
        return None

    user_cart = Cart.objects.filter(user=user, is_active=True).order_by("-updated_at").first()
    if user_cart is None:
        guest_cart.user = user
        guest_cart.save(update_fields=["user", "updated_at"])
        return guest_cart
    return user_cart.merge_from(guest_cart)


def cart_response_headers(cart):
    return {settings.CART_TOKEN_HEADER: str(cart.token)} if cart else {}
