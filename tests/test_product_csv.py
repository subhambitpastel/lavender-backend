"""Catalogue CSV export / import — the dashboard's bulk product update."""

import csv
from decimal import Decimal
from io import BytesIO, StringIO

import pytest
from django.urls import reverse

from apps.catalog import csv_io
from apps.catalog.models import Product, ProductColour, ProductVariant
from tests import factories


def upload(text, name="products.csv", encoding="utf-8"):
    """A CSV upload as Django hands it to a view — bytes with a BOM-free encoding."""
    buffer = BytesIO(text.encode(encoding))
    buffer.name = name
    return buffer


def rows_of(text):
    return list(csv.DictReader(StringIO(text)))


def sheet(rows, columns=None):
    """Build a CSV string from dicts, using only the columns given."""
    columns = columns or list(rows[0])
    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


@pytest.mark.django_db
class TestExport:
    def test_one_row_per_variant_with_product_columns_repeated(self, product, sizes):
        text = csv_io.export_products(Product.objects.filter(pk=product.pk))
        rows = rows_of(text)

        assert len(rows) == len(sizes)  # one colour × four sizes
        assert {r["size"] for r in rows} == {s.name for s in sizes}
        assert all(r["slug"] == product.slug for r in rows)
        assert all(r["name"] == product.name for r in rows)
        assert all(r["colour_name"] == "Oat" for r in rows)
        assert all(r["stock_on_hand"] == "10" for r in rows)  # current level (reference)
        assert all(r["stock_quantity"] == "" for r in rows)  # the "add" column is blank on export

    def test_header_is_the_documented_column_set(self, product):
        rows = rows_of(csv_io.export_products())
        assert list(rows[0]) == csv_io.COLUMNS

    def test_export_leaves_stock_quantity_blank_so_a_round_trip_is_a_no_op(self, product):
        rows = rows_of(csv_io.export_products())
        # stock_quantity is "add this many"; blank on export means a re-upload adds
        # nothing. Current levels live in the read-only stock_on_hand column.
        assert all(r["stock_quantity"] == "" for r in rows)
        assert all(r["stock_on_hand"] != "" for r in rows)

    def test_product_with_no_colours_still_gets_a_row(self, db):
        bare = factories.ProductFactory(name="Bare", base_price=10)
        rows = rows_of(csv_io.export_products(Product.objects.filter(pk=bare.pk)))
        assert len(rows) == 1
        assert rows[0]["colour_name"] == ""

    def test_round_trip_changes_nothing(self, product):
        before = csv_io.export_products()
        report = csv_io.import_products(upload(before))
        assert report.ok, report.errors
        assert csv_io.export_products() == before


@pytest.mark.django_db
class TestImportStock:
    def test_stock_quantity_is_added_to_the_current_level(self, product, sizes):
        text = sheet(
            [{"slug": product.slug, "colour_name": "Oat", "size": "S", "stock_quantity": "40"}]
        )
        report = csv_io.import_products(upload(text))
        assert report.ok, report.errors

        variant = ProductVariant.objects.get(colour__product=product, size__name="S")
        assert variant.stock_quantity == 50  # 10 on hand + 40 added
        # Untouched sizes keep their seeded 10.
        assert ProductVariant.objects.get(colour__product=product, size__name="M").stock_quantity == 10

    def test_a_large_delivery_adds_up(self, product):
        # The reported scenario: on hand 10 + 100 arriving in the CSV = 110.
        text = sheet(
            [{"slug": product.slug, "colour_name": "Oat", "size": "S", "stock_quantity": "100"}]
        )
        assert csv_io.import_products(upload(text)).ok
        assert ProductVariant.objects.get(colour__product=product, size__name="S").stock_quantity == 110

    def test_negative_stock_quantity_writes_off(self, product):
        text = sheet(
            [{"slug": product.slug, "colour_name": "Oat", "size": "S", "stock_quantity": "-4"}]
        )
        assert csv_io.import_products(upload(text)).ok
        assert ProductVariant.objects.get(colour__product=product, size__name="S").stock_quantity == 6

    def test_writing_off_below_zero_is_refused_rather_than_floored(self, product):
        text = sheet(
            [{"slug": product.slug, "colour_name": "Oat", "size": "S", "stock_quantity": "-99"}]
        )
        report = csv_io.import_products(upload(text))
        assert not report.ok
        assert "below zero" in report.errors[0]
        assert ProductVariant.objects.get(colour__product=product, size__name="S").stock_quantity == 10


@pytest.mark.django_db
class TestImportProductFields:
    def test_description_and_price_are_updated(self, product):
        text = sheet(
            [
                {
                    "slug": product.slug,
                    "description": "Rewritten in the spreadsheet.",
                    "base_price": "129.00",
                }
            ]
        )
        assert csv_io.import_products(upload(text)).ok

        product.refresh_from_db()
        assert product.description == "Rewritten in the spreadsheet."
        assert product.base_price == Decimal("129.00")

    def test_blank_cell_leaves_the_existing_value_alone(self, product):
        original = product.description
        text = sheet([{"slug": product.slug, "description": "", "base_price": "55.00"}])
        assert csv_io.import_products(upload(text)).ok

        product.refresh_from_db()
        assert product.description == original
        assert product.base_price == Decimal("55.00")

    def test_clear_token_empties_a_field(self, product):
        product.compare_at_price = Decimal("150.00")
        product.save()

        text = sheet([{"slug": product.slug, "compare_at_price": "CLEAR"}])
        assert csv_io.import_products(upload(text)).ok

        product.refresh_from_db()
        assert product.compare_at_price is None
        assert product.on_sale is False

    def test_boolean_columns_accept_yes_no(self, product):
        text = sheet([{"slug": product.slug, "is_active": "no", "is_bestseller": "yes"}])
        assert csv_io.import_products(upload(text)).ok

        product.refresh_from_db()
        assert product.is_active is False
        assert product.is_bestseller is True

    def test_product_columns_are_read_once_not_from_the_last_row(self, product):
        """The export repeats product cells on every row; later rows must not win."""
        text = sheet(
            [
                {"slug": product.slug, "base_price": "10.00", "colour_name": "Oat", "size": "S"},
                {"slug": product.slug, "base_price": "10.00", "colour_name": "Oat", "size": "M"},
            ]
        )
        assert csv_io.import_products(upload(text)).ok

        product.refresh_from_db()
        assert product.base_price == Decimal("10.00")

    def test_collections_are_set_from_a_pipe_separated_list(self, product):
        best = factories.CollectionFactory(name="Bestsellers")
        new = factories.CollectionFactory(name="New Arrivals")

        text = sheet([{"slug": product.slug, "collections": f"{best.slug}|{new.slug}"}])
        assert csv_io.import_products(upload(text)).ok

        assert set(product.collections.values_list("slug", flat=True)) == {best.slug, new.slug}


@pytest.mark.django_db
class TestImportCreatesColoursAndVariants:
    def test_a_new_colourway_is_added(self, product, sizes):
        text = sheet(
            [
                {
                    "slug": product.slug,
                    "colour_name": "Sage",
                    "colour_hex": "#AEBBA4",
                    "size": "M",
                    "stock_quantity": "12",
                }
            ]
        )
        report = csv_io.import_products(upload(text))
        assert report.ok, report.errors
        assert report.colours_created == 1
        assert report.variants_created == 1

        colour = ProductColour.objects.get(product=product, name="Sage")
        assert colour.swatch_hex == "#AEBBA4"
        assert colour.variants.get(size__name="M").stock_quantity == 12

    def test_a_new_variant_gets_a_generated_sku(self, product):
        text = sheet(
            [{"slug": product.slug, "colour_name": "Sage", "size": "M", "stock_quantity": "1"}]
        )
        assert csv_io.import_products(upload(text)).ok

        variant = ProductVariant.objects.get(colour__name="Sage", size__name="M")
        assert variant.sku  # auto-generated by ProductVariant.save

    def test_unknown_size_is_rejected(self, product):
        text = sheet(
            [{"slug": product.slug, "colour_name": "Oat", "size": "XXL", "stock_quantity": "3"}]
        )
        report = csv_io.import_products(upload(text))
        assert not report.ok
        assert "isn't in the size list" in report.errors[0]


@pytest.mark.django_db
class TestImportValidation:
    def test_unknown_slug_is_rejected(self, product):
        text = sheet([{"slug": "no-such-product", "base_price": "10.00"}])
        report = csv_io.import_products(upload(text))
        assert not report.ok
        assert "no product with slug" in report.errors[0]

    def test_one_bad_row_rolls_back_the_whole_file(self, product):
        text = sheet(
            [
                {"slug": product.slug, "colour_name": "Oat", "size": "S", "stock_quantity": "99"},
                {"slug": "nope", "colour_name": "Oat", "size": "S", "stock_quantity": "1"},
            ]
        )
        report = csv_io.import_products(upload(text))
        assert not report.ok
        # The good row in front of the bad one must not have stuck.
        assert ProductVariant.objects.get(colour__product=product, size__name="S").stock_quantity == 10

    def test_missing_slug_column_is_reported(self, product):
        text = sheet([{"stock_quantity": "5"}])
        report = csv_io.import_products(upload(text))
        assert not report.ok
        assert "Missing required column" in report.errors[0]

    def test_unrecognised_column_is_reported(self, product):
        text = sheet([{"slug": product.slug, "Variant Grams": "500"}])
        report = csv_io.import_products(upload(text))
        assert not report.ok
        assert "Unrecognised column" in report.errors[0]

    def test_non_numeric_price_is_reported_with_its_row_number(self, product):
        text = sheet([{"slug": product.slug, "base_price": "one hundred"}])
        report = csv_io.import_products(upload(text))
        assert not report.ok
        assert report.errors[0].startswith("Row 2:")

    def test_dry_run_validates_without_saving(self, product):
        text = sheet(
            [{"slug": product.slug, "colour_name": "Oat", "size": "S", "stock_quantity": "77"}]
        )
        report = csv_io.import_products(upload(text), dry_run=True)
        assert report.ok
        assert report.variants_updated == 1
        assert ProductVariant.objects.get(colour__product=product, size__name="S").stock_quantity == 10

    def test_excel_utf8_bom_is_tolerated(self, product):
        text = sheet([{"slug": product.slug, "base_price": "77.00"}])
        report = csv_io.import_products(upload(text, encoding="utf-8-sig"))
        assert report.ok, report.errors
        product.refresh_from_db()
        assert product.base_price == Decimal("77.00")

    def test_blank_spacer_rows_are_skipped(self, product):
        text = sheet([{"slug": product.slug, "base_price": "88.00"}, {"slug": ""}])
        report = csv_io.import_products(upload(text))
        assert report.ok, report.errors
        assert report.rows_read == 1


@pytest.mark.django_db
class TestImportSideCases:
    def test_bad_colour_hex_is_rejected(self, product):
        text = sheet(
            [{"slug": product.slug, "colour_name": "Sage", "colour_hex": "banana",
              "size": "M", "stock_quantity": "1"}]
        )
        report = csv_io.import_products(upload(text))
        assert not report.ok
        assert "colour code" in report.errors[0]

    def test_colour_hex_without_hash_is_normalised(self, product):
        text = sheet(
            [{"slug": product.slug, "colour_name": "Sage", "colour_hex": "A8B3A0",
              "size": "M", "stock_quantity": "1"}]
        )
        assert csv_io.import_products(upload(text)).ok
        assert ProductColour.objects.get(product=product, name="Sage").swatch_hex == "#A8B3A0"

    def test_decimal_stock_is_rejected_not_truncated(self, product):
        text = sheet(
            [{"slug": product.slug, "colour_name": "Oat", "size": "S", "stock_quantity": "10.5"}]
        )
        report = csv_io.import_products(upload(text))
        assert not report.ok
        assert "whole number" in report.errors[0]
        assert ProductVariant.objects.get(colour__product=product, size__name="S").stock_quantity == 10

    def test_duplicate_colour_size_rows_are_rejected(self, product):
        text = sheet(
            [
                {"slug": product.slug, "colour_name": "Oat", "size": "S", "stock_quantity": "1"},
                {"slug": product.slug, "colour_name": "Oat", "size": "S", "stock_quantity": "2"},
            ]
        )
        report = csv_io.import_products(upload(text))
        assert not report.ok
        assert "duplicate row" in report.errors[0].lower()

    def test_duplicate_sku_in_file_is_rejected(self, product):
        text = sheet(
            [
                {"slug": product.slug, "colour_name": "Oat", "size": "S", "sku": "DUP-1"},
                {"slug": product.slug, "colour_name": "Oat", "size": "M", "sku": "DUP-1"},
            ]
        )
        report = csv_io.import_products(upload(text))
        assert not report.ok
        assert "sku" in report.errors[0].lower() and "unique" in report.errors[0].lower()

    def test_sale_price_at_or_below_base_is_rejected(self, product):
        text = sheet([{"slug": product.slug, "base_price": "100.00", "compare_at_price": "80.00"}])
        report = csv_io.import_products(upload(text))
        assert not report.ok
        assert "compare_at_price" in report.errors[0]

    def test_price_with_too_many_decimals_is_rejected(self, product):
        text = sheet([{"slug": product.slug, "base_price": "12.999"}])
        report = csv_io.import_products(upload(text))
        assert not report.ok
        assert "decimal" in report.errors[0].lower()

    def test_duplicate_header_column_is_rejected(self, product):
        text = f"slug,slug,base_price\n{product.slug},{product.slug},10.00\n"
        report = csv_io.import_products(upload(text))
        assert not report.ok
        assert "Duplicate column" in report.errors[0]

    def test_conflicting_repeated_value_warns_and_keeps_first_row(self, product):
        text = sheet(
            [
                {"slug": product.slug, "base_price": "10.00", "colour_name": "Oat", "size": "S"},
                {"slug": product.slug, "base_price": "20.00", "colour_name": "Oat", "size": "M"},
            ]
        )
        report = csv_io.import_products(upload(text))
        assert report.ok, report.errors
        assert any("base_price" in w for w in report.warnings)
        product.refresh_from_db()
        assert product.base_price == Decimal("10.00")  # first row wins

    def test_colour_details_without_a_name_warn_not_error(self, product):
        text = sheet([{"slug": product.slug, "colour_hex": "#A8B3A0"}])
        report = csv_io.import_products(upload(text))
        assert report.ok, report.errors
        assert any("colour details ignored" in w for w in report.warnings)

    def test_report_lists_the_exact_changes(self, product):
        text = sheet(
            [{"slug": product.slug, "base_price": "129.00", "colour_name": "Oat",
              "size": "S", "stock_quantity": "40"}]
        )
        report = csv_io.import_products(upload(text))
        assert report.ok, report.errors
        joined = " | ".join(report.changes)
        assert "base_price" in joined and "100" in joined and "129" in joined
        assert "stock 10 → 50" in joined  # 10 on hand + 40 added

    def test_a_no_op_import_lists_no_changes(self, product):
        # Re-uploading the current value changes nothing → empty change list.
        text = sheet([{"slug": product.slug, "base_price": str(product.base_price)}])
        report = csv_io.import_products(upload(text))
        assert report.ok
        assert report.changes == []

    def test_stock_on_hand_is_read_only_and_warns(self, product):
        # Editing the reference column does nothing; the shopper is nudged to
        # use stock_quantity (which is added on).
        text = sheet(
            [{"slug": product.slug, "colour_name": "Oat", "size": "S", "stock_on_hand": "999"}]
        )
        report = csv_io.import_products(upload(text))
        assert report.ok, report.errors
        assert ProductVariant.objects.get(colour__product=product, size__name="S").stock_quantity == 10
        assert any("stock_on_hand is read-only" in w for w in report.warnings)


@pytest.mark.django_db
class TestDashboardViews:
    def test_export_and_import_require_staff(self, client):
        for name in ("dashboard:product_export", "dashboard:product_import"):
            response = client.get(reverse(name))
            assert response.status_code == 302
            assert "/dashboard/login/" in response["Location"]

    def test_export_returns_a_csv_attachment(self, client, staff, product):
        client.force_login(staff)
        response = client.get(reverse("dashboard:product_export"))

        assert response.status_code == 200
        assert response["Content-Type"].startswith("text/csv")
        assert "attachment; filename=" in response["Content-Disposition"]
        body = response.content.decode()
        assert body.splitlines()[0] == ",".join(csv_io.COLUMNS)
        assert product.slug in body

    def test_export_honours_the_list_filters(self, client, staff, product):
        factories.ProductFactory(name="Excluded Item", base_price=20)
        client.force_login(staff)

        response = client.get(reverse("dashboard:product_export"), {"q": product.name})
        body = response.content.decode()
        assert product.slug in body
        assert "excluded-item" not in body

    def test_upload_updates_stock_and_shows_what_changed(self, client, staff, product):
        client.force_login(staff)
        text = sheet(
            [{"slug": product.slug, "colour_name": "Oat", "size": "S", "stock_quantity": "64"}]
        )
        response = client.post(
            reverse("dashboard:product_import"),
            {"file": upload(text), "dry_run": ""},
        )

        # The results page is rendered (not a redirect) so it can list the change.
        assert response.status_code == 200
        assert ProductVariant.objects.get(colour__product=product, size__name="S").stock_quantity == 74
        body = response.content.decode()
        assert "stock 10 → 74" in body  # exact change shown (10 on hand + 64 added), not just a count

    def test_preview_then_apply_without_reupload(self, client, staff, product):
        client.force_login(staff)
        variant = ProductVariant.objects.get(colour__product=product, size__name="S")
        start = variant.stock_quantity  # 10
        text = sheet(
            [{"slug": product.slug, "colour_name": "Oat", "size": "S", "stock_quantity": "7"}]
        )
        # Preview: nothing saved yet, but an "Apply" button is offered.
        r1 = client.post(
            reverse("dashboard:product_import"), {"file": upload(text), "dry_run": "1"}
        )
        variant.refresh_from_db()
        assert variant.stock_quantity == start
        assert b"apply_pending" in r1.content

        # Apply the previewed file — no re-upload of the file.
        r2 = client.post(reverse("dashboard:product_import"), {"apply_pending": "1"})
        variant.refresh_from_db()
        assert variant.stock_quantity == start + 7
        assert b"Import complete" in r2.content

    def test_apply_pending_with_no_preview_is_handled(self, client, staff, product):
        client.force_login(staff)
        response = client.post(reverse("dashboard:product_import"), {"apply_pending": "1"})
        assert response.status_code == 200
        assert b"expired" in response.content

    def test_upload_with_errors_re_renders_and_changes_nothing(self, client, staff, product):
        client.force_login(staff)
        text = sheet([{"slug": "ghost", "base_price": "5.00"}])
        response = client.post(
            reverse("dashboard:product_import"), {"file": upload(text), "dry_run": ""}
        )

        assert response.status_code == 200
        assert b"no product with slug" in response.content

    def test_product_list_offers_both_buttons(self, client, staff, product):
        client.force_login(staff)
        body = client.get(reverse("dashboard:product_list")).content.decode()
        assert "Export as CSV" in body
        assert "Import CSV" in body
