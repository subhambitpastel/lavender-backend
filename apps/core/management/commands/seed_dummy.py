"""Populate the store with dummy trading activity.

`seed_demo` builds the catalogue and site content. This command fills in
everything that accumulates once a shop is *running* — customers, order history,
addresses, wishlists, reviews awaiting moderation, enquiries and subscribers —
so the dashboard's KPIs, order list and moderation queues have something real to
show.

    py manage.py seed_dummy
    py manage.py seed_dummy --customers 60 --orders 150
    py manage.py seed_dummy --flush          # clear previous dummy activity first

Historical orders deliberately do **not** decrement live stock: they represent
trading that already happened and settled, so inventory keeps reflecting what is
on the shelf today. Only the checkout flow moves stock.
"""

import random
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.accounts.models import Address
from apps.catalog.models import Product, ProductVariant, Review
from apps.core.utils import money
from apps.marketing.models import ContactMessage, NewsletterSubscriber
from apps.orders.models import Discount, Order, OrderItem
from apps.wishlist.models import WishlistItem

User = get_user_model()

# Generated accounts all use @example.com so --flush can find them again.
DUMMY_DOMAIN = "example.com"

FIRST_NAMES = [
    "Eleanor", "Priya", "Hannah", "Marta", "Sophie", "Ama", "Isla", "Freya",
    "Niamh", "Rosa", "Beatrice", "Clara", "Imogen", "Nadia", "Yuki", "Leila",
    "Fiona", "Greta", "Anouk", "Sadie", "Tessa", "Margot", "Colette", "Ada",
    "Ines", "Bridget", "Saoirse", "Delphine", "Maya", "Verity", "Juno", "Elspeth",
    "Camille", "Rania", "Astrid", "琳", "Noor", "Wren", "Thea", "Cassia",
]
LAST_NAMES = [
    "Reid", "Sharma", "Bennett", "Kowalski", "Turner", "Okafor", "Mackenzie",
    "Lindqvist", "Doherty", "Alvarez", "Whitfield", "Moreau", "Ashworth",
    "Haddad", "Tanaka", "Rahman", "Buchanan", "Hoffmann", "Visser", "Ellery",
    "Pemberton", "Devlin", "Rossi", "Nkemdirim", "Fairbanks", "Sutcliffe",
]
CITIES = [
    ("London", "SW11", "Greater London"), ("Bristol", "BS8", "Bristol"),
    ("Edinburgh", "EH3", "Midlothian"), ("Manchester", "M20", "Greater Manchester"),
    ("Leeds", "LS6", "West Yorkshire"), ("Brighton", "BN1", "East Sussex"),
    ("Bath", "BA2", "Somerset"), ("York", "YO1", "North Yorkshire"),
    ("Cardiff", "CF10", "South Glamorgan"), ("Glasgow", "G12", "Lanarkshire"),
    ("Oxford", "OX2", "Oxfordshire"), ("Norwich", "NR2", "Norfolk"),
]
STREETS = [
    "Lavender Hill", "Meadow Lane", "Cornmarket Street", "Alma Road",
    "Bramble Close", "Hollow Way", "Fern Avenue", "Willowbank Terrace",
    "Chapel Street", "Orchard Rise", "Marlborough Road", "Sycamore Grove",
]

# Weighted so the dashboard shows a believable spread of work-in-progress.
STATUS_WEIGHTS = [
    (Order.Status.CLOSED, 20),
    (Order.Status.DELIVERED, 22),
    (Order.Status.SHIPPED, 12),
    (Order.Status.FULFILLMENT, 10),
    (Order.Status.CONFIRMED, 12),
    (Order.Status.DRAFT, 8),
    (Order.Status.CANCELLED, 9),
    (Order.Status.REFUNDED, 7),
]

REVIEW_POOL = [
    (5, "Worth every penny", "I've worn this three times a week since it arrived and it still looks new. The colour is exactly as pictured."),
    (5, "The softest thing I own", "Genuinely lovely against the skin. Sizing is generous — I'd size down for a closer fit."),
    (4, "Beautiful, runs large", "Really lovely quality and a gorgeous shade. I'm usually a M and swapped for an S."),
    (5, "Lived in it on holiday", "Packed small, came out uncreased, and washed beautifully on a cool cycle."),
    (4, "Lovely fabric, slow delivery", "The cloth is genuinely special. Took a week to arrive but worth the wait."),
    (5, "Ordered a second", "Bought another in a different colour the week after. That says it all really."),
    (3, "Lovely but sheer", "Beautifully made, though lighter than I expected — I layer it over a vest."),
    (5, "My go-to now", "Throws over everything and instantly looks considered. Excellent with jeans."),
    (4, "Great weight", "Substantial without being heavy. The ribbed cuffs have held their shape."),
    (5, "Gift that landed well", "Bought for my sister's birthday and she's barely taken it off since."),
    (2, "Not for me", "The quality is clearly there, but the cut sat oddly on me. Returns were painless though."),
    (4, "Quietly excellent", "Nothing flashy — just very well made, which is exactly what I wanted."),
]

ENQUIRIES = [
    ("Sizing between M and L", "I'm between sizes on the Cloud Cashmere Jumper — does it shrink at all after washing?"),
    ("Restock on Soft Lavender?", "The Soft Lavender colourway is out of stock in my size. Any idea when it's back?"),
    ("Gift wrapping", "Is gift wrapping available at checkout, and can you include a handwritten note?"),
    ("Delivery to Ireland", "Do you ship to the Republic of Ireland, and are duties included in the price?"),
    ("Care of merino", "Can the Everyday Merino Crew go in the machine on a wool cycle, or hand wash only?"),
    ("Return started, no email", "I posted a return last Tuesday but haven't had a confirmation email yet."),
    ("Press enquiry", "I write for a slow-fashion newsletter and would love to feature your Scottish mill."),
    ("Wholesale", "We run a small boutique in Bath and would like to discuss stocking your knitwear."),
    ("Faulty seam", "A seam on the sleeve has come loose after three wears. Happy to send a photo."),
    ("Order amendment", "Could I add a second item to an order I placed an hour ago, before it ships?"),
    ("Fabric origin", "Where is the linen milled? I'm trying to buy more European-made pieces."),
    ("Student discount", "Do you offer a student discount, or is the newsletter code the only one?"),
]


def weighted_choice(pairs):
    population, weights = zip(*pairs)
    return random.choices(population, weights=weights, k=1)[0]


class Command(BaseCommand):
    help = "Seed dummy customers, order history, reviews, enquiries and subscribers."

    def add_arguments(self, parser):
        parser.add_argument("--customers", type=int, default=40)
        parser.add_argument("--orders", type=int, default=80)
        parser.add_argument("--reviews", type=int, default=30)
        parser.add_argument("--days", type=int, default=120, help="Spread orders over N days.")
        parser.add_argument(
            "--flush",
            action="store_true",
            help="Delete previously generated dummy activity before seeding.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        random.seed()

        if not Product.objects.exists():
            self.stderr.write(
                self.style.ERROR("No products found — run `manage.py seed_demo` first.")
            )
            return

        if options["flush"]:
            self.flush()

        customers = self.seed_customers(options["customers"])
        self.seed_addresses(customers)
        self.seed_orders(options["orders"], customers, options["days"])
        self.seed_wishlists(customers)
        self.seed_reviews(options["reviews"], customers)
        self.seed_enquiries()
        self.seed_subscribers()

        self.report()

    # ------------------------------------------------------------------ flush

    def flush(self):
        dummy = User.objects.filter(email__endswith=f"@{DUMMY_DOMAIN}")
        counts = (
            Order.objects.count(),
            dummy.count(),
            ContactMessage.objects.count(),
        )
        # Order items, addresses and wishlist rows cascade from these.
        Order.objects.all().delete()
        Review.objects.filter(user__in=dummy).delete()
        dummy.delete()
        ContactMessage.objects.all().delete()
        NewsletterSubscriber.objects.filter(source="dummy").delete()
        self.stdout.write(
            f"Flushed {counts[0]} orders, {counts[1]} dummy customers, {counts[2]} enquiries."
        )

    # -------------------------------------------------------------- customers

    def seed_customers(self, count):
        existing = list(User.objects.filter(email__endswith=f"@{DUMMY_DOMAIN}"))
        now = timezone.now()
        created = 0

        while len(existing) + created < count:
            first = random.choice(FIRST_NAMES)
            last = random.choice(LAST_NAMES)
            index = len(existing) + created + 1
            email = f"{first.lower()}.{last.lower()}{index}@{DUMMY_DOMAIN}"
            if User.objects.filter(email=email).exists():
                created += 1
                continue
            user = User.objects.create_user(
                email=email,
                password="lavender123",
                first_name=first,
                last_name=last,
                phone=f"07{random.randint(100, 999)} {random.randint(100000, 999999)}",
                marketing_opt_in=random.random() < 0.6,
            )
            # Backdate signup so "new customers this week" is meaningful.
            user.date_joined = now - timedelta(
                days=random.randint(0, 540), hours=random.randint(0, 23)
            )
            user.save(update_fields=["date_joined"])
            created += 1

        customers = list(User.objects.filter(email__endswith=f"@{DUMMY_DOMAIN}"))
        self.stdout.write(f"Customers: +{created} (total {len(customers)})")
        return customers

    def seed_addresses(self, customers):
        created = 0
        for customer in customers:
            if customer.addresses.exists():
                continue
            for index in range(random.randint(1, 2)):
                city, postcode_area, county = random.choice(CITIES)
                Address.objects.create(
                    user=customer,
                    label="Home" if index == 0 else "Work",
                    first_name=customer.first_name,
                    last_name=customer.last_name,
                    line1=f"{random.randint(1, 180)} {random.choice(STREETS)}",
                    line2=random.choice(["", "", "Flat 2", "Apt 4B"]),
                    city=city,
                    county=county,
                    postcode=f"{postcode_area} {random.randint(1, 9)}{random.choice('ABDEFGHJLNPQRSTUWXYZ')}{random.choice('ABDEFGHJLNPQRSTUWXYZ')}",
                    country="GB",
                    phone=customer.phone,
                    is_default_shipping=index == 0,
                    is_default_billing=index == 0,
                )
                created += 1
        self.stdout.write(f"Addresses: +{created}")

    # ------------------------------------------------------------------ orders

    def _address_snapshot(self, customer=None):
        city, postcode_area, county = random.choice(CITIES)
        first = customer.first_name if customer else random.choice(FIRST_NAMES)
        last = customer.last_name if customer else random.choice(LAST_NAMES)
        return {
            "first_name": first,
            "last_name": last,
            "line1": f"{random.randint(1, 180)} {random.choice(STREETS)}",
            "line2": "",
            "city": city,
            "county": county,
            "postcode": f"{postcode_area} {random.randint(1, 9)}{random.choice('ABDEFGHJLNPQRSTUWXYZ')}{random.choice('ABDEFGHJLNPQRSTUWXYZ')}",
            "country": "GB",
            "phone": f"07{random.randint(100, 999)} {random.randint(100000, 999999)}",
        }

    def seed_orders(self, count, customers, days):
        variants = list(
            ProductVariant.objects.select_related("colour__product", "size").filter(
                is_active=True
            )
        )
        if not variants:
            self.stdout.write(self.style.WARNING("No variants — skipping orders."))
            return

        discounts = list(Discount.objects.filter(is_active=True))
        now = timezone.now()
        threshold = Decimal(settings.FREE_SHIPPING_THRESHOLD)

        # Oldest first, so order numbers ascend with time like real trading.
        offsets = sorted(
            (random.uniform(0, days) for _ in range(count)), reverse=True
        )

        created = 0
        for offset in offsets:
            placed = now - timedelta(days=offset)
            customer = random.choice(customers) if random.random() < 0.7 else None
            if customer and customer.date_joined > placed:
                # Don't let an order predate the account that placed it.
                customer = None

            chosen = random.sample(variants, k=random.randint(1, 4))
            lines = []
            subtotal = Decimal("0")
            for variant in chosen:
                quantity = random.choices([1, 2, 3], weights=[72, 22, 6], k=1)[0]
                unit_price = money(variant.price)
                line_total = money(unit_price * quantity)
                subtotal += line_total
                lines.append((variant, quantity, unit_price, line_total))
            subtotal = money(subtotal)

            discount_total = Decimal("0.00")
            discount_code = ""
            if discounts and random.random() < 0.22:
                discount = random.choice(discounts)
                ok, _ = discount.is_valid(subtotal)
                if ok:
                    discount_code = discount.code
                    discount_total = discount.amount_for(subtotal)

            method = random.choices(
                [Order.ShippingMethod.STANDARD, Order.ShippingMethod.EXPRESS],
                weights=[80, 20],
                k=1,
            )[0]
            if subtotal >= threshold:
                shipping_total = Decimal("0.00")
            else:
                shipping_total = money(
                    settings.EXPRESS_SHIPPING_FEE
                    if method == Order.ShippingMethod.EXPRESS
                    else settings.STANDARD_SHIPPING_FEE
                )

            status = weighted_choice(STATUS_WEIGHTS)
            if status == Order.Status.DRAFT:
                payment_status = Order.PaymentStatus.UNPAID
            elif status == Order.Status.REFUNDED:
                payment_status = Order.PaymentStatus.REFUNDED
            elif status == Order.Status.CANCELLED:
                payment_status = random.choice(
                    [Order.PaymentStatus.UNPAID, Order.PaymentStatus.REFUNDED]
                )
            else:
                payment_status = Order.PaymentStatus.PAID

            shipping_address = self._address_snapshot(customer)
            order = Order.objects.create(
                user=customer,
                email=customer.email if customer else self._guest_email(shipping_address),
                phone=shipping_address["phone"],
                status=status,
                payment_status=payment_status,
                payment_ref=(
                    f"mock_pi_{random.getrandbits(96):024x}"
                    if payment_status != Order.PaymentStatus.UNPAID
                    else ""
                ),
                payment_provider="mock" if payment_status != Order.PaymentStatus.UNPAID else "",
                subtotal=subtotal,
                discount_total=discount_total,
                shipping_total=shipping_total,
                tax_total=Decimal("0.00"),
                grand_total=money(subtotal - discount_total + shipping_total),
                currency=settings.DEFAULT_CURRENCY,
                discount_code=discount_code,
                shipping_method=method,
                shipping_address=shipping_address,
                billing_address=shipping_address,
                customer_note=random.choice(
                    ["", "", "", "Please leave with a neighbour if out.", "Gift — no invoice please."]
                ),
                tracking_number=(
                    f"RM{random.randint(100000000, 999999999)}GB"
                    if status
                    in {Order.Status.SHIPPED, Order.Status.DELIVERED, Order.Status.CLOSED}
                    else ""
                ),
                placed_at=placed,
                # These settled long ago; stock already reconciled either way.
                stock_released=status in {Order.Status.CANCELLED, Order.Status.REFUNDED},
            )

            for variant, quantity, unit_price, line_total in lines:
                image = variant.colour.primary_image
                OrderItem.objects.create(
                    order=order,
                    variant=variant,
                    product_slug=variant.colour.product.slug,
                    product_name=variant.colour.product.name,
                    colour_name=variant.colour.name,
                    size_name=variant.size.name,
                    sku=variant.sku,
                    image_url=image.image.url if image else "",
                    unit_price=unit_price,
                    quantity=quantity,
                    line_total=line_total,
                )

            # created_at is auto_now_add, so backdate it after the fact —
            # the dashboard's revenue KPIs read this field.
            Order.objects.filter(pk=order.pk).update(created_at=placed)

            # Synthesise an activity log so the order-detail timeline isn't empty.
            if status in Order.LIFECYCLE:
                chain = Order.LIFECYCLE[: Order.LIFECYCLE.index(status) + 1]
            else:  # cancelled / refunded came off the confirmed stage
                chain = [Order.Status.DRAFT, Order.Status.CONFIRMED, status]
            prev = ""
            for step in chain:
                order.status_events.create(
                    from_status=prev,
                    to_status=step,
                    actor="system" if prev == "" else "admin@lavenderhill.test",
                )
                prev = step

            if discount_code:
                Discount.objects.filter(code=discount_code).update(
                    used_count=F("used_count") + 1
                )
            created += 1

        self.stdout.write(f"Orders: +{created} (total {Order.objects.count()})")

    @staticmethod
    def _guest_email(address):
        return (
            f"{address['first_name'].lower()}.{address['last_name'].lower()}"
            f"{random.randint(1, 99)}@{DUMMY_DOMAIN}"
        )

    # --------------------------------------------------------------- wishlists

    def seed_wishlists(self, customers):
        products = list(Product.objects.filter(is_active=True))
        created = 0
        for customer in customers:
            if random.random() < 0.45:
                continue
            for product in random.sample(products, k=random.randint(1, 5)):
                _, made = WishlistItem.objects.get_or_create(
                    user=customer, product=product
                )
                created += int(made)
        self.stdout.write(f"Wishlist items: +{created}")

    # ----------------------------------------------------------------- reviews

    def seed_reviews(self, count, customers):
        products = list(Product.objects.filter(is_active=True))
        created = pending = 0
        now = timezone.now()

        for _ in range(count):
            product = random.choice(products)
            rating, title, body = random.choice(REVIEW_POOL)
            customer = random.choice(customers) if random.random() < 0.7 else None
            # Roughly a quarter sit unapproved so the moderation queue isn't empty.
            approved = random.random() > 0.25

            review = Review.objects.create(
                product=product,
                user=customer,
                author_name=(
                    f"{customer.first_name} {customer.last_name[0]}."
                    if customer
                    else f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)[0]}."
                ),
                author_location=random.choice(CITIES)[0],
                rating=rating,
                title=title,
                body=body,
                is_verified=bool(customer),
                is_approved=approved,
                status="approved" if approved else "pending",
            )
            Review.objects.filter(pk=review.pk).update(
                created_at=now - timedelta(days=random.randint(0, 200))
            )
            created += 1
            pending += int(not approved)

        for product in products:
            product.recalculate_rating()

        self.stdout.write(f"Reviews: +{created} ({pending} awaiting moderation)")

    # --------------------------------------------------------------- enquiries

    def seed_enquiries(self):
        now = timezone.now()
        created = 0
        for subject, message in ENQUIRIES:
            first, last = random.choice(FIRST_NAMES), random.choice(LAST_NAMES)
            enquiry = ContactMessage.objects.create(
                name=f"{first} {last}",
                email=f"{first.lower()}.{last.lower()}@{DUMMY_DOMAIN}",
                subject=subject,
                message=message,
                is_handled=random.random() < 0.4,
            )
            ContactMessage.objects.filter(pk=enquiry.pk).update(
                created_at=now - timedelta(days=random.randint(0, 45))
            )
            created += 1
        self.stdout.write(f"Contact enquiries: +{created}")

    # ------------------------------------------------------------- subscribers

    def seed_subscribers(self):
        now = timezone.now()
        created = 0
        for index in range(45):
            first, last = random.choice(FIRST_NAMES), random.choice(LAST_NAMES)
            email = f"{first.lower()}.{last.lower()}{index}@{DUMMY_DOMAIN}"
            subscriber, made = NewsletterSubscriber.objects.get_or_create(
                email=email,
                defaults={
                    "source": "dummy",
                    "is_active": random.random() < 0.9,
                },
            )
            if made:
                NewsletterSubscriber.objects.filter(pk=subscriber.pk).update(
                    created_at=now - timedelta(days=random.randint(0, 300))
                )
                created += 1
        self.stdout.write(f"Newsletter subscribers: +{created}")

    # ------------------------------------------------------------------ report

    def report(self):
        self.stdout.write(self.style.SUCCESS("\nDummy data ready."))
        paid = Order.objects.exclude(
            status__in=[Order.Status.CANCELLED, Order.Status.REFUNDED]
        )
        revenue = sum((o.grand_total for o in paid), Decimal("0"))
        self.stdout.write(
            f"  {User.objects.filter(is_staff=False).count()} customers · "
            f"{Order.objects.count()} orders · "
            f"£{revenue:,.2f} lifetime revenue"
        )
        self.stdout.write(
            f"  {Review.objects.filter(is_approved=False).count()} reviews to moderate · "
            f"{ContactMessage.objects.filter(is_handled=False).count()} open enquiries · "
            f"{NewsletterSubscriber.objects.filter(is_active=True).count()} subscribers"
        )
        self.stdout.write("  Every dummy customer signs in with: lavender123")
