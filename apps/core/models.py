from django.db import models


class TimeStamped(models.Model):
    """Abstract base giving every model created/updated timestamps."""

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class StoredFile(models.Model):
    """A media file (image) held in the database rather than the filesystem.

    Backs ``apps.core.storage.DatabaseStorage``: every ``ImageField`` write lands
    a row here, keyed by the storage path, and ``/media/<path>`` serves it back.
    """

    name = models.CharField(max_length=500, unique=True, db_index=True)
    content = models.BinaryField()
    content_type = models.CharField(max_length=120, blank=True)
    size = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name
