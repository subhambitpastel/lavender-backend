"""Catalogue CSV round-trip: export the products, edit in a spreadsheet, re-upload.

The file is **one row per SKU** — that is, per colour × size — because that is how
the catalogue is actually shaped (see BACKEND_IMPL_GUIDE §"SKU = colour × size").
Product-level columns therefore repeat across a product's rows; on import they are
read from that product's first row and ignored on the rest, so the owner only has
to fill them in once.

Import rules, in short:

* ``slug`` identifies the product and must already exist — a typo can't silently
  create a junk product. Everything else about the product can be edited.
* A blank cell means **leave this value alone**. That is what makes a
  stock-only or price-only edit possible: delete every column you don't care
  about, keep ``slug``/``colour_name``/``size``, and nothing else is touched.
* To deliberately empty a text field or clear a sale price, write ``CLEAR``.
* Stock is **added**, not replaced: whatever is in ``stock_quantity`` is added to
  the current level (``25`` books in a delivery, ``-2`` writes off breakage). So a
  product on hand at 20, uploaded with ``stock_quantity`` 100, ends up at 120.
  The current level is shown read-only in ``stock_on_hand`` (ignored on import),
  and the export leaves ``stock_quantity`` blank so re-uploading it changes nothing.
* A colour or size that doesn't exist yet on the product is created. Sizes
  themselves must already exist in the admin size list.
* The whole file is validated before anything is written; one bad row aborts the
  import and the catalogue is left untouched.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from io import StringIO

from django.db import transaction

from .models import (
    Category,
    Collection,
    Fabric,
    Product,
    ProductColour,
    ProductVariant,
    Size,
)

# Sentinel a cell can hold to blank out a field, since an empty cell means
# "unchanged". Case-insensitive.
CLEAR = "CLEAR"

# Multi-value cells (collections, fabrics) use "|" — commas would fight the CSV
# quoting and "/" appears inside real names.
LIST_SEPARATOR = "|"

# A swatch colour is a 3- or 6-digit hex code, with or without a leading "#".
HEX_RE = re.compile(r"^#?(?:[0-9A-Fa-f]{3}|[0-9A-Fa-f]{6})$")

# Money is stored to 2 decimal places, so anything finer is a mistake, not a value.
MONEY_PLACES = 2

PRODUCT_COLUMNS = [
    "slug",
    "name",
    "description",
    "category",
    "collections",
    "fabrics",
    "base_price",
    "compare_at_price",
    "composition",
    "care_instructions",
    "sustainability_note",
    "meta_title",
    "meta_description",
    "is_active",
    "is_featured",
    "is_new_in",
    "is_bestseller",
    "sort_order",
]

VARIANT_COLUMNS = [
    "colour_name",
    "colour_hex",
    "colour_is_active",
    "size",
    # `stock_on_hand` is the current level, shown on export for reference only —
    # it is ignored on import. To change stock, put the amount to add (or a
    # negative to write off) in `stock_quantity`; it is ADDED to what's on hand.
    "sku",
    "stock_on_hand",
    "stock_quantity",
    "price_override",
    "variant_is_active",
]

# SKU is the unique per-variant key (one row = one SKU), so it leads the file
# for easy lookup/sorting in a spreadsheet. Product columns repeat per row and
# the remaining variant columns follow. Import reads columns by name, so this
# ordering is purely presentational and round-trips unchanged.
COLUMNS = ["sku"] + PRODUCT_COLUMNS + [c for c in VARIANT_COLUMNS if c != "sku"]

# Only `slug` is structurally required; the rest may be dropped entirely from an
# upload, which is how a stock-only sheet stays small.
REQUIRED_COLUMNS = ["slug"]

TEXT_FIELDS = [
    "name",
    "description",
    "composition",
    "care_instructions",
    "sustainability_note",
    "meta_title",
    "meta_description",
]

BOOL_FIELDS = ["is_active", "is_featured", "is_new_in", "is_bestseller"]

TRUE_WORDS = {"1", "true", "yes", "y", "active", "on"}
FALSE_WORDS = {"0", "false", "no", "n", "inactive", "off"}


class RowError(Exception):
    """A problem with one row, reported against its line number."""


# --------------------------------------------------------------------- export


def _bool_out(value: bool) -> str:
    return "yes" if value else "no"


def export_products(queryset=None) -> str:
    """Render products as CSV text — one row per variant, product rows repeated.

    A product with no colours (or a colour with no sizes) still gets a row, so a
    freshly created product can be filled in from the spreadsheet.
    """
    if queryset is None:
        queryset = Product.objects.all()
    queryset = queryset.select_related("category").prefetch_related(
        "collections", "fabrics", "colours__variants__size"
    )

    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=COLUMNS, lineterminator="\n")
    writer.writeheader()

    for product in queryset:
        base = {
            "slug": product.slug,
            "name": product.name,
            "description": product.description,
            "category": product.category.slug if product.category_id else "",
            "collections": LIST_SEPARATOR.join(
                c.slug for c in product.collections.all()
            ),
            "fabrics": LIST_SEPARATOR.join(f.slug for f in product.fabrics.all()),
            "base_price": f"{product.base_price:.2f}",
            "compare_at_price": (
                f"{product.compare_at_price:.2f}" if product.compare_at_price else ""
            ),
            "composition": product.composition,
            "care_instructions": product.care_instructions,
            "sustainability_note": product.sustainability_note,
            "meta_title": product.meta_title,
            "meta_description": product.meta_description,
            "is_active": _bool_out(product.is_active),
            "is_featured": _bool_out(product.is_featured),
            "is_new_in": _bool_out(product.is_new_in),
            "is_bestseller": _bool_out(product.is_bestseller),
            "sort_order": product.sort_order,
        }

        rows = 0
        for colour in product.colours.all():
            colour_cells = {
                "colour_name": colour.name,
                "colour_hex": colour.swatch_hex,
                "colour_is_active": _bool_out(colour.is_active),
            }
            for variant in colour.variants.all():
                writer.writerow(
                    {
                        **base,
                        **colour_cells,
                        "size": variant.size.name,
                        "sku": variant.sku,
                        # Current level for reference (read-only on import)…
                        "stock_on_hand": variant.stock_quantity,
                        # …and the "amount to add" column stays blank on export, so
                        # re-uploading the file adds nothing (a true no-op round trip).
                        "stock_quantity": "",
                        "price_override": (
                            f"{variant.price_override:.2f}"
                            if variant.price_override is not None
                            else ""
                        ),
                        "variant_is_active": _bool_out(variant.is_active),
                    }
                )
                rows += 1
            if not colour.variants.all():
                writer.writerow({**base, **colour_cells})
                rows += 1
        if not rows:
            writer.writerow(base)

    return buffer.getvalue()


# --------------------------------------------------------------------- import


@dataclass
class ImportReport:
    """Outcome of an import run — counts for the flash message, errors for the page."""

    products_updated: int = 0
    colours_created: int = 0
    variants_created: int = 0
    variants_updated: int = 0
    rows_read: int = 0
    errors: list[str] = field(default_factory=list)
    # Non-fatal notes (e.g. a repeated value that disagreed with the first row).
    # Unlike errors, warnings don't roll the import back.
    warnings: list[str] = field(default_factory=list)
    # A human-readable line for every concrete change made — so the report shows
    # exactly what changed, field by field, not just a count.
    changes: list[str] = field(default_factory=list)
    dry_run: bool = False

    @property
    def ok(self) -> bool:
        return not self.errors

    def summary(self) -> str:
        verb = "would be" if self.dry_run else ""
        parts = [
            f"{self.rows_read} row{'s' if self.rows_read != 1 else ''} read",
            f"{self.products_updated} product{'s' if self.products_updated != 1 else ''} updated",
            f"{self.variants_updated} variant{'s' if self.variants_updated != 1 else ''} updated",
        ]
        if self.colours_created:
            parts.append(f"{self.colours_created} new colour(s)")
        if self.variants_created:
            parts.append(f"{self.variants_created} new variant(s)")
        if self.warnings:
            parts.append(f"{len(self.warnings)} warning{'s' if len(self.warnings) != 1 else ''}")
        joined = ", ".join(parts)
        return f"{joined}{' — dry run, nothing saved' if verb else ''}."


def _clean(value) -> str:
    return (value or "").strip()


def _short(value, limit: int = 50) -> str:
    """A compact, one-line form of a value for the change log."""
    text = " ".join(str(value).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _is_clear(value: str) -> bool:
    return value.upper() == CLEAR


def _parse_bool(value: str, column: str) -> bool:
    lowered = value.lower()
    if lowered in TRUE_WORDS:
        return True
    if lowered in FALSE_WORDS:
        return False
    raise RowError(f"{column}: “{value}” isn't a yes/no value.")


def _parse_decimal(value: str, column: str) -> Decimal:
    try:
        parsed = Decimal(value.replace(",", "").replace("£", ""))
    except (InvalidOperation, ValueError):
        raise RowError(f"{column}: “{value}” isn't a number.") from None
    if parsed < 0:
        raise RowError(f"{column}: can't be negative.")
    # A price finer than 2 decimals would be silently rounded on save — surface it.
    if parsed.as_tuple().exponent < -MONEY_PLACES:
        raise RowError(f"{column}: use at most {MONEY_PLACES} decimal places, e.g. 12.99.")
    return parsed


def _parse_int(value: str, column: str, allow_negative=False) -> int:
    try:
        parsed = Decimal(value.replace(",", ""))
    except (InvalidOperation, ValueError):
        raise RowError(f"{column}: “{value}” isn't a whole number.") from None
    # Reject 10.5 rather than silently truncating it to 10.
    if parsed != parsed.to_integral_value():
        raise RowError(f"{column}: “{value}” must be a whole number (no decimals).")
    parsed = int(parsed)
    if parsed < 0 and not allow_negative:
        raise RowError(f"{column}: can't be negative.")
    return parsed


def _parse_hex(value: str, column: str = "colour_hex") -> str:
    """Validate a swatch colour and normalise to a leading-# form (case kept).

    Anything that isn't a hex code — ``banana``, ``#ZZZ``, ``12345`` — is rejected
    rather than saved and quietly breaking the storefront swatch.
    """
    cleaned = value.strip()
    if not HEX_RE.match(cleaned):
        raise RowError(
            f'{column}: “{value}” isn’t a colour code — use a hex like #A8B3A0.'
        )
    return cleaned if cleaned.startswith("#") else f"#{cleaned}"


def _apply_product_fields(product: Product, row: dict, report: ImportReport) -> bool:
    """Write the product-level cells of `row` onto `product`. Returns True if changed."""
    changed = []
    # The product's name may itself change, so label the log with its first value.
    label = product.name

    def note(column, old, new):
        report.changes.append(f"{label}: {column} “{_short(old)}” → “{_short(new)}”")

    for column in TEXT_FIELDS:
        if column not in row:
            continue
        value = _clean(row[column])
        if not value:
            continue
        new = "" if _is_clear(value) else value
        if column == "name" and not new:
            raise RowError("name: can't be emptied.")
        if getattr(product, column) != new:
            note(column, getattr(product, column) or "(blank)", new or "(blank)")
            setattr(product, column, new)
            changed.append(column)

    if "base_price" in row and (value := _clean(row["base_price"])):
        price = _parse_decimal(value, "base_price")
        if product.base_price != price:
            note("base_price", product.base_price, price)
            product.base_price = price
            changed.append("base_price")

    if "compare_at_price" in row and (value := _clean(row["compare_at_price"])):
        new_compare = None if _is_clear(value) else _parse_decimal(value, "compare_at_price")
        if product.compare_at_price != new_compare:
            note(
                "compare_at_price",
                product.compare_at_price if product.compare_at_price is not None else "(none)",
                new_compare if new_compare is not None else "(cleared)",
            )
            product.compare_at_price = new_compare
            changed.append("compare_at_price")

    for column in BOOL_FIELDS:
        if column not in row:
            continue
        if value := _clean(row[column]):
            parsed = _parse_bool(value, column)
            if getattr(product, column) != parsed:
                note(column, _bool_out(getattr(product, column)), _bool_out(parsed))
                setattr(product, column, parsed)
                changed.append(column)

    if "sort_order" in row and (value := _clean(row["sort_order"])):
        parsed = _parse_int(value, "sort_order")
        if product.sort_order != parsed:
            note("sort_order", product.sort_order, parsed)
            product.sort_order = parsed
            changed.append("sort_order")

    if "category" in row and (value := _clean(row["category"])):
        category = Category.objects.filter(slug=value).first() or Category.objects.filter(
            name__iexact=value
        ).first()
        if category is None:
            raise RowError(f"category: no category matches “{value}”.")
        if product.category_id != category.pk:
            old_cat = product.category.slug if product.category_id else "(none)"
            note("category", old_cat, category.slug)
            product.category = category
            changed.append("category")

    # A "sale" price at or below the normal price isn't a sale — reject it, the
    # same rule the dashboard product form enforces.
    if (
        product.compare_at_price is not None
        and product.compare_at_price <= product.base_price
    ):
        raise RowError(
            "compare_at_price must be higher than base_price (or left blank to clear the sale)."
        )

    if changed:
        product.save()
    return bool(changed)


def _apply_m2m(product: Product, row: dict, report: ImportReport) -> bool:
    """collections / fabrics are pipe-separated slug lists; CLEAR empties them."""
    changed = False
    for column, model, relation in (
        ("collections", Collection, product.collections),
        ("fabrics", Fabric, product.fabrics),
    ):
        if column not in row:
            continue
        value = _clean(row[column])
        if not value:
            continue
        if _is_clear(value):
            if relation.exists():
                relation.clear()
                changed = True
                report.changes.append(f"{product.name}: {column} cleared")
            continue

        wanted = [v.strip() for v in value.split(LIST_SEPARATOR) if v.strip()]
        objects = []
        for token in wanted:
            match = model.objects.filter(slug=token).first() or model.objects.filter(
                name__iexact=token
            ).first()
            if match is None:
                raise RowError(f"{column}: no match for “{token}”.")
            objects.append(match)
        if set(relation.all()) != set(objects):
            relation.set(objects)
            changed = True
            report.changes.append(
                f"{product.name}: {column} → {', '.join(o.slug for o in objects)}"
            )
    return changed


def _apply_variant(colour: ProductColour, row: dict, report: ImportReport) -> None:
    size_name = _clean(row.get("size", ""))
    if not size_name:
        # Colour-level row (swatch/active only) — nothing further to do.
        return

    size = Size.objects.filter(name__iexact=size_name).first()
    if size is None:
        raise RowError(
            f"size: “{size_name}” isn't in the size list — add it under Sizes first."
        )

    variant = ProductVariant.objects.filter(colour=colour, size=size).first()
    created = variant is None
    if created:
        variant = ProductVariant(colour=colour, size=size)

    sku_hint = _clean(row.get("sku", "")) or variant.sku
    where = f"{colour.product.name} / {colour.name} / {size.name}"
    if sku_hint:
        where += f" [SKU {sku_hint}]"
    old_stock = variant.stock_quantity

    # `stock_on_hand` is reference-only — nudge the user if they edited it hoping
    # to set stock, since it's ignored (they should use stock_quantity, which adds).
    on_hand = _clean(row.get("stock_on_hand", ""))
    if (
        on_hand
        and not created
        and on_hand.lstrip("-").isdigit()
        and int(on_hand) != variant.stock_quantity
    ):
        report.warnings.append(
            f"{where}: stock_on_hand is read-only and was ignored — put the amount to "
            f"add in stock_quantity instead."
        )

    changed = created
    if value := _clean(row.get("stock_quantity", "")):
        # The amount is ADDED to what's on hand (a delivery in / write-off), not
        # set — so 100 against a product at 20 makes 120.
        delta = _parse_int(value, "stock_quantity", allow_negative=True)
        # Stock can't go below zero; asking to remove more than is there is a
        # mistake worth surfacing rather than silently flooring.
        if variant.stock_quantity + delta < 0:
            raise RowError(
                f"stock_quantity: adding {delta} would take stock below zero "
                f"(currently {variant.stock_quantity})."
            )
        if delta != 0:
            variant.stock_quantity += delta
            changed = True

    if value := _clean(row.get("price_override", "")):
        new_price = None if _is_clear(value) else _parse_decimal(value, "price_override")
        if variant.price_override != new_price:
            report.changes.append(
                f"{where}: price_override "
                f"{variant.price_override if variant.price_override is not None else '(base)'} → "
                f"{new_price if new_price is not None else '(base)'}"
            )
            variant.price_override = new_price
            changed = True

    if value := _clean(row.get("variant_is_active", "")):
        parsed = _parse_bool(value, "variant_is_active")
        if variant.is_active != parsed:
            report.changes.append(
                f"{where}: variant_is_active {_bool_out(variant.is_active)} → {_bool_out(parsed)}"
            )
            variant.is_active = parsed
            changed = True

    if sku := _clean(row.get("sku", "")):
        clash = ProductVariant.objects.filter(sku=sku).exclude(pk=variant.pk).exists()
        if clash:
            raise RowError(f"sku: “{sku}” is already used by another variant.")
        if variant.sku != sku:
            report.changes.append(f"{where}: sku “{variant.sku or '(auto)'}” → “{sku}”")
            variant.sku = sku
            changed = True

    if changed:
        variant.save()
        if created:
            report.variants_created += 1
            report.changes.append(
                f"{colour.product.name} / {colour.name} / {size.name} [SKU {variant.sku}]: "
                f"new SKU created (stock {variant.stock_quantity})"
            )
        else:
            report.variants_updated += 1
            if variant.stock_quantity != old_stock:
                report.changes.append(f"{where}: stock {old_stock} → {variant.stock_quantity}")


def _apply_colour(product: Product, row: dict, report: ImportReport) -> ProductColour | None:
    colour_name = _clean(row.get("colour_name", ""))
    if not colour_name:
        return None

    colour = ProductColour.objects.filter(
        product=product, name__iexact=colour_name
    ).first()
    if colour is None:
        colour = ProductColour(product=product, name=colour_name)
        hex_value = _clean(row.get("colour_hex", ""))
        if hex_value and not _is_clear(hex_value):
            colour.swatch_hex = _parse_hex(hex_value)
        colour.save()
        report.colours_created += 1
        report.changes.append(f"{product.name}: added colour “{colour_name}” ({colour.swatch_hex})")
        return colour

    where = f"{product.name} / {colour.name}"
    changed = []
    if (hex_value := _clean(row.get("colour_hex", ""))) and not _is_clear(hex_value):
        normalised = _parse_hex(hex_value)
        if colour.swatch_hex != normalised:
            report.changes.append(f"{where}: colour_hex {colour.swatch_hex} → {normalised}")
            colour.swatch_hex = normalised
            changed.append("swatch_hex")
    if value := _clean(row.get("colour_is_active", "")):
        parsed = _parse_bool(value, "colour_is_active")
        if colour.is_active != parsed:
            report.changes.append(
                f"{where}: colour_is_active {_bool_out(colour.is_active)} → {_bool_out(parsed)}"
            )
            colour.is_active = parsed
            changed.append("is_active")
    if changed:
        colour.save()
    return colour


def import_products(file_obj, dry_run: bool = False) -> ImportReport:
    """Apply a CSV upload to the catalogue.

    Everything happens inside one transaction: any row error rolls the whole
    file back, so the owner never ends up with half an update applied. A
    ``dry_run`` validates and reports, then rolls back regardless.
    """
    report = ImportReport(dry_run=dry_run)

    try:
        raw = file_obj.read()
    except Exception:
        report.errors.append("That file couldn't be read.")
        return report
    if isinstance(raw, bytes):
        # utf-8-sig strips the BOM Excel writes, which would otherwise turn the
        # first header into "﻿slug" and make every row look slug-less.
        try:
            raw = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            try:
                raw = raw.decode("cp1252")
            except UnicodeDecodeError:
                report.errors.append(
                    "That file isn't UTF-8 text — re-save it as CSV UTF-8 and try again."
                )
                return report

    reader = csv.DictReader(StringIO(raw))
    if not reader.fieldnames:
        report.errors.append("That file is empty.")
        return report

    header = [(name or "").strip().lower() for name in reader.fieldnames]
    present = set(header)

    # A repeated header makes DictReader silently drop all but the last column,
    # so a "sku, …, sku" file would lose data without saying so.
    duplicates = sorted({c for c in header if c and header.count(c) > 1})
    if duplicates:
        report.errors.append(
            f"Duplicate column(s): {', '.join(duplicates)}. Each column may appear only once."
        )
        return report

    missing = [c for c in REQUIRED_COLUMNS if c not in present]
    if missing:
        report.errors.append(
            f"Missing required column(s): {', '.join(missing)}. "
            "Export the catalogue first to get a file with the right headers."
        )
        return report

    unknown = sorted(present - set(COLUMNS) - {""})
    if unknown:
        report.errors.append(
            f"Unrecognised column(s): {', '.join(unknown)}. "
            "Remove them, or rename to match the exported headers."
        )
        return report

    seen_products: set[str] = set()
    # First row's cells per product, so later rows can be checked for conflicts.
    first_row: dict[str, dict] = {}
    warned_conflicts: set[tuple[str, str]] = set()
    # Variant identities and SKUs already seen in THIS file, to catch duplicates.
    seen_variants: dict[tuple[str, str, str], int] = {}
    seen_skus: dict[str, int] = {}

    try:
        with transaction.atomic():
            for line_number, raw_row in enumerate(reader, start=2):
                row = {
                    (k or "").strip().lower(): v
                    for k, v in raw_row.items()
                    if k is not None
                }
                slug = _clean(row.get("slug", ""))
                if not slug and not any(_clean(v) for v in row.values()):
                    continue  # blank spacer line
                report.rows_read += 1

                try:
                    if not slug:
                        raise RowError("slug: required — which product is this row for?")

                    product = Product.objects.filter(slug=slug).first()
                    if product is None:
                        raise RowError(
                            f"slug: no product with slug “{slug}”. "
                            "Products are updated, not created, by import."
                        )

                    colour_name = _clean(row.get("colour_name", ""))
                    size_name = _clean(row.get("size", ""))

                    # A colour × size may appear only once — a second row would
                    # silently overwrite the first, so flag it instead.
                    if colour_name and size_name:
                        identity = (slug, colour_name.lower(), size_name.lower())
                        if identity in seen_variants:
                            raise RowError(
                                f"duplicate row for {colour_name} / {size_name} — "
                                f"already given on line {seen_variants[identity]}."
                            )
                        seen_variants[identity] = line_number

                    # A SKU is unique, so it can't be reused on two rows.
                    if row_sku := _clean(row.get("sku", "")):
                        if row_sku in seen_skus:
                            raise RowError(
                                f"sku “{row_sku}” is on more than one row "
                                f"(also line {seen_skus[row_sku]}) — SKUs must be unique."
                            )
                        seen_skus[row_sku] = line_number

                    # Product columns are read once per product: the export
                    # repeats them on every variant row, and re-applying them
                    # would make later rows silently win. Later rows are checked
                    # for disagreements and warned about (not applied).
                    if slug not in seen_products:
                        seen_products.add(slug)
                        first_row[slug] = row
                        touched = _apply_product_fields(product, row, report)
                        touched = _apply_m2m(product, row, report) or touched
                        if touched:
                            report.products_updated += 1
                    else:
                        for column in PRODUCT_COLUMNS:
                            if column == "slug":
                                continue
                            here = _clean(row.get(column, ""))
                            first = _clean(first_row[slug].get(column, ""))
                            if here and first and here != first and (slug, column) not in warned_conflicts:
                                warned_conflicts.add((slug, column))
                                report.warnings.append(
                                    f"Row {line_number}: {column} for “{slug}” is “{here}” here "
                                    f"but “{first}” on its first row — the first row was used."
                                )

                    colour = _apply_colour(product, row, report)
                    if colour is not None:
                        _apply_variant(colour, row, report)
                    elif size_name:
                        raise RowError(
                            "size given without colour_name — a SKU is a colour × size."
                        )
                    elif _clean(row.get("colour_hex", "")) or _clean(row.get("colour_is_active", "")):
                        report.warnings.append(
                            f"Row {line_number}: colour details ignored — no colour_name given."
                        )
                except RowError as exc:
                    report.errors.append(f"Row {line_number}: {exc}")
                    if len(report.errors) >= 50:
                        report.errors.append("… further rows not checked.")
                        break

            if report.errors or dry_run:
                transaction.set_rollback(True)
    except Exception as exc:  # pragma: no cover - unexpected DB/parse failure
        report.errors.append(f"Import failed: {exc}")

    if report.errors:
        # Nothing was written, so don't report counts, warnings or changes that
        # didn't happen.
        report.products_updated = report.colours_created = 0
        report.variants_created = report.variants_updated = 0
        report.warnings = []
        report.changes = []

    return report
