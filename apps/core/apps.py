from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.core"

    def ready(self):
        from .seeding import run_on_boot

        # Honours SEED_DEMO; no-ops unless this is the runserver process.
        run_on_boot()
