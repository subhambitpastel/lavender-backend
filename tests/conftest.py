import pytest
from rest_framework.test import APIClient

from tests import factories


@pytest.fixture
def api():
    return APIClient()


@pytest.fixture
def sizes(db):
    return [
        factories.SizeFactory(name=name, sort_order=order)
        for order, name in enumerate(["XS", "S", "M", "L"])
    ]


@pytest.fixture
def product(db, sizes):
    """One product, one colour, one variant per size, 10 units each."""
    product = factories.ProductFactory(name="The Cloud Jumper", base_price=100)
    colour = factories.ProductColourFactory(product=product, name="Oat")
    for size in sizes:
        factories.ProductVariantFactory(colour=colour, size=size, stock_quantity=10)
    return product


@pytest.fixture
def variant(product):
    return product.colours.first().variants.first()


@pytest.fixture
def user(db):
    return factories.UserFactory(email="shopper@example.com", password="testpass123")


@pytest.fixture
def staff(db):
    return factories.StaffFactory(email="staff@example.com", password="testpass123")


@pytest.fixture
def auth_api(api, user):
    from rest_framework_simplejwt.tokens import RefreshToken

    token = RefreshToken.for_user(user).access_token
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return api


@pytest.fixture
def checkout_payload():
    return {
        "contact": {"email": "shopper@example.com", "phone": "07700 900000"},
        "shipping": {
            "first_name": "Eleanor",
            "last_name": "Reid",
            "line1": "12 Lavender Hill",
            "city": "London",
            "postcode": "SW11 5RW",
            "country": "GB",
        },
        "shipping_method": "standard",
    }
