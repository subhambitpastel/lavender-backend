"""Run the SEED_DEMO policy by hand.

    py manage.py apply_seed_policy             # use SEED_DEMO from .env
    py manage.py apply_seed_policy --mode 3    # override for this run only
"""

from django.core.management.base import BaseCommand

from apps.core import seeding


class Command(BaseCommand):
    help = "Apply the SEED_DEMO policy (0 off · 1 always · 2 if-empty · 3 reset)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--mode",
            type=int,
            choices=[seeding.OFF, seeding.ALWAYS, seeding.IF_EMPTY, seeding.RESET],
            default=None,
            help="Override the SEED_DEMO setting for this run.",
        )

    def handle(self, *args, **options):
        applied = seeding.apply(mode=options["mode"], write=self.stdout.write)
        if applied == seeding.OFF:
            self.stdout.write("SEED_DEMO=0 — nothing to do.")
