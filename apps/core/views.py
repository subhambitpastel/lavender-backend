from django.http import Http404, HttpResponse

from .models import StoredFile
from .storage import norm


def serve_media(request, path):
    """Serve a media file straight from the database (DatabaseStorage backend).

    Media names carry a random suffix, so a given URL is immutable — safe to cache
    hard, which keeps this DB-backed path from being hit on every image request.
    """
    try:
        stored = (
            StoredFile.objects.only("content", "content_type", "size").get(name=norm(path))
        )
    except StoredFile.DoesNotExist:
        raise Http404("Media not found.")

    response = HttpResponse(
        bytes(stored.content),
        content_type=stored.content_type or "application/octet-stream",
    )
    response["Content-Length"] = stored.size or len(stored.content)
    response["Cache-Control"] = "public, max-age=31536000, immutable"
    return response
