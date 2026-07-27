"""Populate the store with demo data that mirrors the Figma design.

    py manage.py seed_demo            # add missing records, keep what exists
    py manage.py seed_demo --flush    # wipe catalogue/content first
"""

import random
from datetime import timedelta
from decimal import Decimal
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from PIL import Image, ImageDraw, ImageFont

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
    HomeSection,
    JournalCategory,
    JournalPost,
    NewsletterSubscriber,
    SiteSettings,
)
from apps.orders.models import Discount

User = get_user_model()

# Brand palette from the Figma design system.
CREAM = (246, 243, 238)
INK = (42, 41, 37)
LAVENDER = (156, 134, 180)
LAVENDER_DEEP = (110, 90, 134)

SIZES = [("XS", 1), ("S", 2), ("M", 3), ("L", 4), ("XL", 5), ("One Size", 6)]

FABRICS = [
    ("Cashmere", "Feather-light Grade-A Mongolian cashmere, spun for warmth without weight."),
    ("Linen", "European flax linen that softens with every wash."),
    ("Modal", "Beechwood modal with a liquid drape and a cool hand."),
    ("Organic Cotton", "GOTS-certified cotton, grown without synthetic pesticides."),
    ("Merino", "Traceable merino wool — breathable, temperature-regulating, non-itch."),
]

CATEGORIES = [
    ("Knitwear", "Cashmere and merino pieces made to be lived in.", None),
    ("Loungewear", "Softness for slow mornings and long evenings.", None),
    ("Dresses", "Easy silhouettes in fabrics that move with you.", None),
    ("Tops & Shirts", "Considered basics and quiet statement pieces.", None),
    ("Trousers", "Relaxed tailoring and drawstring ease.", None),
    ("Accessories", "The finishing touch — scarves, socks and sleep masks.", None),
]

COLLECTIONS = [
    ("New Arrivals", "The latest additions to the Lavender Hill wardrobe."),
    ("Bestsellers", "The pieces our community returns to season after season."),
    ("Sale", "Considered pieces at considered prices."),
    ("The Gift Guide", "Thoughtful gifting, beautifully wrapped."),
]

COLOURWAYS = [
    ("Oat Melange", "#DCD3C6"),
    ("Soft Lavender", "#DDD2E6"),
    ("Chalk", "#F2EFE9"),
    ("Slate", "#6F7169"),
    ("Clay", "#B98A76"),
    ("Ink", "#2A2925"),
    ("Sage", "#A8B3A0"),
    ("Blush", "#E5CFC8"),
]

PRODUCTS = [
    ("The Cloud Cashmere Jumper", "Knitwear", "Cashmere", 245, 295,
     "A relaxed, dropped-shoulder jumper knitted from feather-light cashmere. Cut generously so it falls softly at the hip."),
    ("Everyday Merino Crew", "Knitwear", "Merino", 135, None,
     "A fine-gauge merino crew neck that works alone or as a layer. Ribbed cuffs hold their shape wash after wash."),
    ("Ribbed Cashmere Cardigan", "Knitwear", "Cashmere", 265, None,
     "An open-front cardigan with deep patch pockets, made to be thrown over everything."),
    ("The Weekend Knit Vest", "Knitwear", "Merino", 110, 140,
     "A sleeveless knit vest with a clean neckline — the easiest layer in the wardrobe."),
    ("Modal Lounge Set", "Loungewear", "Modal", 165, None,
     "A matching long-sleeve top and wide-leg trouser in cool, fluid modal."),
    ("Brushed Cotton Pyjama Shirt", "Loungewear", "Organic Cotton", 88, None,
     "A soft brushed-cotton pyjama shirt with mother-of-pearl buttons and piped edges."),
    ("Cashmere Lounge Pant", "Loungewear", "Cashmere", 195, 235,
     "Drawstring cashmere trousers with a tapered leg. Indulgent, and quietly practical."),
    ("The Sunday Robe", "Loungewear", "Modal", 145, None,
     "A calf-length robe with a wrap tie and generous sleeves."),
    ("Linen Midi Dress", "Dresses", "Linen", 175, None,
     "A column midi dress in washed European linen, with side seam pockets and a tie waist."),
    ("The Tiered Cotton Dress", "Dresses", "Organic Cotton", 155, 185,
     "Soft tiers in organic cotton poplin, with a scooped neck and elasticated sleeves."),
    ("Modal Slip Dress", "Dresses", "Modal", 125, None,
     "A bias-cut slip that skims rather than clings. Adjustable straps."),
    ("Long-Sleeve Wrap Dress", "Dresses", "Modal", 185, None,
     "A true wrap dress with a deep V and a self-tie waist."),
    ("The Everyday Linen Shirt", "Tops & Shirts", "Linen", 115, None,
     "An oversized linen shirt with a relaxed collar and a curved hem."),
    ("Organic Cotton Tee", "Tops & Shirts", "Organic Cotton", 45, None,
     "A heavyweight cotton tee cut a little longer, in a shape that holds."),
    ("Silk-Touch Modal Blouse", "Tops & Shirts", "Modal", 128, 155,
     "A fluid blouse with a soft shoulder and covered buttons."),
    ("Merino Roll Neck", "Tops & Shirts", "Merino", 145, None,
     "A slim roll neck in extra-fine merino — a base layer that reads as a top."),
    ("Wide-Leg Linen Trouser", "Trousers", "Linen", 145, None,
     "High-waisted linen trousers with pressed pleats and a wide, easy leg."),
    ("The Drawstring Trouser", "Trousers", "Organic Cotton", 115, 140,
     "A relaxed cotton twill trouser with a soft drawstring waist and deep pockets."),
    ("Tapered Modal Trouser", "Trousers", "Modal", 135, None,
     "A tapered, elasticated-waist trouser that dresses up or down."),
    ("Cashmere Wide-Leg Pant", "Trousers", "Cashmere", 225, None,
     "Everything you want from loungewear, cut like proper trousers."),
    ("Cashmere Travel Wrap", "Accessories", "Cashmere", 185, 220,
     "An oversized cashmere wrap that doubles as a blanket. Folds to nothing."),
    ("Ribbed Cashmere Socks", "Accessories", "Cashmere", 48, None,
     "Ribbed bed socks in the softest cashmere, with a loose non-binding cuff."),
    ("Silk Sleep Mask", "Accessories", "Modal", 38, None,
     "A padded sleep mask with an adjustable band and a soft-touch lining."),
    ("Linen Scarf", "Accessories", "Linen", 65, None,
     "A lightweight linen scarf with hand-knotted fringing."),
]

REVIEWS = [
    (5, "Worth every penny", "I've worn this three times a week since it arrived and it still looks new. The colour is exactly as pictured.", "Eleanor R.", "London"),
    (5, "So soft", "Genuinely the softest thing I own. Sizing is generous — I'd size down for a closer fit.", "Priya S.", "Bristol"),
    (4, "Beautiful, runs large", "Lovely quality and a gorgeous colour. I'm usually a M and swapped for an S.", "Hannah B.", "Edinburgh"),
    (5, "My new favourite", "Bought it for a trip and lived in it. Washes beautifully on a cool cycle.", "Marta K.", "Manchester"),
    (4, "Lovely fabric", "The fabric is really special. Took a week to arrive but well worth the wait.", "Sophie T.", "Leeds"),
    (5, "Buying a second", "Ordered another in a different colour the week after. Says it all.", "Ama O.", "Birmingham"),
]

JOURNAL = [
    ("How to care for cashmere", "Care", "A few small habits keep cashmere looking new for years — here's what we do.", 5),
    ("The case for a smaller wardrobe", "Slow Living", "Why buying less, better, is the most sustainable thing you can do.", 6),
    ("Meet the mill: our Scottish knitters", "Provenance", "A visit to the family-run mill that has knitted our cashmere for six years.", 8),
    ("Five ways to wear linen past summer", "Styling", "Linen isn't only for August. Here's how we layer it into autumn.", 4),
    ("What GOTS certification actually means", "Provenance", "The certification behind our organic cotton, explained plainly.", 5),
    ("Building a capsule for winter", "Styling", "Nine pieces that carry you from November through to March.", 7),
]


class Command(BaseCommand):
    help = "Seed the database with demo catalogue, content and orders."

    def add_arguments(self, parser):
        parser.add_argument(
            "--flush",
            action="store_true",
            help="Delete existing catalogue and content data before seeding.",
        )
        parser.add_argument(
            "--no-images", action="store_true", help="Skip image generation entirely."
        )
        parser.add_argument(
            "--text-images",
            action="store_true",
            help="Use the drawn text placeholders only — don't download real photos "
            "(useful offline). By default real model photography is fetched.",
        )

    def handle(self, *args, **options):
        random.seed(20260722)
        self.make_images = not options["no_images"]

        # Seed the catalogue in one transaction. Drawing the placeholder cards here
        # guarantees every record has *an* image even offline; real photography is
        # then layered on top afterwards (see below).
        with transaction.atomic():
            if options["flush"]:
                self.stdout.write("Flushing existing demo data…")
                Review.objects.all().delete()
                ProductImage.objects.all().delete()
                ProductVariant.objects.all().delete()
                ProductColour.objects.all().delete()
                Product.objects.all().delete()
                Category.objects.all().delete()
                Collection.objects.all().delete()
                Fabric.objects.all().delete()
                HomeSection.objects.all().delete()
                JournalPost.objects.all().delete()
                JournalCategory.objects.all().delete()

            sizes = self.seed_sizes()
            fabrics = self.seed_fabrics()
            categories = self.seed_categories()
            collections = self.seed_collections()
            self.seed_products(sizes, fabrics, categories, collections)
            self.seed_journal()
            self.seed_content(collections)
            self.seed_discounts()
            self.seed_users()

        self.stdout.write(self.style.SUCCESS("\nSeed complete."))
        self.stdout.write(
            f"  {Product.objects.count()} products · "
            f"{ProductColour.objects.count()} colourways · "
            f"{ProductVariant.objects.count()} SKUs · "
            f"{ProductVariant.objects.filter(stock_quantity__gt=0).count()} in stock"
        )
        self.stdout.write("  Demo staff login: staff@lavenderhill.test / lavender123")
        self.stdout.write("  Demo customer:    hello@lavenderhill.test / lavender123")
        self.stdout.write("  Promo code:       SOFT10 (10% off)")

        # Real model photography by default — swap it over the placeholder cards.
        # Runs after the transaction commits so a slow download never holds a lock,
        # and a network failure leaves the placeholders in place rather than
        # rolling back the whole seed.
        if self.make_images and not options["text_images"]:
            self.stdout.write("\nFetching real model photography…")
            try:
                call_command("seed_images", verbosity=0)
                self.stdout.write(self.style.SUCCESS("  Real images applied."))
            except Exception as exc:  # offline / download issue — keep placeholders
                self.stdout.write(
                    self.style.WARNING(
                        f"  Couldn't fetch real images ({exc}); kept text placeholders. "
                        "Re-run `py manage.py seed_images` when online."
                    )
                )

    # ------------------------------------------------------------ placeholders

    def placeholder(self, label, sublabel, size=(900, 1125), bg=CREAM, accent=LAVENDER):
        """Generate a branded placeholder image so the storefront looks populated."""
        image = Image.new("RGB", size, bg)
        draw = ImageDraw.Draw(image)
        width, height = size

        # Soft accent band and a thin frame — echoes the Figma product cards.
        draw.rectangle([0, int(height * 0.62), width, int(height * 0.66)], fill=accent)
        draw.rectangle([24, 24, width - 24, height - 24], outline=(228, 223, 214), width=2)

        try:
            title_font = ImageFont.truetype("georgia.ttf", int(width * 0.062))
            small_font = ImageFont.truetype("arial.ttf", int(width * 0.028))
        except OSError:
            title_font = ImageFont.load_default()
            small_font = ImageFont.load_default()

        def centred(text, y, font, fill):
            box = draw.textbbox((0, 0), text, font=font)
            draw.text(((width - (box[2] - box[0])) / 2, y), text, font=font, fill=fill)

        centred(label[:22], int(height * 0.40), title_font, INK)
        centred(sublabel.upper()[:28], int(height * 0.72), small_font, LAVENDER_DEEP)
        centred("LAVENDER HILL", int(height * 0.78), small_font, (122, 117, 108))

        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=82)
        return ContentFile(buffer.getvalue())

    # ------------------------------------------------------------------ seeds

    def seed_sizes(self):
        sizes = []
        for name, order in SIZES:
            size, _ = Size.objects.get_or_create(name=name, defaults={"sort_order": order})
            sizes.append(size)
        self.stdout.write(f"Sizes: {len(sizes)}")
        return {s.name: s for s in sizes}

    def seed_fabrics(self):
        fabrics = {}
        for index, (name, description) in enumerate(FABRICS):
            fabric, created = Fabric.objects.get_or_create(
                name=name, defaults={"description": description, "sort_order": index}
            )
            if created and self.make_images:
                fabric.image.save(
                    f"fabric-{fabric.slug}.jpg",
                    self.placeholder(name, "Shop by fabric", size=(800, 800)),
                    save=True,
                )
            fabrics[name] = fabric
        self.stdout.write(f"Fabrics: {len(fabrics)}")
        return fabrics

    def seed_categories(self):
        categories = {}
        for index, (name, description, parent) in enumerate(CATEGORIES):
            category, created = Category.objects.get_or_create(
                name=name,
                defaults={"description": description, "sort_order": index},
            )
            if created and self.make_images:
                category.image.save(
                    f"category-{category.slug}.jpg",
                    self.placeholder(name, "Shop the category", size=(900, 900)),
                    save=True,
                )
            categories[name] = category
        self.stdout.write(f"Categories: {len(categories)}")
        return categories

    def seed_collections(self):
        collections = {}
        for index, (name, description) in enumerate(COLLECTIONS):
            collection, created = Collection.objects.get_or_create(
                name=name, defaults={"description": description, "sort_order": index}
            )
            if created and self.make_images:
                collection.hero_image.save(
                    f"collection-{collection.slug}.jpg",
                    self.placeholder(name, "Collection", size=(1400, 800)),
                    save=True,
                )
            collections[name] = collection
        self.stdout.write(f"Collections: {len(collections)}")
        return collections

    def seed_products(self, sizes, fabrics, categories, collections):
        created_count = 0
        clothing_sizes = [sizes[n] for n in ("XS", "S", "M", "L", "XL")]

        for index, (name, category_name, fabric_name, price, compare, description) in enumerate(
            PRODUCTS
        ):
            if Product.objects.filter(name=name).exists():
                continue

            is_accessory = category_name == "Accessories"
            product = Product.objects.create(
                name=name,
                description=description,
                category=categories[category_name],
                base_price=Decimal(price),
                compare_at_price=Decimal(compare) if compare else None,
                is_active=True,
                is_new_in=index % 4 == 0,
                is_bestseller=index % 5 == 0,
                is_featured=index % 6 == 0,
                composition=f"100% {fabric_name.lower()}. Made in Portugal.",
                care_instructions=(
                    "Hand wash cool or dry clean. Reshape while damp and dry flat, "
                    "away from direct heat."
                ),
                sustainability_note=(
                    "Made in a family-run mill on renewable energy, with offcuts "
                    "returned to the yarn supply."
                ),
                meta_title=f"{name} | Lavender Hill Clothing",
                meta_description=description[:160],
                sort_order=index,
            )
            product.fabrics.add(fabrics[fabric_name])

            product.collections.add(collections["New Arrivals" if index % 4 == 0 else "Bestsellers"])
            if compare:
                product.collections.add(collections["Sale"])
            if is_accessory:
                product.collections.add(collections["The Gift Guide"])

            # 2–4 colourways per product.
            palette = random.sample(COLOURWAYS, k=random.randint(2, 4))
            for colour_index, (colour_name, hex_code) in enumerate(palette):
                colour = ProductColour.objects.create(
                    product=product,
                    name=colour_name,
                    swatch_hex=hex_code,
                    sort_order=colour_index,
                )

                if self.make_images:
                    for shot in range(2):
                        image = ProductImage(
                            colour=colour,
                            alt_text=f"{name} in {colour_name}",
                            sort_order=shot,
                            is_primary=shot == 0,
                        )
                        image.image.save(
                            f"{product.slug}-{colour.pk}-{shot}.jpg",
                            self.placeholder(
                                colour_name,
                                name if shot == 0 else "Detail",
                                bg=CREAM if shot == 0 else (242, 239, 233),
                            ),
                            save=False,
                        )
                        image.save()

                variant_sizes = [sizes["One Size"]] if is_accessory else clothing_sizes
                for size in variant_sizes:
                    # A realistic spread: most sizes stocked, a few low or sold out.
                    roll = random.random()
                    if roll < 0.08:
                        stock = 0
                    elif roll < 0.22:
                        stock = random.randint(1, 4)
                    else:
                        stock = random.randint(6, 40)
                    ProductVariant.objects.create(
                        colour=colour, size=size, stock_quantity=stock
                    )

            # A handful of approved reviews on most products.
            for rating, title, body, author, location in random.sample(
                REVIEWS, k=random.randint(0, 3)
            ):
                Review.objects.create(
                    product=product,
                    author_name=author,
                    author_location=location,
                    rating=rating,
                    title=title,
                    body=body,
                    is_verified=True,
                    is_approved=True,
                    status="approved",
                )
            product.recalculate_rating()
            created_count += 1

        self.stdout.write(f"Products: +{created_count} (total {Product.objects.count()})")

    def seed_journal(self):
        categories = {}
        for index, name in enumerate(["Care", "Slow Living", "Provenance", "Styling"]):
            categories[name], _ = JournalCategory.objects.get_or_create(
                name=name, defaults={"sort_order": index}
            )

        now = timezone.now()
        for index, (title, category, excerpt, minutes) in enumerate(JOURNAL):
            if JournalPost.objects.filter(title=title).exists():
                continue
            post = JournalPost.objects.create(
                title=title,
                category=categories[category],
                excerpt=excerpt,
                body=(
                    f"<p>{excerpt}</p>"
                    "<p>At Lavender Hill we design for longevity — pieces that earn their "
                    "place in your wardrobe and stay there. That starts with the fibre and "
                    "ends with how you care for it.</p>"
                    "<h2>Where it begins</h2>"
                    "<p>Every yarn we use is chosen for how it feels on the fifth wear, not "
                    "the first. We work with mills we have visited, and we keep our runs "
                    "small so nothing is made that isn't wanted.</p>"
                    "<h2>Making it last</h2>"
                    "<p>Wash cool, dry flat, and store folded rather than hung. Small habits, "
                    "compounded over years.</p>"
                ),
                author="The Lavender Hill Studio",
                read_minutes=minutes,
                is_published=True,
                is_featured=index == 0,
                published_at=now - timedelta(days=index * 9 + 3),
            )
            if self.make_images:
                post.hero_image.save(
                    f"journal-{post.slug}.jpg",
                    self.placeholder(category, title, size=(1400, 900)),
                    save=True,
                )
        self.stdout.write(f"Journal posts: {JournalPost.objects.count()}")

    def seed_content(self, collections):
        site = SiteSettings.load()
        site.announcement_text = "Complimentary UK delivery on orders over £50"
        site.free_shipping_threshold = Decimal("50")
        # Icon keys match the storefront's UspItem union (truck|returns|leaf|lock).
        site.usp_items = [
            {"icon": "truck", "label": "Free UK delivery over £50"},
            {"icon": "returns", "label": "Free 30-day returns"},
            {"icon": "leaf", "label": "Sustainably & ethically made"},
            {"icon": "lock", "label": "Secure checkout"},
        ]
        site.footer_links = [
            {
                "title": "Shop",
                "links": [
                    {"label": "New in", "href": "/new-in"},
                    {"label": "Knitwear", "href": "/collections/knitwear"},
                    {"label": "Loungewear", "href": "/collections/loungewear"},
                    {"label": "Sale", "href": "/sale"},
                ],
            },
            {
                "title": "Help",
                "links": [
                    {"label": "FAQs", "href": "/faqs"},
                    {"label": "Delivery & returns", "href": "/faqs#delivery"},
                    {"label": "Size guide", "href": "/faqs#sizing"},
                    {"label": "Contact us", "href": "/contact"},
                ],
            },
            {
                "title": "About",
                "links": [
                    {"label": "Our story", "href": "/about"},
                    {"label": "Sustainability", "href": "/about#sustainability"},
                    {"label": "Journal", "href": "/journal"},
                ],
            },
        ]
        site.faqs = [
            {"group": "Delivery", "question": "How long does delivery take?",
             "answer": "Standard UK delivery arrives in 3–5 working days. Express arrives in 1–2."},
            {"group": "Delivery", "question": "Do you ship internationally?",
             "answer": "We ship across the EU and to the US. Duties are calculated at checkout."},
            {"group": "Returns", "question": "What is your returns policy?",
             "answer": "Return anything unworn within 30 days for a full refund, free of charge."},
            {"group": "Sizing", "question": "How do your pieces fit?",
             "answer": "Our knitwear is cut generously. If you're between sizes, we'd size down."},
            {"group": "Care", "question": "How should I wash cashmere?",
             "answer": "Hand wash cool with a gentle detergent, reshape while damp, and dry flat."},
        ]
        site.social_instagram = "https://instagram.com/lavenderhill"
        site.social_facebook = "https://facebook.com/lavenderhill"
        site.social_pinterest = "https://pinterest.com/lavenderhill"
        site.contact_email = "hello@lavenderhill.example"
        site.contact_phone = "+44 20 7946 0102"
        site.studio_address = "Unit 4, Lavender Hill Studios\nLondon SW11 5RW\nUnited Kingdom"
        site.about_body = (
            "<p>Lavender Hill began with a single cashmere jumper and a stubborn belief that "
            "clothes should be made to last.</p>"
            "<p>We design in London and make in small, family-run mills across Portugal and "
            "Scotland — places we visit, with people we know.</p>"
        )
        site.save()

        blocks = [
            {
                "kind": HomeSection.Kind.HERO,
                "eyebrow": "Autumn / Winter",
                "title": "Softness, considered",
                "subtitle": "Cashmere and merino knitted in small runs, made to be worn for years.",
                "cta_label": "Shop new in",
                "cta_href": "/new-in",
                "sort_order": 0,
            },
            {
                "kind": HomeSection.Kind.CATEGORY_TILES,
                "title": "Shop by category",
                "sort_order": 1,
                "payload": {"categories": ["knitwear", "loungewear", "dresses", "accessories"]},
            },
            {
                "kind": HomeSection.Kind.COLLECTION_ROW,
                "eyebrow": "Just landed",
                "title": "New arrivals",
                "cta_label": "View all",
                "cta_href": "/new-in",
                "collection": collections["New Arrivals"],
                "payload": {"limit": 4},
                "sort_order": 2,
            },
            {
                "kind": HomeSection.Kind.EDITORIAL,
                "eyebrow": "The Cloud Collection",
                "title": "Knitted to be lived in",
                "subtitle": "Feather-light cashmere in a relaxed, dropped-shoulder cut.",
                "cta_label": "Shop knitwear",
                "cta_href": "/collections/knitwear",
                "sort_order": 3,
            },
            {
                "kind": HomeSection.Kind.FABRIC_ROW,
                "title": "Shop by fabric",
                "subtitle": "Five fibres, chosen for how they feel on the fiftieth wear.",
                "sort_order": 4,
            },
            {
                "kind": HomeSection.Kind.COLLECTION_ROW,
                "eyebrow": "Loved by you",
                "title": "Bestsellers",
                "cta_label": "Shop bestsellers",
                "cta_href": "/collections/bestsellers",
                "collection": collections["Bestsellers"],
                "payload": {"limit": 4},
                "sort_order": 5,
            },
            {
                "kind": HomeSection.Kind.SUSTAINABILITY,
                "eyebrow": "Our promise",
                "title": "Made well, made less",
                "subtitle": "Small runs, traceable fibres, and mills we've stood in ourselves.",
                "cta_label": "Read our story",
                "cta_href": "/about",
                "sort_order": 6,
            },
            {
                "kind": HomeSection.Kind.JOURNAL,
                "title": "From the journal",
                "cta_label": "Read the journal",
                "cta_href": "/journal",
                "sort_order": 7,
                "payload": {"limit": 3},
            },
            {
                "kind": HomeSection.Kind.INSTAGRAM,
                "title": "@lavenderhill",
                "subtitle": "Tag us to be featured.",
                "cta_href": "https://instagram.com/lavenderhill",
                "sort_order": 8,
            },
        ]

        for block in blocks:
            if HomeSection.objects.filter(kind=block["kind"], sort_order=block["sort_order"]).exists():
                continue
            section = HomeSection.objects.create(**block)
            if self.make_images and section.kind in {
                HomeSection.Kind.HERO,
                HomeSection.Kind.EDITORIAL,
                HomeSection.Kind.SUSTAINABILITY,
            }:
                section.image.save(
                    f"home-{section.kind}.jpg",
                    self.placeholder(section.title, section.eyebrow or "Lavender Hill", size=(1600, 900)),
                    save=True,
                )
        self.stdout.write(f"Homepage blocks: {HomeSection.objects.count()}")

        for email in ["ada@example.com", "beatrice@example.com", "chloe@example.com"]:
            NewsletterSubscriber.objects.get_or_create(email=email, defaults={"source": "seed"})

    def seed_discounts(self):
        Discount.objects.get_or_create(
            code="SOFT10",
            defaults={
                "description": "10% off your first order",
                "kind": Discount.Kind.PERCENT,
                "value": Decimal("10"),
                "is_active": True,
                "usage_limit": 500,
            },
        )
        Discount.objects.get_or_create(
            code="WELCOME15",
            defaults={
                "description": "£15 off orders over £120",
                "kind": Discount.Kind.FIXED,
                "value": Decimal("15"),
                "min_spend": Decimal("120"),
                "is_active": True,
            },
        )
        self.stdout.write(f"Discounts: {Discount.objects.count()}")

    def seed_users(self):
        # Profiles mirror what the sign-up flow now captures (phone is stored
        # E.164-normalised, exactly as RegisterSerializer would produce it), so
        # the demo accounts look like real registrations in "My account".
        if not User.objects.filter(email="staff@lavenderhill.test").exists():
            User.objects.create_user(
                email="staff@lavenderhill.test",
                password="lavender123",
                first_name="Studio",
                last_name="Team",
                phone="+447700900456",
                location="London",
                postcode="EC2A 4NE",
                country="GB",
                is_staff=True,
            )
        if not User.objects.filter(email="hello@lavenderhill.test").exists():
            User.objects.create_user(
                email="hello@lavenderhill.test",
                password="lavender123",
                first_name="Eleanor",
                last_name="Reid",
                phone="+447700900123",
                location="London",
                postcode="SW1A 1AA",
                country="GB",
                marketing_opt_in=True,
            )
        self.stdout.write(f"Users: {User.objects.count()}")
