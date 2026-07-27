import mimetypes
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.core.models import StoredFile


class Command(BaseCommand):
    help = "Import every file under MEDIA_ROOT into the database (DatabaseStorage)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--overwrite",
            action="store_true",
            help="Replace rows that already exist instead of skipping them.",
        )

    def handle(self, *args, **options):
        root = Path(settings.MEDIA_ROOT)
        if not root.exists():
            self.stdout.write("No MEDIA_ROOT on disk — nothing to import.")
            return

        imported = skipped = 0
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            name = path.relative_to(root).as_posix()
            if not options["overwrite"] and StoredFile.objects.filter(name=name).exists():
                skipped += 1
                continue
            data = path.read_bytes()
            StoredFile.objects.update_or_create(
                name=name,
                defaults={
                    "content": data,
                    "content_type": mimetypes.guess_type(name)[0] or "application/octet-stream",
                    "size": len(data),
                },
            )
            imported += 1

        self.stdout.write(
            self.style.SUCCESS(f"Imported {imported} file(s); skipped {skipped} existing.")
        )
