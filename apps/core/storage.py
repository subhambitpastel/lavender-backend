"""A Django file storage backend that keeps file bytes in the database.

Set as the ``default`` storage, it makes every ``ImageField`` (product images,
category/collection/fabric/journal imagery, imagekit-generated thumbnails) write
to the ``StoredFile`` table instead of ``MEDIA_ROOT``. ``/media/<path>`` is then
served straight from the DB by ``apps.core.views.serve_media``.

Note: this is deliberate per the project's request. For scale the standard choice
is object storage (S3/GCS) via ``STORAGES['default']`` — swapping back is config
only, since nothing outside this backend assumes where the bytes live.
"""

import mimetypes

from django.core.files.base import ContentFile
from django.core.files.storage import Storage
from django.utils.deconstruct import deconstructible


# Store keys with forward slashes always — imagekit builds cache names with the
# OS separator (backslashes on Windows), which would otherwise split into two
# different keys and 404. This is the single normalisation point.
def norm(name):
    return str(name).replace("\\", "/").lstrip("/")


@deconstructible
class DatabaseStorage(Storage):
    def _model(self):
        # Imported lazily so the storage can be referenced before apps are ready.
        from .models import StoredFile

        return StoredFile

    def _open(self, name, mode="rb"):
        row = self._model().objects.get(name=norm(name))
        return ContentFile(bytes(row.content), name=name)

    def _save(self, name, content):
        content.seek(0)
        data = content.read()
        key = norm(name)
        content_type = (
            getattr(content, "content_type", "")
            or mimetypes.guess_type(key)[0]
            or "application/octet-stream"
        )
        self._model().objects.update_or_create(
            name=key,
            defaults={"content": data, "content_type": content_type, "size": len(data)},
        )
        return name

    def exists(self, name):
        return self._model().objects.filter(name=norm(name)).exists()

    def delete(self, name):
        self._model().objects.filter(name=norm(name)).delete()

    def size(self, name):
        return self._model().objects.get(name=norm(name)).size

    def url(self, name):
        from django.conf import settings

        return f"{settings.MEDIA_URL.rstrip('/')}/{norm(name)}"

    def get_created_time(self, name):
        return self._model().objects.get(name=norm(name)).created_at

    def get_modified_time(self, name):
        return self._model().objects.get(name=norm(name)).updated_at
