from decimal import Decimal

import pytest

from tests import factories


@pytest.mark.django_db
class TestProductList:
    def test_lists_only_active_products(self, api, product):
        factories.ProductFactory(name="Hidden", is_active=False)
        response = api.get("/api/v1/products/")
        assert response.status_code == 200
        names = [p["name"] for p in response.data["results"]]
        assert product.name in names
        assert "Hidden" not in names

    def test_card_shape_matches_the_contract(self, api, product):
        response = api.get("/api/v1/products/")
        card = response.data["results"][0]
        for field in (
            "slug", "name", "price", "compare_at_price", "on_sale", "badge",
            "rating_avg", "review_count", "primary_image", "colours",
        ):
            assert field in card, field
        assert card["colours"][0]["swatch_hex"] == "#DCD3C6"

    def test_pagination_defaults_to_twelve(self, api, db):
        factories.ProductFactory.create_batch(15)
        response = api.get("/api/v1/products/")
        assert len(response.data["results"]) == 12
        assert response.data["count"] == 15

    def test_filter_by_category(self, api, product):
        other = factories.ProductFactory(name="Elsewhere")
        response = api.get(f"/api/v1/products/?category={product.category.slug}")
        names = [p["name"] for p in response.data["results"]]
        assert product.name in names
        assert other.name not in names

    def test_filter_on_sale(self, api, product):
        sale = factories.ProductFactory(name="Reduced", base_price=50, compare_at_price=80)
        response = api.get("/api/v1/products/?on_sale=true")
        names = [p["name"] for p in response.data["results"]]
        assert names == [sale.name]

    def test_filter_by_price_range(self, api, product):
        factories.ProductFactory(name="Pricey", base_price=500)
        response = api.get("/api/v1/products/?max_price=200")
        names = [p["name"] for p in response.data["results"]]
        assert "Pricey" not in names

    def test_filter_by_size(self, api, product, sizes):
        response = api.get(f"/api/v1/products/?size={sizes[0].name}")
        assert response.data["count"] == 1

    def test_ordering_by_price(self, api, db):
        factories.ProductFactory(name="Cheap", base_price=10)
        factories.ProductFactory(name="Dear", base_price=900)
        response = api.get("/api/v1/products/?ordering=base_price")
        assert response.data["results"][0]["name"] == "Cheap"

    def test_top_rated_breaks_ties_on_review_count(self, api, db):
        """Equal star ratings are ranked by how many reviews back them up."""
        factories.ProductFactory(name="One review", rating_avg=Decimal("5.00"), review_count=1)
        factories.ProductFactory(name="Three reviews", rating_avg=Decimal("5.00"), review_count=3)
        factories.ProductFactory(name="Lower rated", rating_avg=Decimal("4.50"), review_count=99)

        response = api.get("/api/v1/products/?ordering=-rating_avg,-review_count")
        names = [p["name"] for p in response.data["results"]]
        assert names == ["Three reviews", "One review", "Lower rated"]

    def test_search(self, api, product):
        factories.ProductFactory(name="Completely Different")
        response = api.get("/api/v1/products/?search=Cloud")
        assert response.data["count"] == 1


@pytest.mark.django_db
class TestProductDetail:
    def test_nested_colours_images_and_variants(self, api, product):
        response = api.get(f"/api/v1/products/{product.slug}/")
        assert response.status_code == 200
        colour = response.data["colours"][0]
        assert colour["name"] == "Oat"
        assert len(colour["variants"]) == 4
        variant = colour["variants"][0]
        assert {"id", "size", "sku", "stock_quantity", "in_stock", "price"} <= set(variant)
        assert colour["stock"] == 40

    def test_sizes_are_the_union_across_colours(self, api, product):
        response = api.get(f"/api/v1/products/{product.slug}/")
        assert [s["name"] for s in response.data["sizes"]] == ["XS", "S", "M", "L"]

    def test_related_products_share_the_category(self, api, product):
        factories.ProductFactory(name="Sibling", category=product.category)
        response = api.get(f"/api/v1/products/{product.slug}/")
        assert [p["name"] for p in response.data["related"]] == ["Sibling"]

    def test_missing_product_is_404(self, api, db):
        assert api.get("/api/v1/products/nope/").status_code == 404


def deliver_product_to(user, product):
    """Give ``user`` a delivered order containing ``product`` (a verified purchase)."""
    from apps.orders.models import Order, OrderItem

    order = Order.objects.create(
        user=user, email=user.email, status=Order.Status.DELIVERED
    )
    OrderItem.objects.create(
        order=order,
        product_slug=product.slug,
        product_name=product.name,
        unit_price=10,
        quantity=1,
        line_total=10,
    )
    return order


@pytest.mark.django_db
class TestReviewsEndpoint:
    def test_only_approved_reviews_are_listed(self, api, product):
        factories.ReviewFactory(product=product, body="Live one", is_approved=True)
        factories.ReviewFactory(product=product, body="Pending one", is_approved=False)
        response = api.get(f"/api/v1/products/{product.slug}/reviews/")
        bodies = [r["body"] for r in response.data["results"]]
        assert bodies == ["Live one"]

    def test_review_requires_sign_in(self, api, product):
        response = api.post(
            f"/api/v1/products/{product.slug}/reviews/",
            {"rating": 5, "body": "Lovely."},
            format="json",
        )
        assert response.status_code == 401

    def test_review_requires_a_delivered_order(self, auth_api, product):
        response = auth_api.post(
            f"/api/v1/products/{product.slug}/reviews/",
            {"rating": 5, "body": "Lovely."},
            format="json",
        )
        assert response.status_code == 403
        assert response.data["code"] == "not_delivered"

    def test_delivered_buyer_review_starts_pending_until_approved(self, auth_api, user, product):
        deliver_product_to(user, product)
        created = auth_api.post(
            f"/api/v1/products/{product.slug}/reviews/",
            {"rating": 5, "title": "Perfect", "body": "Beautiful jumper."},
            format="json",
        )
        assert created.status_code == 201
        review = product.reviews.get()
        # Verified purchase, but it enters moderation — not published, not counted.
        assert review.is_verified
        assert review.status == "pending" and not review.is_approved
        assert review.events.filter(action="submitted").exists()

        listed = auth_api.get(f"/api/v1/products/{product.slug}/reviews/")
        assert listed.data["results"] == []
        product.refresh_from_db()
        assert float(product.rating_avg) == 0.0

        # Once staff approve, it publishes and the average recomputes.
        review.status = review.Status.APPROVED
        review.is_approved = True
        review.save(update_fields=["status", "is_approved"])
        listed = auth_api.get(f"/api/v1/products/{product.slug}/reviews/")
        assert [r["body"] for r in listed.data["results"]] == ["Beautiful jumper."]
        product.refresh_from_db()
        assert float(product.rating_avg) == 5.0

    def test_resubmitting_after_rejection_returns_to_pending_and_keeps_history(
        self, auth_api, user, product
    ):
        deliver_product_to(user, product)
        auth_api.post(
            f"/api/v1/products/{product.slug}/reviews/",
            {"rating": 2, "body": "Meh."},
            format="json",
        )
        review = product.reviews.get()
        # Staff request changes.
        review.status = review.Status.REJECTED
        review.is_approved = False
        review.rejection_reason = "Please say more about the fit."
        review.save(update_fields=["status", "is_approved", "rejection_reason"])
        review.add_event("rejected", reason="Please say more about the fit.")

        # Shopper edits and resubmits.
        again = auth_api.post(
            f"/api/v1/products/{product.slug}/reviews/",
            {"rating": 4, "body": "Runs a little large but lovely."},
            format="json",
        )
        assert again.status_code == 200
        review.refresh_from_db()
        assert review.status == "pending" and review.rejection_reason == ""
        assert review.rating == 4
        # Full history preserved: submitted, rejected, resubmitted.
        assert list(review.events.values_list("action", flat=True)) == [
            "submitted",
            "rejected",
            "resubmitted",
        ]

    def test_a_second_review_edits_the_existing_one(self, auth_api, user, product):
        deliver_product_to(user, product)
        auth_api.post(
            f"/api/v1/products/{product.slug}/reviews/",
            {"rating": 3, "body": "It's fine."},
            format="json",
        )
        again = auth_api.post(
            f"/api/v1/products/{product.slug}/reviews/",
            {"rating": 5, "body": "It grew on me."},
            format="json",
        )
        assert again.status_code == 200
        assert product.reviews.count() == 1
        assert product.reviews.get().rating == 5

    def test_rating_is_validated(self, auth_api, user, product):
        deliver_product_to(user, product)
        response = auth_api.post(
            f"/api/v1/products/{product.slug}/reviews/",
            {"rating": 9, "body": "Too good."},
            format="json",
        )
        assert response.status_code == 400


@pytest.mark.django_db
class TestTaxonomyAndSearch:
    def test_categories_are_returned_as_a_tree(self, api, product):
        child = factories.CategoryFactory(name="Child")
        child.parent = product.category
        child.save()
        response = api.get("/api/v1/categories/")
        roots = [c["slug"] for c in response.data]
        assert child.slug not in roots
        parent = next(c for c in response.data if c["slug"] == product.category.slug)
        assert parent["children"][0]["slug"] == child.slug

    def test_search_endpoint(self, api, product):
        response = api.get("/api/v1/search/?q=Cloud")
        assert response.data["count"] == 1
        assert response.data["products"][0]["slug"] == product.slug

    def test_empty_search_returns_empty_lists(self, api, db):
        response = api.get("/api/v1/search/?q=")
        assert response.data["products"] == []

    def test_schema_is_generated(self, api, db):
        assert api.get("/api/v1/schema/").status_code == 200
