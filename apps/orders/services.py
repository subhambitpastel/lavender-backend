"""Checkout: turn a cart into an order without ever overselling."""

from decimal import Decimal

from django.conf import settings
from django.db import models, transaction
from django.utils import timezone

from apps.catalog.models import ProductVariant
from apps.core.utils import money

from . import payments
from .models import Discount, Order, OrderItem, Return, ReturnItem


class CheckoutError(Exception):
    """Raised when a cart cannot be converted into an order."""

    def __init__(self, message, code="checkout_error", detail=None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.detail = detail or {}


class ReturnError(Exception):
    """Raised when a return request is invalid (window closed, bad quantity…)."""

    def __init__(self, message, code="return_error"):
        super().__init__(message)
        self.message = message
        self.code = code


def shipping_cost(subtotal: Decimal, method: str) -> Decimal:
    if subtotal >= Decimal(settings.FREE_SHIPPING_THRESHOLD):
        return Decimal("0.00")
    if method == Order.ShippingMethod.EXPRESS:
        return money(settings.EXPRESS_SHIPPING_FEE)
    return money(settings.STANDARD_SHIPPING_FEE)


def _image_url(variant, request=None):
    image = variant.colour.primary_image
    if not image:
        return ""
    url = image.image.url
    return request.build_absolute_uri(url) if request else url


@transaction.atomic
def place_order(*, cart, data, user=None, request=None) -> Order:
    """Create an order from ``cart``.

    Stock is re-checked under ``select_for_update`` and decremented in the same
    transaction, so two concurrent checkouts can never both take the last item.
    """
    items = list(cart.items.select_related("variant__colour__product", "variant__size"))
    if not items:
        raise CheckoutError("Your bag is empty.", code="empty_cart")

    variant_ids = [item.variant_id for item in items]
    locked = {
        v.pk: v
        for v in ProductVariant.objects.select_for_update()
        .select_related("colour__product", "size")
        .filter(pk__in=variant_ids)
    }

    out_of_stock = []
    for item in items:
        variant = locked.get(item.variant_id)
        if variant is None or not variant.is_active:
            out_of_stock.append({"variant_id": item.variant_id, "reason": "unavailable"})
        elif variant.stock_quantity < item.quantity:
            out_of_stock.append(
                {
                    "variant_id": item.variant_id,
                    "sku": variant.sku,
                    "reason": "insufficient_stock",
                    "available": variant.stock_quantity,
                    "requested": item.quantity,
                }
            )
    if out_of_stock:
        raise CheckoutError(
            "Some items are no longer available in the quantity requested.",
            code="out_of_stock",
            detail={"items": out_of_stock},
        )

    subtotal = money(
        sum(
            (locked[item.variant_id].price * item.quantity for item in items),
            Decimal("0"),
        )
    )

    # ---------------------------------------------------------------- discount
    discount_total = Decimal("0.00")
    discount_obj = None
    code = (data.get("discount_code") or "").strip().upper()
    if not code and cart.discount_id:
        discount_obj = cart.discount
        code = discount_obj.code
    elif code:
        discount_obj = Discount.objects.select_for_update().filter(code=code).first()
        if discount_obj is None:
            raise CheckoutError("That promo code isn't recognised.", code="invalid_discount")
    if discount_obj:
        ok, reason = discount_obj.is_valid(subtotal)
        if not ok:
            raise CheckoutError(reason, code="invalid_discount")
        buyer_email = (data.get("contact") or {}).get("email") or (
            user.email if user and getattr(user, "is_authenticated", False) else ""
        )
        if discount_obj.redeemed_by(user=user, email=buyer_email):
            raise CheckoutError(
                "You've already used this promo code.", code="discount_used"
            )
        discount_total = discount_obj.amount_for(subtotal)

    method = data.get("shipping_method") or Order.ShippingMethod.STANDARD
    shipping_total = shipping_cost(subtotal, method)
    taxable = max(subtotal - discount_total, Decimal("0"))
    tax_total = money(taxable * Decimal(settings.TAX_RATE) / Decimal("100"))
    grand_total = money(taxable + shipping_total + tax_total)

    contact = data.get("contact") or {}
    shipping_address = data.get("shipping") or {}
    billing_address = data.get("billing") or shipping_address

    order = Order.objects.create(
        user=user if (user and user.is_authenticated) else None,
        email=contact.get("email") or (user.email if user and user.is_authenticated else ""),
        phone=contact.get("phone", ""),
        status=Order.Status.DRAFT,
        subtotal=subtotal,
        discount_total=discount_total,
        shipping_total=shipping_total,
        tax_total=tax_total,
        grand_total=grand_total,
        currency=settings.DEFAULT_CURRENCY,
        discount_code=code,
        shipping_method=method,
        shipping_address=shipping_address,
        billing_address=billing_address,
        customer_note=data.get("customer_note", ""),
        placed_at=timezone.now(),
    )

    for item in items:
        variant = locked[item.variant_id]
        unit_price = money(variant.price)
        OrderItem.objects.create(
            order=order,
            variant=variant,
            product_slug=variant.colour.product.slug,
            product_name=variant.colour.product.name,
            colour_name=variant.colour.name,
            size_name=variant.size.name,
            sku=variant.sku,
            image_url=_image_url(variant, request),
            unit_price=unit_price,
            quantity=item.quantity,
            line_total=money(unit_price * item.quantity),
        )
        variant.stock_quantity -= item.quantity
        variant.save(update_fields=["stock_quantity", "updated_at"])

    if discount_obj:
        Discount.objects.filter(pk=discount_obj.pk).update(used_count=discount_obj.used_count + 1)

    # ----------------------------------------------------------------- payment
    result = payments.create_payment(order)
    order.payment_ref = result.payment_ref
    order.payment_provider = result.provider
    if result.status == "paid":
        order.payment_status = Order.PaymentStatus.PAID
        order.status = Order.Status.CONFIRMED
    order.save(update_fields=["payment_ref", "payment_provider", "payment_status", "status", "updated_at"])
    order.payment_client_secret = result.client_secret  # transient, for the response

    # Seed the activity log with how the order entered its first status.
    order.status_events.create(
        from_status="",
        to_status=order.status,
        actor="system",
        note="Order placed" + (" and paid" if order.status == Order.Status.CONFIRMED else ""),
    )

    cart.items.all().delete()
    cart.discount = None
    cart.is_active = False
    cart.save(update_fields=["discount", "is_active", "updated_at"])

    return order


@transaction.atomic
def cancel_order(order: Order, *, refund=False, actor="") -> Order:
    """Cancel or refund an order and put its stock back."""
    order.restock()
    old = order.status
    if refund:
        payments.refund_payment(order)
        order.status = Order.Status.REFUNDED
        order.payment_status = Order.PaymentStatus.REFUNDED
    else:
        order.status = Order.Status.CANCELLED
    order.save(update_fields=["status", "payment_status", "updated_at"])
    order.status_events.create(
        from_status=old,
        to_status=order.status,
        actor=actor or "admin",
        note="Refunded and restocked" if refund else "Cancelled and restocked",
    )
    return order


# --------------------------------------------------------------------- returns


@transaction.atomic
def request_return(*, order: Order, user=None, items: dict, reason: str, note: str = "") -> Return:
    """Create a customer return request for specific order lines.

    ``items`` maps ``order_item_id`` → quantity. Validates the order is inside
    its return window and that each quantity is available (not already tied up in
    a live return). The request lands as REQUESTED — no money/stock moves until a
    staff member approves it.
    """
    if not order.is_returnable:
        raise ReturnError(
            "This order isn't eligible for a return (it must be delivered and "
            "within the return window)."
        )

    valid_reasons = {choice[0] for choice in Return.Reason.choices}
    if reason not in valid_reasons:
        raise ReturnError("Choose a reason for the return.")

    by_id = {item.id: item for item in order.items.all()}
    cleaned = []  # (order_item, quantity)
    for raw_id, raw_qty in items.items():
        try:
            item = by_id[int(raw_id)]
            qty = int(raw_qty)
        except (KeyError, ValueError, TypeError):
            raise ReturnError("That item isn't part of this order.")
        if qty <= 0:
            continue
        if qty > item.returnable_quantity:
            raise ReturnError(
                f"You can return at most {item.returnable_quantity} of "
                f"“{item.product_name}”."
            )
        cleaned.append((item, qty))

    if not cleaned:
        raise ReturnError("Select at least one item to return.")

    ret = Return.objects.create(
        order=order,
        user=user or order.user,
        reason=reason,
        customer_note=note.strip(),
        status=Return.Status.REQUESTED,
    )
    ReturnItem.objects.bulk_create(
        [ReturnItem(return_request=ret, order_item=item, quantity=qty) for item, qty in cleaned]
    )
    ret.refund_total = ret.compute_refund_total()
    ret.save(update_fields=["refund_total"])

    order.status_events.create(
        from_status=order.status,
        to_status=order.status,
        actor=order.email,
        note=f"Return {ret.number} requested ({ret.item_count} item(s)).",
    )
    return ret


@transaction.atomic
def resolve_return(*, ret: Return, approve: bool, actor: str = "", staff_note: str = "") -> Return:
    """Approve (refund + restock the returned lines) or reject a return request.

    Restock is idempotent via ``Return.restocked``. The refund is recorded on the
    return; a real gateway would refund ``refund_total`` here (MockProvider is a
    no-op, StripeProvider would call a partial refund)."""
    if ret.status != Return.Status.REQUESTED:
        raise ReturnError("This return has already been resolved.")

    ret.staff_note = staff_note.strip()
    ret.resolved_at = timezone.now()

    if approve:
        if not ret.restocked:
            for return_item in ret.items.select_related("order_item"):
                variant_id = return_item.order_item.variant_id
                if variant_id:
                    ProductVariant.objects.filter(pk=variant_id).update(
                        stock_quantity=models.F("stock_quantity") + return_item.quantity
                    )
            ret.restocked = True
        payments.refund_payment(ret.order)  # gateway refund (mock: no-op)
        ret.status = Return.Status.APPROVED
        note = f"Return {ret.number} approved — refunded {ret.refund_total} and restocked."
    else:
        ret.status = Return.Status.REJECTED
        note = f"Return {ret.number} rejected."

    ret.save(update_fields=["status", "staff_note", "restocked", "resolved_at", "updated_at"])
    ret.order.status_events.create(
        from_status=ret.order.status,
        to_status=ret.order.status,
        actor=actor or "admin",
        note=note + (f" Note: {ret.staff_note}" if ret.staff_note else ""),
    )
    return ret
