"""Replace placeholder imagery with real fashion photography.

`seed_demo` generates flat, branded placeholder cards so the store works with no
network. This command swaps them for curated photographs of people modelling
clothing (see `apps/catalog/imagery.py`), which is what a womenswear storefront
should actually look like.

    py manage.py seed_images                 # everything
    py manage.py seed_images --only products # products | categories | fabrics |
                                             # collections | journal | home
    py manage.py seed_images --force         # re-download even if already done

Images are downloaded once into MEDIA_ROOT, so the storefront serves them from
Django afterwards and works offline. Touches imagery only — never orders,
customers or stock.
"""

import urllib.error
import urllib.request
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.catalog import imagery
from apps.catalog.models import Category, Collection, Fabric, Product, ProductImage
from apps.marketing.models import HomeSection, JournalPost

USER_AGENT = "LavenderHillSeeder/1.0 (+local development seed)"
TIMEOUT = 30

GROUPS = ("categories", "fabrics", "collections", "products", "journal", "home")


class Command(BaseCommand):
    help = "Download curated model photography over the generated placeholders."

    def add_arguments(self, parser):
        parser.add_argument(
            "--only",
            choices=GROUPS,
            action="append",
            help="Limit to one or more groups (repeatable).",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Re-download images that already look like real photography.",
        )

    def handle(self, *args, **options):
        self.force = options["force"]
        self.downloaded = 0
        self.failed = 0
        self._cache: dict[str, bytes] = {}
        # Persistent on-disk cache: photos are fetched from Unsplash once and
        # reused forever, so re-seeds (even a SEED_DEMO=1 wipe on every boot) are
        # instant and offline, and never hit a download rate limit.
        self.cache_dir = Path(settings.BASE_DIR) / ".image_cache"
        self.cache_dir.mkdir(exist_ok=True)

        groups = options["only"] or GROUPS
        for group in groups:
            getattr(self, f"do_{group}")()

        if self.failed:
            self.stdout.write(
                self.style.WARNING(
                    f"\n{self.downloaded} image(s) applied, {self.failed} download(s) failed. "
                    "Re-run to retry — existing placeholders were left in place."
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(f"\n{self.downloaded} image(s) applied.")
            )

    # ------------------------------------------------------------- downloading

    def fetch(self, photo_id: str, width: int, height: int) -> ContentFile | None:
        """Return a photo's bytes: from memory, then disk cache, then the network."""
        url = imagery.photo_url(photo_id, width, height)
        if url in self._cache:
            return ContentFile(self._cache[url])

        safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in photo_id)
        cache_file = self.cache_dir / f"{safe_id}_{width}x{height}.jpg"
        if cache_file.exists():
            payload = cache_file.read_bytes()
            self._cache[url] = payload
            return ContentFile(payload)

        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                payload = response.read()
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            self.failed += 1
            self.stderr.write(f"  ! {photo_id}: {exc}")
            return None

        if len(payload) < 1024:
            self.failed += 1
            self.stderr.write(f"  ! {photo_id}: response too small ({len(payload)} bytes)")
            return None

        self._cache[url] = payload
        try:
            cache_file.write_bytes(payload)  # persist for the next (re)seed
        except OSError:
            pass
        return ContentFile(payload)

    def apply(self, instance, field: str, photo: imagery.Photo, size, name: str) -> bool:
        """Attach a photo to an ImageField, skipping work already done."""
        photo_id, _description = photo
        current = getattr(instance, field)
        if current and not self.force and photo_id in current.name:
            return False

        content = self.fetch(photo_id, *size)
        if content is None:
            return False

        filename = f"{name}-{photo_id}.jpg"
        getattr(instance, field).save(filename, content, save=True)
        self.downloaded += 1
        return True

    # ----------------------------------------------------------------- groups

    def do_categories(self):
        applied = 0
        for category in Category.objects.all():
            photo = imagery.CATEGORY_HERO.get(category.name)
            if not photo:
                continue
            applied += self.apply(category, "image", photo, (900, 940), category.slug)
        self.stdout.write(f"Categories: {applied} updated")

    def do_fabrics(self):
        applied = 0
        for fabric in Fabric.objects.all():
            photo = imagery.FABRIC_HERO.get(fabric.name)
            if not photo:
                continue
            applied += self.apply(fabric, "image", photo, (800, 800), fabric.slug)
        self.stdout.write(f"Fabrics: {applied} updated")

    def do_collections(self):
        applied = 0
        for collection in Collection.objects.all():
            photo = imagery.COLLECTION_HERO.get(collection.name)
            if not photo:
                continue
            applied += self.apply(
                collection, "hero_image", photo, (1400, 800), collection.slug
            )
        self.stdout.write(f"Collections: {applied} updated")

    @transaction.atomic
    def do_products(self):
        """Give every colourway its own shot, so swatches visibly change the gallery."""
        applied = 0
        for product in Product.objects.select_related("category").prefetch_related(
            "colours__images"
        ):
            pool = imagery.pool_for_category(product.category.name)
            for index, colour in enumerate(product.colours.all()):
                photo = pool[index % len(pool)]
                photo_id, description = photo
                alt = f"{product.name} in {colour.name} — {description.lower()}"

                images = list(colour.images.all())
                if images:
                    primary = next((i for i in images if i.is_primary), images[0])
                    if self.apply(
                        primary, "image", photo, (1200, 1500), f"{product.slug}-{colour.pk}"
                    ):
                        primary.alt_text = alt
                        primary.save(update_fields=["alt_text", "updated_at"])
                        applied += 1

                    # Second shot: next photo in the pool, for the gallery.
                    secondary = next((i for i in images if i is not primary), None)
                    if secondary is not None:
                        alt_photo = pool[(index + 1) % len(pool)]
                        if self.apply(
                            secondary,
                            "image",
                            alt_photo,
                            (1200, 1500),
                            f"{product.slug}-{colour.pk}-b",
                        ):
                            secondary.alt_text = alt
                            secondary.save(update_fields=["alt_text", "updated_at"])
                            applied += 1
                else:
                    image = ProductImage(colour=colour, alt_text=alt, is_primary=True)
                    content = self.fetch(photo_id, 1200, 1500)
                    if content is not None:
                        image.image.save(
                            f"{product.slug}-{colour.pk}-{photo_id}.jpg", content, save=False
                        )
                        image.save()
                        self.downloaded += 1
                        applied += 1
        self.stdout.write(f"Product images: {applied} updated")

    def do_journal(self):
        applied = 0
        for index, post in enumerate(JournalPost.objects.all()):
            photo = imagery.JOURNAL_POOL[index % len(imagery.JOURNAL_POOL)]
            applied += self.apply(post, "hero_image", photo, (1400, 900), post.slug)
        self.stdout.write(f"Journal posts: {applied} updated")

    def do_home(self):
        applied = 0
        for section in HomeSection.objects.all():
            photo = imagery.HOME_HERO.get(section.kind)
            if not photo:
                continue
            applied += self.apply(section, "image", photo, (1600, 900), f"home-{section.kind}")
        self.stdout.write(f"Homepage blocks: {applied} updated")
