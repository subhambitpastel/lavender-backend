"""Dashboard permission gating and the product-editor save paths."""

import io
import re

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image

from apps.catalog.models import Product, ProductColour, ProductVariant
from tests import factories


def _upload(name):
    """A tiny real JPEG — ImageField refuses anything that isn't decodable."""
    buffer = io.BytesIO()
    Image.new("RGB", (10, 10), "white").save(buffer, "JPEG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/jpeg")

PROTECTED = [
    "dashboard:home",
    "dashboard:product_list",
    "dashboard:inventory",
    "dashboard:order_list",
    "dashboard:customer_list",
    "dashboard:discount_list",
    "dashboard:review_list",
    "dashboard:journal_list",
    "dashboard:content_settings",
    "dashboard:newsletter_list",
    "dashboard:category_list",
]


@pytest.mark.django_db
class TestAccessControl:
    @pytest.mark.parametrize("name", PROTECTED)
    def test_anonymous_is_redirected_to_login(self, client, name):
        response = client.get(reverse(name))
        assert response.status_code == 302
        assert "/dashboard/login/" in response["Location"]

    def test_a_signed_in_customer_is_not_staff(self, client, user):
        client.force_login(user)
        response = client.get(reverse("dashboard:product_list"))
        assert response.status_code == 302

    @pytest.mark.parametrize("name", PROTECTED)
    def test_staff_can_reach_every_screen(self, client, staff, name):
        client.force_login(staff)
        assert client.get(reverse(name)).status_code == 200

    def test_login_page_rejects_non_staff(self, client, user):
        response = client.post(
            reverse("dashboard:login"),
            {"email": user.email, "password": "testpass123"},
            follow=True,
        )
        assert b"doesn&#x27;t have dashboard access" in response.content or response.status_code == 200
        assert not response.context["user"].is_staff

    def test_staff_can_sign_in(self, client, staff):
        response = client.post(
            reverse("dashboard:login"),
            {"email": staff.email, "password": "testpass123"},
        )
        assert response.status_code == 302
        assert response["Location"] == reverse("dashboard:home")


@pytest.mark.django_db
class TestProductEditor:
    def test_creating_a_product_with_a_colour_row(self, client, staff, db):
        client.force_login(staff)
        category = factories.CategoryFactory(name="Knitwear")

        response = client.post(
            reverse("dashboard:product_create"),
            {
                "name": "Editor Jumper",
                "slug": "",
                "description": "Made in the editor.",
                "category": category.pk,
                "base_price": "150.00",
                "currency": "GBP",
                "sort_order": 0,
                "is_active": "on",
                "colours-TOTAL_FORMS": "1",
                "colours-INITIAL_FORMS": "0",
                "colours-MIN_NUM_FORMS": "0",
                "colours-MAX_NUM_FORMS": "1000",
                "colours-0-name": "Oat Melange",
                "colours-0-swatch_hex": "#DCD3C6",
                "colours-0-sort_order": "0",
                "colours-0-is_active": "on",
            },
        )
        assert response.status_code == 302
        colour = ProductColour.objects.get(name="Oat Melange")
        assert colour.product.slug == "editor-jumper"

    def test_compare_at_price_must_beat_the_price(self, client, staff, db):
        client.force_login(staff)
        category = factories.CategoryFactory(name="Knitwear")
        response = client.post(
            reverse("dashboard:product_create"),
            {
                "name": "Bad Pricing", "slug": "", "description": "",
                "category": category.pk, "base_price": "150.00",
                "compare_at_price": "100.00", "currency": "GBP", "sort_order": 0,
                "colours-TOTAL_FORMS": "0", "colours-INITIAL_FORMS": "0",
                "colours-MIN_NUM_FORMS": "0", "colours-MAX_NUM_FORMS": "1000",
            },
        )
        assert response.status_code == 200
        assert b"must be higher" in response.content

    def test_blank_spare_colour_row_is_not_mandatory(self, client, staff, db):
        """The spare row must not block the save just because it was rendered.

        A ``type="color"`` input always posts a value and lowercases it, which
        used to make the untouched row look edited — and then fail on its name.
        """
        client.force_login(staff)
        category = factories.CategoryFactory(name="Knitwear")

        response = client.post(
            reverse("dashboard:product_create"),
            {
                "name": "No Colour Yet", "slug": "", "description": "",
                "category": category.pk, "base_price": "80.00",
                "currency": "GBP", "sort_order": 0, "is_active": "on",
                "colours-TOTAL_FORMS": "1", "colours-INITIAL_FORMS": "0",
                "colours-MIN_NUM_FORMS": "0", "colours-MAX_NUM_FORMS": "1000",
                "colours-0-name": "",
                "colours-0-swatch_hex": "#dcd3c6",   # browser lowercases the default
                "colours-0-sort_order": "0", "colours-0-is_active": "on",
            },
        )
        assert response.status_code == 302
        product = Product.objects.get(name="No Colour Yet")
        assert product.slug == "no-colour-yet"
        assert product.colours.count() == 0

    def test_every_error_is_reported_at_once_under_its_own_field(
        self, client, staff, db
    ):
        """All problems at once, each beside the input that caused it.

        The form is submitted with `novalidate` so the browser can't stop at the
        first required field with its own one-at-a-time bubble — Django gets to
        validate everything and render each error inline.
        """
        client.force_login(staff)

        page = client.get(reverse("dashboard:product_create")).content.decode()
        assert "novalidate" in page, "browser validation would pre-empt the server's"

        response = client.post(
            reverse("dashboard:product_create"),
            {
                "name": "", "slug": "", "description": "",     # required
                "category": "", "base_price": "",              # required
                "currency": "GBP", "sort_order": 0,
                "colours-TOTAL_FORMS": "0", "colours-INITIAL_FORMS": "0",
                "colours-MIN_NUM_FORMS": "0", "colours-MAX_NUM_FORMS": "1000",
            },
        )
        html = response.content.decode()
        assert response.status_code == 200

        # Each field carries its own message, not just a lump at the top.
        for field in ("name", "category", "base_price"):
            block = re.search(r'id="field-%s".{0,900}?</label>' % field, html, re.S)
            assert block, f"no wrapper rendered for {field}"
            assert "field__error" in block.group(0), f"{field} has no inline error"

        # ...and the summary lists them together, with an anchor to scroll to.
        assert "data-error-summary" in html
        assert html.count("field__error") >= 3

    def test_required_fields_are_starred_optional_ones_are_not(
        self, client, staff, db
    ):
        """Mandatory fields wear a red * beside their label; optional ones don't.

        The marker is driven off ``field.field.required``, so it always tracks
        what the form actually enforces — no hand-maintained list to drift.
        """
        client.force_login(staff)
        html = client.get(reverse("dashboard:product_create")).content.decode()

        def label_of(name):
            block = re.search(r'id="field-%s".{0,400}?</span>' % name, html, re.S)
            assert block, f"no label rendered for {name}"
            return block.group(0)

        # Required by the model → marked.
        for name in ("name", "category", "base_price"):
            assert 'class="req"' in label_of(name), f"{name} should be starred"

        # Optional (blank=True, or forced optional) → not marked.
        for name in ("slug", "description", "compare_at_price"):
            assert 'class="req"' not in label_of(name), f"{name} must not be starred"

    def test_stock_without_a_colour_name_is_refused_not_dropped(
        self, client, staff, db, sizes
    ):
        """Stock typed into an unnamed row must not vanish on save.

        Stock posts outside the formset's fields, so an unnamed row looked
        untouched and everything entered was silently discarded — the product
        saved "successfully" with no stock at all.
        """
        client.force_login(staff)
        category = factories.CategoryFactory(name="Knitwear")

        response = client.post(
            reverse("dashboard:product_create"),
            {
                "name": "Nameless Colour", "slug": "", "description": "",
                "category": category.pk, "base_price": "20.00",
                "currency": "GBP", "sort_order": 0, "is_active": "on",
                "colours-TOTAL_FORMS": "1", "colours-INITIAL_FORMS": "0",
                "colours-MIN_NUM_FORMS": "0", "colours-MAX_NUM_FORMS": "1000",
                "colours-0-name": "",                       # left blank...
                "colours-0-swatch_hex": "#dcd3c6",
                "colours-0-sort_order": "0", "colours-0-is_active": "on",
                f"colours-0-stock_{sizes[0].pk}": "25",     # ...but stock entered
                f"colours-0-active_{sizes[0].pk}": "on",
            },
        )
        assert response.status_code == 200
        assert b"Name this colour" in response.content
        assert not Product.objects.filter(name="Nameless Colour").exists()

    def test_adding_a_product_sets_colour_images_and_stock_in_one_go(
        self, client, staff, db, sizes
    ):
        """Images and stock are available while *adding*, not only when editing."""
        client.force_login(staff)
        category = factories.CategoryFactory(name="Knitwear")

        response = client.post(
            reverse("dashboard:product_create"),
            {
                "name": "Full Add", "slug": "", "description": "",
                "category": category.pk, "base_price": "120.00",
                "currency": "GBP", "sort_order": 0, "is_active": "on",
                "colours-TOTAL_FORMS": "1", "colours-INITIAL_FORMS": "0",
                "colours-MIN_NUM_FORMS": "0", "colours-MAX_NUM_FORMS": "1000",
                "colours-0-name": "Slate", "colours-0-swatch_hex": "#6F7169",
                "colours-0-sort_order": "0", "colours-0-is_active": "on",
                f"colours-0-stock_{sizes[0].pk}": "9",
                f"colours-0-active_{sizes[0].pk}": "on",
                "colours-0-images": _upload("shot.jpg"),
            },
        )
        assert response.status_code == 302

        colour = ProductColour.objects.get(name="Slate")
        assert colour.images.count() == 1
        assert colour.images.first().is_primary
        assert colour.variants.get(size=sizes[0]).stock_quantity == 9

    def test_stock_grid_creates_updates_and_removes_variants(self, client, staff, product, sizes):
        client.force_login(staff)
        colour = product.colours.first()

        response = client.post(
            reverse("dashboard:colour_stock_save", args=[colour.pk]),
            {
                f"stock_{sizes[0].pk}": "25",
                f"active_{sizes[0].pk}": "on",
                f"stock_{sizes[1].pk}": "0",
                f"active_{sizes[1].pk}": "on",
                f"stock_{sizes[2].pk}": "",          # blank → stop offering this size
                f"stock_{sizes[3].pk}": "7",
                f"active_{sizes[3].pk}": "on",
                f"price_{sizes[3].pk}": "120.00",
            },
        )
        assert response.status_code == 200

        variants = {v.size.name: v for v in colour.variants.select_related("size")}
        assert variants["XS"].stock_quantity == 25
        assert variants["S"].stock_quantity == 0
        assert "M" not in variants
        assert float(variants["L"].price_override) == 120.0
        assert colour.stock == 32

    def test_image_upload_is_incremental_not_all_at_once(self, client, staff, product):
        """Each pick appends to the colour, so images don't have to go up together."""
        client.force_login(staff)
        colour = product.colours.first()
        colour.images.all().delete()
        url = reverse("dashboard:colour_images_upload", args=[colour.pk])

        first = client.post(url, {"images": _upload("one.jpg")})
        assert first.status_code == 200
        assert colour.images.count() == 1

        second = client.post(url, {"images": _upload("two.jpg")})
        assert second.status_code == 200
        assert colour.images.count() == 2            # appended, not replaced
        assert b"imagestrip" in second.content        # refreshed strip returned

    def test_images_can_be_reordered(self, client, staff, product):
        """Posting a new id order rewrites sort_order, so the gallery follows it."""
        client.force_login(staff)
        colour = product.colours.first()
        colour.images.all().delete()
        upload = reverse("dashboard:colour_images_upload", args=[colour.pk])
        for name in ("a.jpg", "b.jpg", "c.jpg"):
            client.post(upload, {"images": _upload(name)})

        ordered = list(colour.images.order_by("sort_order", "id"))
        reversed_ids = [i.pk for i in reversed(ordered)]

        response = client.post(
            reverse("dashboard:colour_images_reorder", args=[colour.pk]),
            {"order": ",".join(str(pk) for pk in reversed_ids)},
        )
        assert response.status_code == 200
        again = [i.pk for i in colour.images.order_by("sort_order", "id")]
        assert again == reversed_ids

    def test_a_colour_never_stores_more_than_eight_images(self, client, staff, product):
        """The per-colour cap holds server-side even if a client sends more."""
        client.force_login(staff)
        colour = product.colours.first()
        colour.images.all().delete()

        response = client.post(
            reverse("dashboard:colour_images_upload", args=[colour.pk]),
            {"images": [_upload(f"{i}.jpg") for i in range(11)]},
        )
        assert response.status_code == 200
        assert colour.images.count() == 8            # capped, not 11

        # Adding more once full is a no-op rather than an overflow.
        client.post(
            reverse("dashboard:colour_images_upload", args=[colour.pk]),
            {"images": [_upload("extra.jpg")]},
        )
        assert colour.images.count() == 8

    def test_a_validation_error_keeps_typed_stock_and_colour(
        self, client, staff, db, sizes
    ):
        """A failed save redraws the grid from what was typed, not the DB.

        Previously a missing price wiped the whole colour panel; the admin lost
        every stock number they had entered.
        """
        client.force_login(staff)
        category = factories.CategoryFactory(name="Dresses")

        response = client.post(
            reverse("dashboard:product_create"),
            {
                "name": "Keep Me", "slug": "", "description": "",
                "category": category.pk, "base_price": "",   # <- triggers the error
                "currency": "GBP", "sort_order": 0, "is_active": "on",
                "colours-TOTAL_FORMS": "1", "colours-INITIAL_FORMS": "0",
                "colours-MIN_NUM_FORMS": "0", "colours-MAX_NUM_FORMS": "1000",
                "colours-0-name": "Blush", "colours-0-swatch_hex": "#eeccdd",
                "colours-0-sort_order": "0", "colours-0-is_active": "on",
                f"colours-0-stock_{sizes[0].pk}": "15",
                f"colours-0-active_{sizes[0].pk}": "on",
            },
        )
        assert response.status_code == 200
        html = response.content.decode()
        assert re.search(
            r'name="colours-0-stock_%d"[^>]*value="15"' % sizes[0].pk, html
        ), "typed stock was wiped on the error re-render"
        assert 'value="Blush"' in html, "colour name was wiped on the error re-render"
        assert not Product.objects.filter(name="Keep Me").exists()

    def test_editing_a_colour_appends_images_on_a_plain_save(
        self, client, staff, product
    ):
        """Adding images to an existing colour works from a normal form save.

        The "add images" input is named, so images upload even when the browser's
        JavaScript is stale or disabled — the failure the manager originally hid.
        """
        client.force_login(staff)
        colour = product.colours.first()
        colour.images.all().delete()
        colour.images.create(image=_upload("existing.jpg"), sort_order=0, is_primary=True)

        response = client.post(
            reverse("dashboard:product_edit", args=[product.pk]),
            {
                "name": product.name, "slug": product.slug,
                "description": product.description or "x",
                "category": product.category_id, "base_price": str(product.base_price),
                "currency": product.currency, "sort_order": "0", "is_active": "on",
                "colours-TOTAL_FORMS": "1", "colours-INITIAL_FORMS": "1",
                "colours-MIN_NUM_FORMS": "0", "colours-MAX_NUM_FORMS": "1000",
                "colours-0-id": str(colour.pk), "colours-0-name": colour.name,
                "colours-0-swatch_hex": colour.swatch_hex,
                "colours-0-sort_order": "0", "colours-0-is_active": "on",
                "colours-0-images": _upload("added.jpg"),
            },
        )
        assert response.status_code == 302
        assert colour.images.count() == 2          # existing kept, new one appended

    def test_inventory_bulk_add_is_added_not_set(self, client, staff, product):
        client.force_login(staff)
        variant = product.colours.first().variants.first()
        start = variant.stock_quantity  # seeded at 10
        client.post(reverse("dashboard:inventory_bulk"), {f"add_{variant.pk}": "42"})
        variant.refresh_from_db()
        assert variant.stock_quantity == start + 42  # added, not overwritten

    def test_inventory_bulk_negative_writes_off_but_not_below_zero(self, client, staff, product):
        client.force_login(staff)
        variant = product.colours.first().variants.first()
        client.post(reverse("dashboard:inventory_bulk"), {f"add_{variant.pk}": "-999"})
        variant.refresh_from_db()
        assert variant.stock_quantity == 0

    def test_inventory_blank_add_leaves_stock_untouched(self, client, staff, product):
        client.force_login(staff)
        variant = product.colours.first().variants.first()
        start = variant.stock_quantity
        client.post(reverse("dashboard:inventory_bulk"), {f"add_{variant.pk}": ""})
        variant.refresh_from_db()
        assert variant.stock_quantity == start

    def test_inventory_inline_add_updates_in_place(self, client, staff, product):
        client.force_login(staff)
        variant = product.colours.first().variants.first()
        start = variant.stock_quantity  # 10
        response = client.post(
            reverse("dashboard:inventory_quick", args=[variant.pk]),
            {"add": "8"},
            HTTP_HX_REQUEST="true",
        )
        variant.refresh_from_db()
        assert variant.stock_quantity == start + 8  # added, not replaced
        assert str(start + 8).encode() in response.content  # badge shows the new number

    def test_inventory_inline_add_without_htmx_redirects(self, client, staff, product):
        client.force_login(staff)
        variant = product.colours.first().variants.first()
        start = variant.stock_quantity
        response = client.post(
            reverse("dashboard:inventory_quick", args=[variant.pk]), {"add": "3"}
        )
        variant.refresh_from_db()
        assert variant.stock_quantity == start + 3
        assert response.status_code == 302

    def test_toggling_active_from_the_list(self, client, staff, product):
        client.force_login(staff)
        client.post(reverse("dashboard:product_toggle", args=[product.pk]))
        product.refresh_from_db()
        assert product.is_active is False


@pytest.mark.django_db
class TestOrderOps:
    def test_status_lifecycle_advances_and_logs(self, client, staff, db):
        from apps.orders.models import Order

        client.force_login(staff)
        order = Order.objects.create(email="x@example.com", status=Order.Status.CONFIRMED)

        # Advance through the lifecycle, with a note, recording each change.
        resp = client.post(
            reverse("dashboard:order_status", args=[order.number]),
            {"status": "fulfillment", "note": "picking now"},
        )
        assert resp.status_code == 302
        order.refresh_from_db()
        assert order.status == "fulfillment"

        client.post(reverse("dashboard:order_status", args=[order.number]), {"status": "shipped"})
        client.post(reverse("dashboard:order_status", args=[order.number]), {"status": "delivered"})
        order.refresh_from_db()
        assert order.status == "delivered"
        assert order.delivered_at is not None  # stamped on delivery

        # The activity log captured every transition (incl. the note).
        events = list(order.status_events.order_by("created_at"))
        assert [e.to_status for e in events] == ["fulfillment", "shipped", "delivered"]
        assert events[0].note == "picking now"
        assert events[0].actor == staff.email

        # Advancing to the same status, or a bogus one, is a no-op.
        client.post(reverse("dashboard:order_status", args=[order.number]), {"status": "nonsense"})
        order.refresh_from_db()
        assert order.status == "delivered"
        assert order.status_events.count() == 3

    def test_closing_a_delivered_order(self, client, staff, db):
        from apps.orders.models import Order

        client.force_login(staff)
        order = Order.objects.create(email="x@example.com", status=Order.Status.DELIVERED)
        client.post(reverse("dashboard:order_status", args=[order.number]), {"status": "closed"})
        order.refresh_from_db()
        assert order.status == "closed"

    def test_cancelling_from_the_dashboard_restocks(self, client, staff, api, variant, checkout_payload):
        token = api.post(
            "/api/v1/cart/items/", {"variant_id": variant.pk, "quantity": 3}, format="json"
        ).data["token"]
        number = api.post(
            "/api/v1/checkout/", checkout_payload, format="json", HTTP_X_CART_TOKEN=str(token)
        ).data["number"]

        variant.refresh_from_db()
        assert variant.stock_quantity == 7

        client.force_login(staff)
        client.post(reverse("dashboard:order_cancel", args=[number]))

        variant.refresh_from_db()
        assert variant.stock_quantity == 10

    def test_review_approval_updates_the_rating(self, client, staff, product):
        review = factories.ReviewFactory(product=product, rating=4, is_approved=False)
        client.force_login(staff)
        client.post(reverse("dashboard:review_moderate", args=[review.pk, "approve"]))
        product.refresh_from_db()
        assert product.review_count == 1
        assert float(product.rating_avg) == 4.0


@pytest.mark.django_db
class TestContentScreens:
    def test_site_settings_save(self, client, staff):
        client.force_login(staff)
        response = client.post(
            reverse("dashboard:content_settings"),
            {
                "announcement_text": "Free delivery over £75",
                "announcement_active": "on",
                "free_shipping_threshold": "75.00",
                "usp_items": "[]",
                "footer_links": "[]",
                "faqs": "[]",
                "contact_email": "hello@example.com",
                "currency": "GBP",
            },
        )
        assert response.status_code == 302

        from apps.marketing.models import SiteSettings
        assert SiteSettings.load().announcement_text == "Free delivery over £75"

    def test_newsletter_csv_export(self, client, staff, db):
        from apps.marketing.models import NewsletterSubscriber

        NewsletterSubscriber.objects.create(email="a@example.com")
        client.force_login(staff)
        response = client.get(reverse("dashboard:newsletter_export"))
        assert response.status_code == 200
        assert response["Content-Type"] == "text/csv"
        assert b"a@example.com" in response.content
