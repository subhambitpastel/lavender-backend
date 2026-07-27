"""Stock rules and derived model properties — the single source of truth."""

import pytest

from tests import factories


@pytest.mark.django_db
class TestStock:
    def test_colour_stock_is_the_sum_of_its_variants(self, product):
        colour = product.colours.first()
        assert colour.stock == 40  # 4 sizes × 10

    def test_inactive_variants_are_excluded_from_colour_stock(self, product):
        colour = product.colours.first()
        variant = colour.variants.first()
        variant.is_active = False
        variant.save()
        assert colour.stock == 30

    def test_product_in_stock_when_any_variant_has_stock(self, product):
        assert product.in_stock is True

    def test_product_out_of_stock_when_every_variant_is_empty(self, product):
        product.colours.first().variants.update(stock_quantity=0)
        product = type(product).objects.prefetch_related("colours__variants").get(pk=product.pk)
        assert product.in_stock is False

    def test_total_stock_spans_colours(self, product, sizes):
        second = factories.ProductColourFactory(product=product, name="Slate")
        factories.ProductVariantFactory(colour=second, size=sizes[0], stock_quantity=5)
        assert product.total_stock == 45

    def test_variant_in_stock_needs_both_active_and_quantity(self, variant):
        assert variant.in_stock is True
        variant.stock_quantity = 0
        assert variant.in_stock is False


@pytest.mark.django_db
class TestPricing:
    def test_on_sale_requires_a_higher_compare_at_price(self, product):
        assert product.on_sale is False
        product.compare_at_price = 150
        assert product.on_sale is True
        assert product.discount_percent == 33

    def test_badge_prefers_sale_over_new_in(self, product):
        product.is_new_in = True
        assert product.badge == "New in"
        product.compare_at_price = 150
        assert product.badge == "Sale"

    def test_variant_price_falls_back_to_the_product(self, variant):
        assert variant.price == 100
        variant.price_override = 80
        assert variant.price == 80


@pytest.mark.django_db
class TestSku:
    def test_sku_is_generated_and_unique(self, product, sizes):
        colour = product.colours.first()
        skus = [v.sku for v in colour.variants.all()]
        assert all(sku.startswith("LH-") for sku in skus)
        assert len(set(skus)) == len(skus)


@pytest.mark.django_db
class TestReviews:
    def test_approving_a_review_recomputes_the_product_rating(self, product):
        factories.ReviewFactory(product=product, rating=5, is_approved=True)
        factories.ReviewFactory(product=product, rating=3, is_approved=True)
        product.refresh_from_db()
        assert float(product.rating_avg) == 4.0
        assert product.review_count == 2

    def test_unapproved_reviews_do_not_count(self, product):
        factories.ReviewFactory(product=product, rating=1, is_approved=False)
        product.refresh_from_db()
        assert product.review_count == 0

    def test_deleting_a_review_recomputes(self, product):
        review = factories.ReviewFactory(product=product, rating=5, is_approved=True)
        review.delete()
        product.refresh_from_db()
        assert product.review_count == 0


@pytest.mark.django_db
class TestOrderNumber:
    def test_numbers_increment(self):
        from apps.orders.models import Order

        first = Order.objects.create(email="a@example.com")
        second = Order.objects.create(email="b@example.com")
        assert first.number.startswith("LH-")
        assert int(second.number.split("-")[-1]) == int(first.number.split("-")[-1]) + 1
