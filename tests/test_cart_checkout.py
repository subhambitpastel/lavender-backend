import pytest

from apps.cart.models import Cart
from apps.orders.models import Order
from tests import factories


def add_to_cart(api, variant, quantity=1, token=None):
    headers = {"HTTP_X_CART_TOKEN": str(token)} if token else {}
    return api.post(
        "/api/v1/cart/items/",
        {"variant_id": variant.pk, "quantity": quantity},
        format="json",
        **headers,
    )


@pytest.mark.django_db
class TestGuestCart:
    def test_adding_an_item_returns_the_cart_and_a_token(self, api, variant):
        response = add_to_cart(api, variant, 2)
        assert response.status_code == 201
        assert response.data["item_count"] == 2
        assert float(response.data["subtotal"]) == 200.0
        assert response["X-Cart-Token"]

    def test_the_token_resolves_the_same_cart(self, api, variant):
        token = add_to_cart(api, variant).data["token"]
        response = api.get("/api/v1/cart/", HTTP_X_CART_TOKEN=str(token))
        assert response.data["item_count"] == 1

    def test_adding_the_same_variant_twice_merges_quantities(self, api, variant):
        token = add_to_cart(api, variant).data["token"]
        response = add_to_cart(api, variant, 3, token=token)
        assert response.data["item_count"] == 4
        assert len(response.data["items"]) == 1

    def test_cannot_add_more_than_stock(self, api, variant):
        response = add_to_cart(api, variant, 99)
        assert response.status_code == 400
        assert response.data["code"] == "insufficient_stock"
        assert response.data["available"] == 10

    def test_out_of_stock_variant_is_rejected(self, api, variant):
        variant.stock_quantity = 0
        variant.save()
        response = add_to_cart(api, variant, 1)
        assert response.status_code == 400
        assert response.data["code"] == "out_of_stock"

    def test_update_and_remove_a_line(self, api, variant):
        created = add_to_cart(api, variant, 2)
        token = created.data["token"]
        item_id = created.data["items"][0]["id"]

        updated = api.patch(
            f"/api/v1/cart/items/{item_id}/", {"quantity": 5}, format="json",
            HTTP_X_CART_TOKEN=str(token),
        )
        assert updated.data["item_count"] == 5

        emptied = api.delete(f"/api/v1/cart/items/{item_id}/", HTTP_X_CART_TOKEN=str(token))
        assert emptied.data["item_count"] == 0

    def test_setting_quantity_to_zero_removes_the_line(self, api, variant):
        created = add_to_cart(api, variant, 2)
        response = api.patch(
            f"/api/v1/cart/items/{created.data['items'][0]['id']}/",
            {"quantity": 0}, format="json",
            HTTP_X_CART_TOKEN=str(created.data["token"]),
        )
        assert response.data["items"] == []

    def test_free_shipping_progress(self, api, variant):
        response = add_to_cart(api, variant, 1)  # £100, threshold £50
        assert float(response.data["free_shipping_remaining"]) == 0.0
        assert float(response.data["shipping_estimate"]) == 0.0


@pytest.mark.django_db
class TestDiscounts:
    def test_applying_a_valid_code(self, api, variant):
        factories.DiscountFactory(code="SOFT10", value=10)
        token = add_to_cart(api, variant).data["token"]
        response = api.post(
            "/api/v1/cart/apply-discount/", {"code": "soft10"}, format="json",
            HTTP_X_CART_TOKEN=str(token),
        )
        assert response.status_code == 200
        assert float(response.data["discount"]["amount"]) == 10.0
        assert float(response.data["total"]) == 90.0

    def test_unknown_code_is_rejected(self, api, variant):
        token = add_to_cart(api, variant).data["token"]
        response = api.post(
            "/api/v1/cart/apply-discount/", {"code": "NOPE"}, format="json",
            HTTP_X_CART_TOKEN=str(token),
        )
        assert response.status_code == 400

    def test_min_spend_is_enforced(self, api, variant):
        factories.DiscountFactory(code="BIG", kind="fixed", value=15, min_spend=500)
        token = add_to_cart(api, variant).data["token"]
        response = api.post(
            "/api/v1/cart/apply-discount/", {"code": "BIG"}, format="json",
            HTTP_X_CART_TOKEN=str(token),
        )
        assert response.status_code == 400
        assert "Spend" in response.data["detail"]

    # -- stateless preview used by the checkout summary (no server cart needed) --

    def test_preview_returns_the_computed_amount(self, api):
        factories.DiscountFactory(code="SOFT10", value=10)
        response = api.post(
            "/api/v1/discounts/validate", {"code": "soft10", "subtotal": "200"}, format="json"
        )
        assert response.status_code == 200
        assert response.data["code"] == "SOFT10"
        assert float(response.data["amount"]) == 20.0

    def test_preview_rejects_unknown_and_min_spend(self, api):
        factories.DiscountFactory(code="BIG", kind="fixed", value=15, min_spend=500)
        unknown = api.post(
            "/api/v1/discounts/validate", {"code": "NOPE", "subtotal": "200"}, format="json"
        )
        assert unknown.status_code == 400
        low = api.post(
            "/api/v1/discounts/validate", {"code": "BIG", "subtotal": "100"}, format="json"
        )
        assert low.status_code == 400
        assert "Spend" in low.data["detail"]


@pytest.mark.django_db
class TestCheckout:
    def test_places_an_order_and_decrements_stock(self, api, variant, checkout_payload):
        token = add_to_cart(api, variant, 3).data["token"]
        response = api.post(
            "/api/v1/checkout/", checkout_payload, format="json",
            HTTP_X_CART_TOKEN=str(token),
        )
        assert response.status_code == 201, response.data
        assert response.data["number"].startswith("LH-")
        assert response.data["payment_status"] == "paid"
        assert response.data["payment"]["client_secret"]

        variant.refresh_from_db()
        assert variant.stock_quantity == 7

    def test_order_items_snapshot_the_product(self, api, variant, checkout_payload):
        token = add_to_cart(api, variant, 1).data["token"]
        api.post("/api/v1/checkout/", checkout_payload, format="json", HTTP_X_CART_TOKEN=str(token))
        item = Order.objects.get().items.get()
        assert item.product_name == "The Cloud Jumper"
        assert item.colour_name == "Oat"
        assert item.sku == variant.sku
        assert float(item.unit_price) == 100.0

    def test_totals_include_shipping_below_the_threshold(self, api, variant, checkout_payload):
        variant.colour.product.base_price = 20
        variant.colour.product.save()
        token = add_to_cart(api, variant, 1).data["token"]
        response = api.post(
            "/api/v1/checkout/", checkout_payload, format="json", HTTP_X_CART_TOKEN=str(token)
        )
        assert float(response.data["shipping_total"]) == 3.95
        assert float(response.data["grand_total"]) == 23.95

    def test_the_cart_is_emptied(self, api, variant, checkout_payload):
        token = add_to_cart(api, variant, 1).data["token"]
        api.post("/api/v1/checkout/", checkout_payload, format="json", HTTP_X_CART_TOKEN=str(token))
        cart = Cart.objects.get(token=token)
        assert cart.items.count() == 0
        assert cart.is_active is False

    def test_empty_cart_is_rejected(self, api, db, checkout_payload):
        response = api.post("/api/v1/checkout/", checkout_payload, format="json")
        assert response.status_code == 400
        assert response.data["code"] == "empty_cart"

    def test_cannot_oversell_when_stock_drops_after_adding(self, api, variant, checkout_payload):
        """Stock is re-checked under lock at checkout, not just at add-to-bag."""
        token = add_to_cart(api, variant, 5).data["token"]
        variant.stock_quantity = 2
        variant.save()

        response = api.post(
            "/api/v1/checkout/", checkout_payload, format="json", HTTP_X_CART_TOKEN=str(token)
        )
        assert response.status_code == 400
        assert response.data["code"] == "out_of_stock"
        variant.refresh_from_db()
        assert variant.stock_quantity == 2  # untouched
        assert Order.objects.count() == 0

    def test_two_checkouts_cannot_both_take_the_last_item(self, api, variant, checkout_payload):
        variant.stock_quantity = 1
        variant.save()

        first_token = add_to_cart(api, variant, 1).data["token"]
        second = type(api)()
        second_token = add_to_cart(second, variant, 1).data["token"]

        ok = api.post(
            "/api/v1/checkout/", checkout_payload, format="json",
            HTTP_X_CART_TOKEN=str(first_token),
        )
        clash = second.post(
            "/api/v1/checkout/", checkout_payload, format="json",
            HTTP_X_CART_TOKEN=str(second_token),
        )
        assert ok.status_code == 201
        assert clash.status_code == 400
        variant.refresh_from_db()
        assert variant.stock_quantity == 0

    def test_discount_carries_through_to_the_order(self, api, variant, checkout_payload):
        discount = factories.DiscountFactory(code="SOFT10", value=10)
        token = add_to_cart(api, variant, 1).data["token"]
        api.post("/api/v1/cart/apply-discount/", {"code": "SOFT10"}, format="json",
                 HTTP_X_CART_TOKEN=str(token))
        response = api.post(
            "/api/v1/checkout/", checkout_payload, format="json", HTTP_X_CART_TOKEN=str(token)
        )
        assert float(response.data["discount_total"]) == 10.0
        assert response.data["discount_code"] == "SOFT10"
        discount.refresh_from_db()
        assert discount.used_count == 1


@pytest.mark.django_db
class TestOrderLifecycle:
    def test_cancelling_restocks_once(self, api, variant, checkout_payload):
        from apps.orders.services import cancel_order

        token = add_to_cart(api, variant, 4).data["token"]
        api.post("/api/v1/checkout/", checkout_payload, format="json", HTTP_X_CART_TOKEN=str(token))
        variant.refresh_from_db()
        assert variant.stock_quantity == 6

        order = Order.objects.get()
        cancel_order(order)
        variant.refresh_from_db()
        assert variant.stock_quantity == 10

        cancel_order(order)  # idempotent
        variant.refresh_from_db()
        assert variant.stock_quantity == 10

    def test_guest_order_lookup(self, api, variant, checkout_payload):
        token = add_to_cart(api, variant, 1).data["token"]
        created = api.post(
            "/api/v1/checkout/", checkout_payload, format="json", HTTP_X_CART_TOKEN=str(token)
        )
        number = created.data["number"]
        response = api.get(f"/api/v1/orders/lookup/?number={number}&email=shopper@example.com")
        assert response.status_code == 200
        assert response.data["number"] == number

    def test_lookup_with_the_wrong_email_is_404(self, api, variant, checkout_payload):
        token = add_to_cart(api, variant, 1).data["token"]
        number = api.post(
            "/api/v1/checkout/", checkout_payload, format="json", HTTP_X_CART_TOKEN=str(token)
        ).data["number"]
        response = api.get(f"/api/v1/orders/lookup/?number={number}&email=wrong@example.com")
        assert response.status_code == 404
