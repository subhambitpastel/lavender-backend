import pytest

from apps.cart.models import Cart
from tests import factories


def register_payload(**overrides):
    """A complete, valid sign-up body — the profile fields are all required now."""
    data = {
        "email": "new@example.com",
        "password": "a-strong-passphrase-42",
        "first_name": "New",
        "last_name": "Customer",
        "phone": "+44 7911 123456",
        "location": "London",
        "postcode": "SW1A 1AA",
        "country": "GB",
    }
    data.update(overrides)
    return data


@pytest.mark.django_db
class TestAuth:
    def test_register_returns_tokens_and_the_user(self, api):
        response = api.post("/api/v1/auth/register", register_payload(), format="json")
        assert response.status_code == 201
        assert response.data["access"]
        user = response.data["user"]
        assert user["email"] == "new@example.com"
        assert user["location"] == "London"
        assert user["postcode"] == "SW1A 1AA"
        assert user["country"] == "GB"
        # Phone is validated and stored canonicalised (E.164), spaces stripped.
        assert user["phone"] == "+447911123456"

    def test_register_rejects_an_impossible_phone(self, api):
        # Parses as a GB number but is too short to be valid.
        response = api.post(
            "/api/v1/auth/register", register_payload(phone="+44 123"), format="json"
        )
        assert response.status_code == 400
        assert "phone" in response.data

    def test_register_requires_the_profile_fields(self, api):
        # Missing phone / location / postcode / country.
        response = api.post(
            "/api/v1/auth/register",
            {
                "email": "bare@example.com",
                "password": "a-strong-passphrase-42",
                "first_name": "Bare",
                "last_name": "Bones",
            },
            format="json",
        )
        assert response.status_code == 400
        assert {"phone", "location", "postcode", "country"} <= set(response.data)

    @pytest.mark.parametrize(
        "field,value",
        [
            ("phone", "not-a-phone"),
            ("postcode", "!!"),
            ("country", "ZZ"),   # not in the whitelist
        ],
    )
    def test_register_validates_each_field(self, api, field, value):
        response = api.post(
            "/api/v1/auth/register", register_payload(**{field: value}), format="json"
        )
        assert response.status_code == 400
        assert field in response.data

    def test_duplicate_email_is_rejected(self, api, user):
        response = api.post(
            "/api/v1/auth/register",
            {"email": user.email, "password": "a-strong-passphrase-42"},
            format="json",
        )
        assert response.status_code == 400

    def test_weak_password_is_rejected(self, api):
        response = api.post(
            "/api/v1/auth/register", {"email": "x@example.com", "password": "123"}, format="json"
        )
        assert response.status_code == 400

    def test_login_with_email(self, api, user):
        response = api.post(
            "/api/v1/auth/login",
            {"email": user.email, "password": "testpass123"},
            format="json",
        )
        assert response.status_code == 200
        assert response.data["user"]["email"] == user.email

    def test_bad_credentials_are_rejected(self, api, user):
        response = api.post(
            "/api/v1/auth/login", {"email": user.email, "password": "wrong"}, format="json"
        )
        assert response.status_code == 401

    def test_me_requires_auth(self, api):
        assert api.get("/api/v1/auth/me").status_code == 401

    def test_me_returns_and_updates_the_profile(self, auth_api, user):
        assert auth_api.get("/api/v1/auth/me").data["email"] == user.email
        response = auth_api.patch(
            "/api/v1/auth/me",
            {"first_name": "Updated", "location": "Bristol", "postcode": "BS1 4DJ", "country": "IE"},
            format="json",
        )
        assert response.status_code == 200
        assert response.data["first_name"] == "Updated"
        assert response.data["location"] == "Bristol"
        assert response.data["country"] == "IE"

    def test_me_cannot_change_email(self, auth_api, user):
        response = auth_api.patch(
            "/api/v1/auth/me", {"email": "hacker@example.com"}, format="json"
        )
        assert response.status_code == 200
        assert response.data["email"] == user.email      # unchanged — email is read-only
        user.refresh_from_db()
        assert user.email == response.data["email"]

    def test_me_rejects_an_invalid_country_on_edit(self, auth_api):
        response = auth_api.patch("/api/v1/auth/me", {"country": "ZZ"}, format="json")
        assert response.status_code == 400
        assert "country" in response.data

    def test_password_reset_never_leaks_whether_the_email_exists(self, api, user):
        known = api.post("/api/v1/auth/password/reset", {"email": user.email}, format="json")
        unknown = api.post(
            "/api/v1/auth/password/reset", {"email": "ghost@example.com"}, format="json"
        )
        assert known.status_code == unknown.status_code == 200


@pytest.mark.django_db
class TestCartMerge:
    def test_guest_cart_folds_into_the_account_on_login(self, api, variant, user):
        guest = api.post(
            "/api/v1/cart/items/", {"variant_id": variant.pk, "quantity": 2}, format="json"
        )
        token = guest.data["token"]

        api.post(
            "/api/v1/auth/login",
            {"email": user.email, "password": "testpass123"},
            format="json",
            HTTP_X_CART_TOKEN=str(token),
        )
        cart = Cart.objects.get(user=user)
        assert cart.items.get().quantity == 2


@pytest.mark.django_db
class TestAddresses:
    def test_addresses_are_scoped_to_the_user(self, auth_api, user):
        payload = {
            "first_name": "Eleanor", "last_name": "Reid", "line1": "12 Lavender Hill",
            "city": "London", "postcode": "SW11 5RW", "country": "GB",
        }
        created = auth_api.post("/api/v1/addresses/", payload, format="json")
        assert created.status_code == 201

        other = factories.UserFactory(email="other@example.com")
        from apps.accounts.models import Address
        Address.objects.create(user=other, **payload)

        listed = auth_api.get("/api/v1/addresses/")
        assert len(listed.data) == 1

    def test_addresses_require_auth(self, api):
        assert api.get("/api/v1/addresses/").status_code == 401

    def test_only_one_default_shipping_address(self, auth_api, user):
        from apps.accounts.models import Address

        base = {
            "first_name": "E", "last_name": "R", "line1": "1 A St",
            "city": "London", "postcode": "N1 1AA",
        }
        first = Address.objects.create(user=user, is_default_shipping=True, **base)
        Address.objects.create(user=user, is_default_shipping=True, **base)
        first.refresh_from_db()
        assert first.is_default_shipping is False


@pytest.mark.django_db
class TestWishlist:
    def test_add_list_and_remove(self, auth_api, product):
        added = auth_api.post("/api/v1/wishlist/", {"product": product.slug}, format="json")
        assert added.status_code == 201

        listed = auth_api.get("/api/v1/wishlist/")
        assert listed.data[0]["product"]["slug"] == product.slug

        removed = auth_api.delete(f"/api/v1/wishlist/{product.slug}/")
        assert removed.status_code == 204
        assert auth_api.get("/api/v1/wishlist/").data == []

    def test_adding_twice_is_idempotent(self, auth_api, product):
        auth_api.post("/api/v1/wishlist/", {"product": product.slug}, format="json")
        again = auth_api.post("/api/v1/wishlist/", {"product": product.slug}, format="json")
        assert again.status_code == 200
        assert len(auth_api.get("/api/v1/wishlist/").data) == 1

    def test_wishlist_requires_auth(self, api):
        assert api.get("/api/v1/wishlist/").status_code == 401


@pytest.mark.django_db
class TestOrderHistory:
    def test_only_your_own_orders_are_listed(self, auth_api, api, user, variant, checkout_payload):
        from apps.orders.models import Order

        Order.objects.create(email="someone@example.com")
        mine = Order.objects.create(email=user.email, user=user)

        response = auth_api.get("/api/v1/orders/")
        numbers = [o["number"] for o in response.data["results"]]
        assert numbers == [mine.number]

    def test_delivered_at_and_reviewed_flag_surface_in_history(self, auth_api, user, product):
        from apps.orders.models import Order, OrderItem
        from apps.catalog.models import Review

        order = Order.objects.create(
            user=user, email=user.email, status=Order.Status.DELIVERED
        )
        OrderItem.objects.create(
            order=order, product_slug=product.slug, product_name=product.name,
            unit_price=10, quantity=1, line_total=10,
        )
        order.refresh_from_db()
        assert order.delivered_at is not None  # stamped on save when delivered

        data = auth_api.get("/api/v1/orders/").data["results"][0]
        assert data["delivered_at"] is not None
        assert data["items"][0]["reviewed"] is False

        Review.objects.create(
            product=product, user=user, author_name="X", rating=5, body="Great",
            is_verified=True, is_approved=True,
        )
        again = auth_api.get("/api/v1/orders/").data["results"][0]
        assert again["items"][0]["reviewed"] is True
