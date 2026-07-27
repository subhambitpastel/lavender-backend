"""Small presentation helpers for the dashboard templates."""

import os

from django import template
from django.contrib.staticfiles import finders
from django.forms import BoundField
from django.templatetags.static import static
from django.utils.html import format_html

register = template.Library()


@register.simple_tag
def static_v(path):
    """Like ``{% static %}`` but with a ``?v=<mtime>`` cache-buster.

    The dashboard's CSS and JS change often; without a version the browser keeps
    serving a stale copy, so JS-driven features (image upload, drag-reorder)
    silently stop working after an edit until a hard refresh. Stamping the file's
    modified time makes every save invalidate the cache automatically.
    """
    url = static(path)
    absolute = finders.find(path)
    if absolute and os.path.exists(absolute):
        return f"{url}?v={int(os.path.getmtime(absolute))}"
    return url


@register.simple_tag
def required_star(field):
    """Emit a red ``*`` when a form field is mandatory, nothing otherwise.

    "Mandatory" is read straight off the bound field (``field.field.required``),
    so the marker always tracks what the form will actually reject — including
    fields we deliberately make optional (``slug``, ``sku``) or conditionally
    required. Pass a ``BoundField``; anything else renders nothing so a template
    typo can't blow up a page.
    """
    if isinstance(field, BoundField) and field.field.required:
        return format_html(' <abbr class="req" title="Required field">*</abbr>')
    return ""
