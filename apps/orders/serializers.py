from rest_framework import serializers

from .models import Discount, Order, OrderItem, Return, ReturnItem


class OrderItemSerializer(serializers.ModelSerializer):
    # True when the signed-in shopper has already reviewed this product. The set
    # of reviewed slugs is computed once per request and passed in via context,
    # so this stays a plain lookup rather than a query per line.
    reviewed = serializers.SerializerMethodField()
    # The shopper's own review for this product (with its moderation status and
    # full history) so "My Orders" can show pending / changes-requested / live
    # and let them edit & resubmit. Null when they haven't reviewed it.
    review = serializers.SerializerMethodField()
    # How many of this line can still be returned (quantity minus anything tied
    # up in a live return) — drives the return picker's max per line.
    returnable_quantity = serializers.IntegerField(read_only=True)

    class Meta:
        model = OrderItem
        fields = (
            "id",
            "product_slug",
            "product_name",
            "colour_name",
            "size_name",
            "sku",
            "image_url",
            "unit_price",
            "quantity",
            "line_total",
            "returnable_quantity",
            "reviewed",
            "review",
        )

    def get_reviewed(self, obj):
        return obj.product_slug in self.context.get("reviewed_slugs", set())

    def get_review(self, obj):
        review = self.context.get("reviews_by_slug", {}).get(obj.product_slug)
        if review is None:
            return None
        return {
            "status": review.status,
            "rejection_reason": review.rejection_reason,
            "rating": review.rating,
            "title": review.title,
            "body": review.body,
            "editable": review.is_editable,
            "edit_deadline": review.edit_deadline,
            "history": [
                {
                    "action": event.action,
                    "reason": event.reason,
                    "rating": event.rating,
                    "title": event.title,
                    "body": event.body,
                    "at": event.created_at,
                    "by_staff": bool(event.actor and event.actor.is_staff),
                }
                for event in review.events.all()
            ],
        }


class ReturnItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="order_item.product_name", read_only=True)
    colour_name = serializers.CharField(source="order_item.colour_name", read_only=True)
    size_name = serializers.CharField(source="order_item.size_name", read_only=True)
    order_item = serializers.IntegerField(source="order_item_id", read_only=True)
    line_refund = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)

    class Meta:
        model = ReturnItem
        fields = ("order_item", "product_name", "colour_name", "size_name", "quantity", "line_refund")


class ReturnSerializer(serializers.ModelSerializer):
    items = ReturnItemSerializer(many=True, read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    reason_display = serializers.CharField(source="get_reason_display", read_only=True)

    class Meta:
        model = Return
        fields = (
            "number",
            "status",
            "status_display",
            "reason",
            "reason_display",
            "customer_note",
            "staff_note",
            "refund_total",
            "items",
            "created_at",
            "resolved_at",
        )


class ReturnCreateSerializer(serializers.Serializer):
    """Write shape for POST /orders/{number}/returns/ — validated in the service."""

    class _Line(serializers.Serializer):
        order_item = serializers.IntegerField()
        quantity = serializers.IntegerField(min_value=1)

    reason = serializers.ChoiceField(choices=Return.Reason.choices)
    note = serializers.CharField(required=False, allow_blank=True, default="")
    items = _Line(many=True)

    def validate_items(self, value):
        if not value:
            raise serializers.ValidationError("Select at least one item to return.")
        return value


class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    shipping_method_display = serializers.CharField(
        source="get_shipping_method_display", read_only=True
    )
    item_count = serializers.IntegerField(read_only=True)
    is_returnable = serializers.BooleanField(read_only=True)
    return_window_ends = serializers.DateTimeField(read_only=True)
    returns = ReturnSerializer(many=True, read_only=True)
    # True when the order belongs to a passwordless guest account the shopper can
    # still finish (set a password) — drives the "create your account" prompt.
    account_claimable = serializers.SerializerMethodField()

    def get_account_claimable(self, obj):
        return bool(obj.user_id and not obj.user.has_usable_password())

    class Meta:
        model = Order
        fields = (
            "number",
            "email",
            "account_claimable",
            "phone",
            "status",
            "status_display",
            "payment_status",
            "payment_ref",
            "subtotal",
            "discount_total",
            "shipping_total",
            "tax_total",
            "grand_total",
            "currency",
            "discount_code",
            "shipping_method",
            "shipping_method_display",
            "shipping_address",
            "billing_address",
            "customer_note",
            "tracking_number",
            "items",
            "item_count",
            "is_returnable",
            "return_window_ends",
            "returns",
            "placed_at",
            "delivered_at",
            "created_at",
        )


class AddressInputSerializer(serializers.Serializer):
    # Name is collected after the order (on the confirmation page), so it may be
    # blank at checkout — the address still ships; the name is backfilled later.
    first_name = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    last_name = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    line1 = serializers.CharField(max_length=255)
    line2 = serializers.CharField(max_length=255, required=False, allow_blank=True)
    city = serializers.CharField(max_length=120)
    county = serializers.CharField(max_length=120, required=False, allow_blank=True)
    postcode = serializers.CharField(max_length=20)
    country = serializers.CharField(max_length=2, default="GB")
    phone = serializers.CharField(max_length=32, required=False, allow_blank=True)


class ContactInputSerializer(serializers.Serializer):
    email = serializers.EmailField()
    phone = serializers.CharField(max_length=32, required=False, allow_blank=True)
    marketing_opt_in = serializers.BooleanField(required=False, default=False)


class CheckoutSerializer(serializers.Serializer):
    contact = ContactInputSerializer()
    shipping = AddressInputSerializer()
    billing = AddressInputSerializer(required=False)
    shipping_method = serializers.ChoiceField(
        choices=Order.ShippingMethod.choices, default=Order.ShippingMethod.STANDARD
    )
    discount_code = serializers.CharField(required=False, allow_blank=True)
    customer_note = serializers.CharField(required=False, allow_blank=True)
    save_address = serializers.BooleanField(required=False, default=False)
    payment = serializers.DictField(required=False, default=dict)


class DiscountSerializer(serializers.ModelSerializer):
    class Meta:
        model = Discount
        fields = ("code", "kind", "value", "min_spend", "description")
