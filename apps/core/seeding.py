"""SEED_DEMO — what happens to the database when the dev server boots.

Driven by the ``SEED_DEMO`` env var:

    0  off       never touch the database (default)
    1  always    wipe and re-seed the demo dataset on every server start
    2  if-empty  seed only when the catalogue is empty, otherwise leave it alone
    3  reset     wipe every record, keep (or create) a staff login, seed nothing

The policy only ever runs for ``manage.py runserver`` — never for migrate,
tests, shell or a WSGI/ASGI server. See ``apps/core/apps.py``.
"""

import os
import sys

from django.conf import settings
from django.core.management import call_command
from django.db import transaction

OFF = 0
ALWAYS = 1
IF_EMPTY = 2
RESET = 3

# ASCII only: this is written straight to a Windows console, where a cp1252
# codec would raise UnicodeEncodeError on an em-dash and take the server down.
MODE_LABELS = {
    OFF: "off - leaving the database alone",
    ALWAYS: "always - wiping and re-seeding the demo dataset",
    IF_EMPTY: "if-empty - seeding only when the catalogue is empty",
    RESET: "reset - wiping all data, keeping an admin login",
}

DEFAULT_ADMIN_EMAIL = "staff@lavenderhill.test"
DEFAULT_ADMIN_PASSWORD = "lavender123"

# Sizes are the axis the stock grid is built from: with none, the product
# editor renders a grid with no rows and stock can't be entered at all. They're
# the size chart rather than content, so a reset restores them like the admin.
DEFAULT_SIZES = [("XS", 1), ("S", 2), ("M", 3), ("L", 4), ("XL", 5), ("One Size", 6)]

# How long a wipe will wait for a row/table lock before giving up (Postgres only).
LOCK_TIMEOUT_MS = 5000


def _deletion_order():
    """Every model holding store data, in an FK-safe deletion order.

    ``Product.category`` and ``ProductVariant.size`` are ``PROTECT``, so
    products must go before categories and variants before sizes.
    """
    from apps.accounts.models import Address
    from apps.cart.models import Cart, CartItem
    from apps.catalog.models import (
        Category,
        Collection,
        Fabric,
        Product,
        ProductColour,
        ProductImage,
        ProductVariant,
        Review,
        Size,
    )
    from apps.marketing.models import (
        ContactMessage,
        HomeSection,
        JournalCategory,
        JournalPost,
        NewsletterSubscriber,
        SiteSettings,
    )
    from apps.orders.models import Discount, Order, OrderItem
    from apps.wishlist.models import WishlistItem

    return [
        OrderItem,
        Order,
        Discount,
        CartItem,
        Cart,
        WishlistItem,
        Review,
        ProductImage,
        ProductVariant,
        ProductColour,
        Product,
        Category,
        Collection,
        Fabric,
        Size,
        ContactMessage,
        HomeSection,
        JournalPost,
        JournalCategory,
        NewsletterSubscriber,
        SiteSettings,
        Address,
    ]


@transaction.atomic
def wipe(write):
    """Delete every store record. Staff/superusers survive so login still works."""
    from django.contrib.auth import get_user_model
    from django.db import connection

    # Without this the DELETE waits forever on any conflicting lock — a second
    # runserver, a pgAdmin query tab, an open psql transaction — and because we
    # run during app init that hangs the server before it ever binds a port.
    # Failing fast turns an invisible hang into a message you can act on.
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT_MS}ms'")

    removed = 0
    for model in _deletion_order():
        count, _ = model.objects.all().delete()
        removed += count

    # Customers go with the rest of the data; staff accounts are the way back in.
    count, _ = get_user_model().objects.filter(is_staff=False, is_superuser=False).delete()
    removed += count

    write(f"  wiped {removed} rows")
    return removed


def ensure_admin(write):
    """Guarantee at least one staff account exists for /dashboard/login/."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    if User.objects.filter(is_staff=True).exists():
        return False

    User.objects.create_user(
        email=DEFAULT_ADMIN_EMAIL,
        password=DEFAULT_ADMIN_PASSWORD,
        first_name="Studio",
        last_name="Team",
        is_staff=True,
    )
    write(f"  created staff login {DEFAULT_ADMIN_EMAIL} / {DEFAULT_ADMIN_PASSWORD}")
    return True


def ensure_sizes(write):
    """Restore the size chart so the stock grid has rows to edit."""
    from apps.catalog.models import Size

    if Size.objects.exists():
        return False

    for name, order in DEFAULT_SIZES:
        Size.objects.create(name=name, sort_order=order)
    write(f"  restored {len(DEFAULT_SIZES)} sizes (needed by the stock grid)")
    return True


def catalogue_is_empty():
    from apps.catalog.models import Product

    return not Product.objects.exists()


def apply(mode=None, write=None):
    """Run the configured policy. Returns the mode that was applied."""
    mode = settings.SEED_DEMO if mode is None else mode
    write = write or (lambda message: sys.stdout.write(message + "\n"))

    if mode not in MODE_LABELS:
        write(f"SEED_DEMO={mode} is not one of 0/1/2/3 — skipping.")
        return None

    if mode == OFF:
        return OFF

    write(f"SEED_DEMO={mode}: {MODE_LABELS[mode]}")

    if mode == ALWAYS:
        wipe(write)
        call_command("seed_demo")
    elif mode == IF_EMPTY:
        if catalogue_is_empty():
            call_command("seed_demo")
        else:
            write("  catalogue already has products - nothing to do")
    elif mode == RESET:
        wipe(write)
        ensure_admin(write)
        ensure_sizes(write)

    return mode


# ------------------------------------------------------------------ boot hook


def should_run_on_boot():
    """True only in the process that actually serves ``runserver``."""
    if getattr(settings, "SEED_DEMO", OFF) == OFF:
        return False
    if len(sys.argv) < 2 or sys.argv[1] != "runserver":
        return False
    if "--noreload" in sys.argv:
        return True
    # Under the autoreloader ready() runs twice: once in the watcher parent and
    # once in the child that serves. RUN_MAIN is only set in the child.
    return os.environ.get("RUN_MAIN") == "true"


def run_on_boot():
    if not should_run_on_boot():
        return

    import warnings

    from django.db import DatabaseError

    # apps.core is first in INSTALLED_APPS, so catalog's ready() (which wires the
    # Review → rating signal) hasn't run yet. Import is cached, so this is a no-op
    # when it later runs for real.
    import apps.catalog.signals  # noqa: F401

    try:
        # Django warns about queries during app init because they misbehave under
        # multi-process servers. should_run_on_boot() has already limited us to a
        # single runserver process that hasn't served a request yet, so the query
        # is deliberate here and the warning is just noise.
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message="Accessing the database during app initialization",
                category=RuntimeWarning,
            )
            apply()
    except KeyboardInterrupt:
        # Ctrl+C during app init otherwise dumps a full traceback through
        # django.setup(). The wipe is atomic, so an interrupted wipe rolled back.
        sys.stderr.write(
            "\nSEED_DEMO: interrupted. Run `py manage.py apply_seed_policy` "
            "to finish, or set SEED_DEMO=0 to boot without it.\n"
        )
        raise SystemExit(1) from None
    except DatabaseError as exc:
        # Deliberately non-fatal: warn and let the server start anyway.
        sys.stderr.write(
            f"SEED_DEMO: skipped - {exc}\n"
            "  Lock timeout? Another connection is holding one - a second runserver,\n"
            "  a pgAdmin query tab, or an open psql transaction. Close it and restart.\n"
            "  Missing tables? Run `py manage.py migrate` first.\n"
        )
