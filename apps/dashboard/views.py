"""Custom staff dashboard — Django templates + HTMX, not django.contrib.admin."""

import csv
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.decorators import user_passes_test
from django.db import transaction
from django.db.models import Count, F, Q, Sum
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.models import Address
from apps.catalog.models import (
    Category,
    Collection,
    Fabric,
    Product,
    ProductColour,
    ProductImage,
    ProductVariant,
    Review,
    ReviewEvent,
    Size,
)
from apps.marketing.models import (
    ContactMessage,
    HomeSection,
    JournalCategory,
    JournalPost,
    NewsletterSubscriber,
    SiteSettings,
)
from apps.orders.models import Discount, Order, Return
from apps.orders.services import ReturnError, cancel_order, resolve_return

from . import forms as dash_forms

User = get_user_model()

LOW_STOCK = settings.LOW_STOCK_THRESHOLD

# A colour holds at most this many images. Each upload also generates card/thumb/
# zoom renditions, so an unbounded count exhausts memory — this is the hard cap
# the storefront and the browser both respect.
MAX_IMAGES_PER_COLOUR = 8

staff_required = user_passes_test(
    lambda u: u.is_authenticated and u.is_staff, login_url="/dashboard/login/"
)


def paginate(request, queryset, per_page=25):
    from django.core.paginator import Paginator

    paginator = Paginator(queryset, per_page)
    return paginator.get_page(request.GET.get("page"))


def stock_rows(colour=None, post=None, prefix=""):
    """One row per size for the colour × size stock grid (blank = not offered).

    ``colour=None`` (or an unsaved one) yields empty rows, which is what the
    "add product" screen and the blank spare colour row need.

    When ``post`` is given (a re-render after a validation error) each row shows
    what the user just typed — read from ``<prefix>stock_/price_/active_<size>``
    — instead of reverting to the stored values, so their work isn't wiped.
    """
    variants = {}
    if colour is not None and colour.pk:
        variants = {v.size_id: v for v in colour.variants.select_related("size")}
    rows = []
    for size in Size.objects.all():
        variant = variants.get(size.pk)
        if post is not None:
            stock = (post.get(f"{prefix}stock_{size.pk}") or "").strip()
            price = (post.get(f"{prefix}price_{size.pk}") or "").strip()
            active = post.get(f"{prefix}active_{size.pk}") == "on"
        elif variant:
            stock = variant.stock_quantity
            price = variant.price_override if variant.price_override is not None else ""
            active = variant.is_active
        else:
            stock, price, active = "", "", True
        rows.append(
            {
                "size": size,
                "variant": variant,
                "stock": stock,
                "price": price,
                "active": active,
                "sku": variant.sku if variant else "auto",
            }
        )
    return rows


def apply_stock_grid(post, colour, prefix=""):
    """Save one colour × size grid from ``<prefix>stock_<size_id>`` style fields.

    Shared by the product form (where ``prefix`` is the colour formset's, so
    several grids can post at once) and the standalone HTMX endpoint.
    """
    for size in Size.objects.all():
        raw = post.get(f"{prefix}stock_{size.pk}")
        if raw is None or raw == "":
            # Blank = this colour isn't offered in that size.
            ProductVariant.objects.filter(colour=colour, size=size).delete()
            continue
        try:
            quantity = max(int(raw), 0)
        except (TypeError, ValueError):
            continue
        variant, _ = ProductVariant.objects.get_or_create(colour=colour, size=size)
        variant.stock_quantity = quantity
        variant.is_active = post.get(f"{prefix}active_{size.pk}") == "on"
        override = (post.get(f"{prefix}price_{size.pk}") or "").strip()
        try:
            variant.price_override = Decimal(override) if override else None
        except InvalidOperation:
            variant.price_override = None
        variant.save()


def attach_colour_images(files, colour, prefix=""):
    """Store files posted for this colour, keeping the first primary.

    Never stores more than ``MAX_IMAGES_PER_COLOUR`` in total — anything beyond
    the remaining room is ignored, so a bypassed client can't overwhelm the app.
    Returns ``(saved, ignored)``.
    """
    uploads = files.getlist(f"{prefix}images")
    if not uploads:
        return 0, 0
    existing = colour.images.count()
    room = max(0, MAX_IMAGES_PER_COLOUR - existing)
    for saved, upload in enumerate(uploads[:room]):
        ProductImage.objects.create(
            colour=colour,
            image=upload,
            alt_text=f"{colour.product.name} in {colour.name}",
            sort_order=existing + saved,
            is_primary=existing == 0 and saved == 0,
        )
    saved = min(len(uploads), room)
    return saved, len(uploads) - saved


# ------------------------------------------------------------------------ auth


def login_view(request):
    if request.user.is_authenticated and request.user.is_staff:
        return redirect("dashboard:home")

    form = dash_forms.StaffLoginForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = authenticate(
            request,
            email=form.cleaned_data["email"],
            password=form.cleaned_data["password"],
        )
        if user is None:
            messages.error(request, "Those details weren't recognised.")
        elif not user.is_staff:
            messages.error(request, "This account doesn't have dashboard access.")
        else:
            login(request, user)
            return redirect(request.GET.get("next") or "dashboard:home")

    return render(request, "dashboard/login.html", {"form": form})


def logout_view(request):
    logout(request)
    return redirect("dashboard:login")


# -------------------------------------------------------------------- overview


@staff_required
def home(request):
    now = timezone.now()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_ago = now - timedelta(days=7)

    paid = Order.objects.exclude(
        status__in=[Order.Status.CANCELLED, Order.Status.REFUNDED]
    )
    today_orders = paid.filter(created_at__gte=today)
    week_orders = paid.filter(created_at__gte=week_ago)

    low_stock = (
        ProductVariant.objects.filter(is_active=True, stock_quantity__lte=LOW_STOCK)
        .select_related("colour__product", "size")
        .order_by("stock_quantity")[:12]
    )

    context = {
        "page_title": "Overview",
        "today_count": today_orders.count(),
        "today_revenue": today_orders.aggregate(t=Sum("grand_total"))["t"] or 0,
        "week_count": week_orders.count(),
        "week_revenue": week_orders.aggregate(t=Sum("grand_total"))["t"] or 0,
        "pending_orders": Order.objects.filter(status=Order.Status.DRAFT).count(),
        "awaiting_fulfilment": Order.objects.filter(
            status__in=[Order.Status.CONFIRMED, Order.Status.FULFILLMENT]
        ).count(),
        "new_customers": User.objects.filter(
            date_joined__gte=week_ago, is_staff=False
        ).count(),
        "pending_reviews": Review.objects.filter(status=Review.Status.PENDING).count(),
        "low_stock": low_stock,
        "low_stock_count": ProductVariant.objects.filter(
            is_active=True, stock_quantity__lte=LOW_STOCK
        ).count(),
        "product_count": Product.objects.filter(is_active=True).count(),
        "recent_orders": Order.objects.all()[:8],
        "subscriber_count": NewsletterSubscriber.objects.filter(is_active=True).count(),
    }
    return render(request, "dashboard/home.html", context)


# -------------------------------------------------------------------- products


@staff_required
def product_list(request):
    queryset = (
        Product.objects.select_related("category")
        .prefetch_related("colours__variants", "colours__images")
        .annotate(stock=Sum("colours__variants__stock_quantity"))
        # Aggregation drops Meta ordering, so restate it for the paginator.
        .order_by("sort_order", "-created_at")
    )
    q = request.GET.get("q", "").strip()
    if q:
        queryset = queryset.filter(Q(name__icontains=q) | Q(slug__icontains=q))
    if category := request.GET.get("category"):
        queryset = queryset.filter(category__slug=category)
    if collection := request.GET.get("collection"):
        queryset = queryset.filter(collections__slug=collection)
    state = request.GET.get("state")
    if state == "active":
        queryset = queryset.filter(is_active=True)
    elif state == "inactive":
        queryset = queryset.filter(is_active=False)
    elif state == "sale":
        queryset = queryset.filter(compare_at_price__gt=F("base_price"))

    return render(
        request,
        "dashboard/products/list.html",
        {
            "page_title": "Products",
            "products": paginate(request, queryset),
            "categories": Category.objects.all(),
            "collections": Collection.objects.all(),
            "q": q,
        },
    )


@staff_required
@require_POST
def product_toggle_active(request, pk):
    product = get_object_or_404(Product, pk=pk)
    product.is_active = not product.is_active
    product.save(update_fields=["is_active", "updated_at"])
    if request.headers.get("HX-Request"):
        return render(
            request, "dashboard/products/_active_toggle.html", {"product": product}
        )
    return redirect("dashboard:product_list")


@staff_required
def product_form(request, pk=None):
    """Product editor: details + colours + per-colour images + per-size stock."""
    product = get_object_or_404(Product, pk=pk) if pk else None

    if request.method == "POST":
        form = dash_forms.ProductForm(request.POST, instance=product)
        colour_formset = dash_forms.ProductColourFormSet(
            request.POST, request.FILES, instance=product, prefix="colours"
        )
        # Validate both before branching: `and` would short-circuit and leave the
        # colour errors uncollected, so only half the problems would be shown.
        details_ok = form.is_valid()
        colours_ok = colour_formset.is_valid()
        if details_ok and colours_ok:
            ignored_images = 0
            with transaction.atomic():
                product = form.save()
                colour_formset.instance = product
                colour_formset.save()
                for colour_form in colour_formset.forms:
                    colour = colour_form.instance
                    if not colour.pk or colour_form.cleaned_data.get("DELETE"):
                        continue
                    # Images and stock ride along with the same submit, so they
                    # work when adding a product, not only when editing one.
                    _, ignored = attach_colour_images(
                        request.FILES, colour, prefix=f"{colour_form.prefix}-"
                    )
                    ignored_images += ignored
                    apply_stock_grid(
                        request.POST, colour, prefix=f"{colour_form.prefix}-"
                    )
            messages.success(request, f"“{product.name}” saved.")
            if ignored_images:
                messages.warning(
                    request,
                    f"A colour can hold at most {MAX_IMAGES_PER_COLOUR} images — "
                    f"{ignored_images} extra were not added.",
                )
            if "save_and_continue" in request.POST:
                return redirect("dashboard:product_edit", pk=product.pk)
            return redirect("dashboard:product_list")
        messages.error(request, "Please correct the highlighted fields.")
    else:
        form = dash_forms.ProductForm(instance=product)
        colour_formset = dash_forms.ProductColourFormSet(instance=product, prefix="colours")

    # Hang each colour's images and stock grid off its form so one panel can
    # render the lot — the same panel whether the product exists yet or not.
    # On a POST that fell through to here (validation failed) the grid is redrawn
    # from what was submitted, not the DB, so typed stock isn't lost.
    error_post = request.POST if request.method == "POST" else None
    for colour_form in colour_formset.forms:
        colour = colour_form.instance
        colour_form.stock_rows = stock_rows(
            colour, post=error_post, prefix=f"{colour_form.prefix}-"
        )
        colour_form.existing_images = (
            colour.images.order_by("sort_order", "id") if colour.pk else []
        )
        colour_form.stock_total = colour.stock if colour.pk else 0

    return render(
        request,
        "dashboard/products/form.html",
        {
            "page_title": product.name if product else "New product",
            "product": product,
            "form": form,
            "colour_formset": colour_formset,
            "blank_rows": stock_rows(None),
            "sizes": Size.objects.all(),
            "max_images": MAX_IMAGES_PER_COLOUR,
        },
    )


@staff_required
@require_POST
def product_delete(request, pk):
    product = get_object_or_404(Product, pk=pk)
    name = product.name
    product.delete()
    messages.success(request, f"“{name}” deleted.")
    return redirect("dashboard:product_list")


# ---------------------------------------------------- product editor (HTMX)


def image_strip(request, colour):
    """Render the admin image strip for one colour.

    Ordered by ``sort_order`` (then id) — the sequence the admin arranges by
    dragging — rather than the model's gallery ordering that pins the cover
    first, so drag-and-drop is honoured exactly on screen.
    """
    return render(
        request,
        "dashboard/products/_images.html",
        {"colour": colour, "images": colour.images.order_by("sort_order", "id")},
    )


@staff_required
@require_POST
def colour_images_upload(request, colour_id):
    """Add one or more images to a colour, returning the refreshed strip.

    Called on every file pick, so images accumulate — the admin no longer has
    to choose them all in a single go.
    """
    colour = get_object_or_404(ProductColour, pk=colour_id)
    attach_colour_images(request.FILES, colour)
    return image_strip(request, colour)


@staff_required
@require_POST
def colour_image_delete(request, image_id):
    image = get_object_or_404(ProductImage, pk=image_id)
    colour = image.colour
    was_primary = image.is_primary
    image.delete()
    if was_primary:
        replacement = colour.images.first()
        if replacement:
            replacement.is_primary = True
            replacement.save(update_fields=["is_primary", "updated_at"])
    return image_strip(request, colour)


@staff_required
@require_POST
def colour_image_primary(request, image_id):
    image = get_object_or_404(ProductImage, pk=image_id)
    image.is_primary = True
    image.save()
    return image_strip(request, image.colour)


@staff_required
@require_POST
def colour_images_reorder(request, colour_id):
    """Persist a new image order from a posted ``order`` of image ids.

    ``order`` is a comma-separated list of this colour's image ids in the
    sequence the admin dragged them into; we write that as ``sort_order``.
    Ids that don't belong to the colour are ignored.
    """
    colour = get_object_or_404(ProductColour, pk=colour_id)
    posted = [i for i in request.POST.get("order", "").split(",") if i.isdigit()]
    with transaction.atomic():
        for position, image_id in enumerate(posted):
            ProductImage.objects.filter(colour=colour, pk=image_id).update(
                sort_order=position
            )
    return image_strip(request, colour)


@staff_required
@require_POST
def colour_stock_save(request, colour_id):
    """Save the whole colour × size stock grid in one go."""
    colour = get_object_or_404(ProductColour, pk=colour_id)
    with transaction.atomic():
        apply_stock_grid(request.POST, colour)

    colour.refresh_from_db()
    return render(
        request,
        "dashboard/products/_stock_grid.html",
        {
            "colour": colour,
            "rows": stock_rows(colour),
            "stock": colour.stock,
            "saved": True,
        },
    )


@staff_required
@require_POST
def colour_delete(request, colour_id):
    colour = get_object_or_404(ProductColour, pk=colour_id)
    product_id = colour.product_id
    colour.delete()
    messages.success(request, "Colour removed.")
    return HttpResponseRedirect(reverse("dashboard:product_edit", args=[product_id]))


# ------------------------------------------------------------------- inventory


@staff_required
def inventory(request):
    queryset = ProductVariant.objects.select_related(
        "colour__product", "size"
    ).order_by("colour__product__name", "colour__sort_order", "size__sort_order")

    q = request.GET.get("q", "").strip()
    if q:
        queryset = queryset.filter(
            Q(colour__product__name__icontains=q)
            | Q(sku__icontains=q)
            | Q(colour__name__icontains=q)
        )
    if request.GET.get("low") == "1":
        queryset = queryset.filter(stock_quantity__lte=LOW_STOCK)
    if request.GET.get("out") == "1":
        queryset = queryset.filter(stock_quantity=0)

    return render(
        request,
        "dashboard/inventory/grid.html",
        {
            "page_title": "Inventory",
            "variants": paginate(request, queryset, per_page=50),
            "q": q,
            "total_units": ProductVariant.objects.aggregate(t=Sum("stock_quantity"))["t"] or 0,
            "low_count": ProductVariant.objects.filter(stock_quantity__lte=LOW_STOCK).count(),
            "out_count": ProductVariant.objects.filter(stock_quantity=0).count(),
        },
    )


@staff_required
@require_POST
def inventory_bulk_save(request):
    """Bulk stock update from the inventory grid."""
    updated = 0
    with transaction.atomic():
        for key, value in request.POST.items():
            if not key.startswith("stock_"):
                continue
            try:
                variant_id = int(key.split("_", 1)[1])
                quantity = max(int(value), 0)
            except (TypeError, ValueError):
                continue
            if ProductVariant.objects.filter(pk=variant_id).exclude(
                stock_quantity=quantity
            ).update(stock_quantity=quantity, updated_at=timezone.now()):
                updated += 1
    messages.success(request, f"{updated} variant(s) updated.")
    return redirect(request.META.get("HTTP_REFERER") or "dashboard:inventory")


@staff_required
@require_POST
def inventory_quick_update(request, pk):
    """HTMX inline stock edit."""
    variant = get_object_or_404(ProductVariant, pk=pk)
    try:
        variant.stock_quantity = max(int(request.POST.get("stock_quantity", 0)), 0)
    except (TypeError, ValueError):
        pass
    variant.save(update_fields=["stock_quantity", "updated_at"])
    return render(request, "dashboard/inventory/_row_stock.html", {"variant": variant})


# -------------------------------------------------------------------- taxonomy


def _edit_instance(request, model):
    """The row the ``?edit=<pk>`` link (or a POSTed hidden pk) refers to."""
    pk = request.POST.get("pk") if request.method == "POST" else request.GET.get("edit")
    return model.objects.filter(pk=pk).first() if pk else None


@staff_required
def category_list(request):
    instance = _edit_instance(request, Category)
    if request.method == "POST":
        form = dash_forms.CategoryForm(request.POST, request.FILES, instance=instance)
        if form.is_valid():
            form.save()
            messages.success(request, "Category saved.")
            return redirect("dashboard:category_list")
        messages.error(request, "Please correct the errors below.")
    else:
        form = dash_forms.CategoryForm(instance=instance)

    return render(
        request,
        "dashboard/taxonomy/categories.html",
        {
            "page_title": "Categories",
            "objects": Category.objects.select_related("parent").annotate(
                n=Count("products")
            ),
            "form": form,
        },
    )


@staff_required
def collection_list(request):
    instance = _edit_instance(request, Collection)
    if request.method == "POST":
        form = dash_forms.CollectionForm(request.POST, request.FILES, instance=instance)
        if form.is_valid():
            form.save()
            messages.success(request, "Collection saved.")
            return redirect("dashboard:collection_list")
        messages.error(request, "Please correct the errors below.")
    else:
        form = dash_forms.CollectionForm(instance=instance)
    return render(
        request,
        "dashboard/taxonomy/collections.html",
        {
            "page_title": "Collections",
            "objects": Collection.objects.annotate(n=Count("products")),
            "form": form,
        },
    )


@staff_required
def fabric_list(request):
    instance = _edit_instance(request, Fabric)
    if request.method == "POST":
        form = dash_forms.FabricForm(request.POST, request.FILES, instance=instance)
        if form.is_valid():
            form.save()
            messages.success(request, "Fabric saved.")
            return redirect("dashboard:fabric_list")
        messages.error(request, "Please correct the errors below.")
    else:
        form = dash_forms.FabricForm(instance=instance)
    return render(
        request,
        "dashboard/taxonomy/fabrics.html",
        {
            "page_title": "Fabrics",
            "objects": Fabric.objects.annotate(n=Count("products")),
            "form": form,
        },
    )


@staff_required
def size_list(request):
    instance = _edit_instance(request, Size)
    if request.method == "POST":
        form = dash_forms.SizeForm(request.POST, instance=instance)
        if form.is_valid():
            form.save()
            messages.success(request, "Size saved.")
            return redirect("dashboard:size_list")
        messages.error(request, "Please correct the errors below.")
    else:
        form = dash_forms.SizeForm(instance=instance)
    return render(
        request,
        "dashboard/taxonomy/sizes.html",
        {"page_title": "Sizes", "objects": Size.objects.all(), "form": form},
    )


@staff_required
@require_POST
def taxonomy_delete(request, kind, pk):
    model = {
        "category": Category,
        "collection": Collection,
        "fabric": Fabric,
        "size": Size,
    }.get(kind)
    if model is None:
        return redirect("dashboard:home")
    obj = get_object_or_404(model, pk=pk)
    try:
        obj.delete()
        messages.success(request, "Deleted.")
    except Exception:
        messages.error(request, "That record is still in use and can't be deleted.")
    return redirect(f"dashboard:{kind}_list")


# ---------------------------------------------------------------------- orders


@staff_required
def order_list(request):
    queryset = Order.objects.select_related("user").prefetch_related("items")
    q = request.GET.get("q", "").strip()
    if q:
        queryset = queryset.filter(
            Q(number__icontains=q) | Q(email__icontains=q)
        )
    if status_filter := request.GET.get("status"):
        queryset = queryset.filter(status=status_filter)

    return render(
        request,
        "dashboard/orders/list.html",
        {
            "page_title": "Orders",
            "orders": paginate(request, queryset),
            "statuses": Order.Status.choices,
            "q": q,
            "current_status": request.GET.get("status", ""),
        },
    )


@staff_required
def order_detail(request, number):
    order = get_object_or_404(
        Order.objects.prefetch_related(
            "items__variant__colour__product",
            "status_events",
            "returns__items__order_item",
        ),
        number=number,
    )
    if request.method == "POST":
        form = dash_forms.OrderStatusForm(request.POST, instance=order)
        if form.is_valid():
            form.save()
            messages.success(request, f"Order {order.number} updated.")
            return redirect("dashboard:order_detail", number=order.number)
    else:
        form = dash_forms.OrderStatusForm(instance=order)

    # The lifecycle stepper: each stage flagged done / current / upcoming.
    labels = dict(Order.Status.choices)
    current = Order.LIFECYCLE.index(order.status) if order.status in Order.LIFECYCLE else -1
    steps = []
    for i, value in enumerate(Order.LIFECYCLE):
        state = "upcoming"
        if current != -1:
            state = "done" if i < current else "current" if i == current else "upcoming"
        steps.append({"value": value, "label": labels[value], "state": state})

    return render(
        request,
        "dashboard/orders/detail.html",
        {
            "page_title": f"Order {order.number}",
            "order": order,
            "form": form,
            "steps": steps,
        },
    )


@staff_required
@require_POST
def order_set_status(request, number):
    """Advance an order to a new lifecycle stage, logging who/why."""
    order = get_object_or_404(Order, number=number)
    labels = dict(Order.Status.choices)
    new_status = request.POST.get("status", "")
    note = (request.POST.get("note") or "").strip()
    if new_status not in labels or new_status == order.status:
        messages.error(request, "That isn't a valid status change.")
        return redirect("dashboard:order_detail", number=order.number)

    order.transition_to(new_status, actor=request.user.email, note=note)
    messages.success(request, f"{order.number} → “{labels[new_status]}”.")
    return redirect("dashboard:order_detail", number=order.number)


@staff_required
@require_POST
def order_cancel(request, number):
    order = get_object_or_404(Order, number=number)
    refund = request.POST.get("refund") == "1"
    cancel_order(order, refund=refund, actor=request.user.email)
    messages.success(
        request,
        f"Order {order.number} {'refunded' if refund else 'cancelled'} and stock restored.",
    )
    return redirect("dashboard:order_detail", number=order.number)


# --------------------------------------------------------------------- returns


@staff_required
def return_list(request):
    queryset = (
        Return.objects.select_related("order", "user")
        .prefetch_related("items")
        .order_by("-created_at")
    )
    if status_filter := request.GET.get("status"):
        queryset = queryset.filter(status=status_filter)
    return render(
        request,
        "dashboard/returns/list.html",
        {
            "page_title": "Returns",
            "returns": paginate(request, queryset),
            "statuses": Return.Status.choices,
            "current_status": request.GET.get("status", ""),
        },
    )


@staff_required
@require_POST
def return_resolve(request, number, action):
    """Approve (refund + restock the returned lines) or reject a return."""
    ret = get_object_or_404(Return.objects.select_related("order"), number=number)
    staff_note = (request.POST.get("staff_note") or "").strip()
    try:
        resolve_return(
            ret=ret,
            approve=(action == "approve"),
            actor=request.user.email,
            staff_note=staff_note,
        )
    except ReturnError as exc:
        messages.error(request, exc.message)
        return redirect("dashboard:order_detail", number=ret.order.number)
    verb = "approved — refunded & restocked" if action == "approve" else "rejected"
    messages.success(request, f"Return {ret.number} {verb}.")
    return redirect(request.POST.get("next") or "dashboard:return_list")


# ------------------------------------------------------------------- customers


@staff_required
def customer_list(request):
    queryset = User.objects.annotate(
        order_count=Count("orders"), spend=Sum("orders__grand_total")
    ).order_by("-date_joined")
    q = request.GET.get("q", "").strip()
    if q:
        queryset = queryset.filter(
            Q(email__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q)
        )
    return render(
        request,
        "dashboard/customers/list.html",
        {"page_title": "Customers", "customers": paginate(request, queryset), "q": q},
    )


@staff_required
def customer_detail(request, pk):
    customer = get_object_or_404(User, pk=pk)
    if request.method == "POST":
        form = dash_forms.CustomerForm(request.POST, instance=customer)
        if form.is_valid():
            form.save()
            messages.success(request, "Customer updated.")
            return redirect("dashboard:customer_detail", pk=customer.pk)
    else:
        form = dash_forms.CustomerForm(instance=customer)

    return render(
        request,
        "dashboard/customers/detail.html",
        {
            "page_title": customer.full_name,
            "customer": customer,
            "form": form,
            "orders": Order.objects.filter(user=customer)[:20],
            "addresses": Address.objects.filter(user=customer),
            "wishlist": customer.wishlist.select_related("product")[:12],
        },
    )


# ------------------------------------------------------------------- discounts


@staff_required
def discount_list(request):
    instance = _edit_instance(request, Discount)
    if request.method == "POST":
        form = dash_forms.DiscountForm(request.POST, instance=instance)
        if form.is_valid():
            form.save()
            messages.success(request, "Discount saved.")
            return redirect("dashboard:discount_list")
        messages.error(request, "Please correct the errors below.")
    else:
        form = dash_forms.DiscountForm(instance=instance)

    return render(
        request,
        "dashboard/discounts/list.html",
        {"page_title": "Discounts", "objects": Discount.objects.all(), "form": form},
    )


@staff_required
@require_POST
def discount_delete(request, pk):
    get_object_or_404(Discount, pk=pk).delete()
    messages.success(request, "Discount deleted.")
    return redirect("dashboard:discount_list")


# --------------------------------------------------------------------- reviews


@staff_required
def review_list(request):
    queryset = Review.objects.select_related("product")
    state = request.GET.get("state", "pending")
    if state in {choice.value for choice in Review.Status}:
        queryset = queryset.filter(status=state)
    return render(
        request,
        "dashboard/reviews/list.html",
        {
            "page_title": "Reviews",
            "reviews": paginate(request, queryset),
            "state": state,
            "pending_count": Review.objects.filter(status=Review.Status.PENDING).count(),
            "rejected_count": Review.objects.filter(status=Review.Status.REJECTED).count(),
        },
    )


@staff_required
def review_detail(request, pk):
    review = get_object_or_404(
        Review.objects.select_related("product").prefetch_related("events__actor"), pk=pk
    )
    return render(
        request,
        "dashboard/reviews/detail.html",
        {"page_title": f"Review · {review.product.name}", "review": review},
    )


def _approve_review(review, actor):
    review.status = Review.Status.APPROVED
    review.is_approved = True
    review.rejection_reason = ""
    # Saving is_approved fires the signal that recomputes the product's rating.
    review.save(update_fields=["status", "is_approved", "rejection_reason", "updated_at"])
    review.add_event(ReviewEvent.Action.APPROVED, actor=actor)


def _reject_review(review, actor, reason):
    review.status = Review.Status.REJECTED
    review.is_approved = False
    review.rejection_reason = reason
    review.save(update_fields=["status", "is_approved", "rejection_reason", "updated_at"])
    review.add_event(ReviewEvent.Action.REJECTED, actor=actor, reason=reason)


@staff_required
@require_POST
def review_moderate(request, pk, action):
    review = get_object_or_404(Review, pk=pk)
    fallback = request.META.get("HTTP_REFERER") or reverse("dashboard:review_list")
    if action == "approve":
        _approve_review(review, request.user)
        messages.success(request, "Review approved and published.")
    elif action == "reject":
        reason = (request.POST.get("reason") or "").strip()
        if not reason:
            messages.error(request, "Please give a reason so the shopper knows what to change.")
            return redirect(fallback)
        _reject_review(review, request.user, reason)
        messages.success(request, "Changes requested — the shopper has been shown your reason.")
    # Reviews are never deleted from the dashboard — a review is either approved
    # and published, or left pending / sent back for changes. Any other action is
    # ignored so it can't be forced via a crafted request.
    return redirect(fallback)


# --------------------------------------------------------------------- journal


@staff_required
def journal_list(request):
    return render(
        request,
        "dashboard/journal/list.html",
        {
            "page_title": "Journal",
            "posts": paginate(request, JournalPost.objects.select_related("category")),
            "categories": JournalCategory.objects.all(),
            "category_form": dash_forms.JournalCategoryForm(),
        },
    )


@staff_required
def journal_form(request, pk=None):
    post = get_object_or_404(JournalPost, pk=pk) if pk else None
    if request.method == "POST":
        form = dash_forms.JournalPostForm(request.POST, request.FILES, instance=post)
        if form.is_valid():
            post = form.save()
            if post.is_published and not post.published_at:
                post.published_at = timezone.now()
                post.save(update_fields=["published_at"])
            messages.success(request, f"“{post.title}” saved.")
            return redirect("dashboard:journal_list")
        messages.error(request, "Please correct the errors below.")
    else:
        form = dash_forms.JournalPostForm(instance=post)

    return render(
        request,
        "dashboard/journal/form.html",
        {"page_title": post.title if post else "New post", "form": form, "post": post},
    )


@staff_required
@require_POST
def journal_delete(request, pk):
    get_object_or_404(JournalPost, pk=pk).delete()
    messages.success(request, "Post deleted.")
    return redirect("dashboard:journal_list")


@staff_required
@require_POST
def journal_category_create(request):
    form = dash_forms.JournalCategoryForm(request.POST)
    if form.is_valid():
        form.save()
        messages.success(request, "Category added.")
    return redirect("dashboard:journal_list")


# --------------------------------------------------------------------- content


@staff_required
def content_settings(request):
    site = SiteSettings.load()
    if request.method == "POST":
        form = dash_forms.SiteSettingsForm(request.POST, instance=site)
        if form.is_valid():
            form.save()
            messages.success(request, "Site settings saved.")
            return redirect("dashboard:content_settings")
        messages.error(request, "Please correct the errors below.")
    else:
        form = dash_forms.SiteSettingsForm(instance=site)

    return render(
        request,
        "dashboard/content/settings.html",
        {
            "page_title": "Site content",
            "form": form,
            "sections": HomeSection.objects.select_related("collection"),
        },
    )


@staff_required
def home_section_form(request, pk=None):
    section = get_object_or_404(HomeSection, pk=pk) if pk else None
    if request.method == "POST":
        form = dash_forms.HomeSectionForm(request.POST, request.FILES, instance=section)
        if form.is_valid():
            form.save()
            messages.success(request, "Homepage block saved.")
            return redirect("dashboard:content_settings")
        messages.error(request, "Please correct the errors below.")
    else:
        form = dash_forms.HomeSectionForm(instance=section)

    return render(
        request,
        "dashboard/content/section_form.html",
        {
            "page_title": str(section) if section else "New homepage block",
            "form": form,
            "section": section,
        },
    )


@staff_required
@require_POST
def home_section_action(request, pk, action):
    section = get_object_or_404(HomeSection, pk=pk)
    if action == "toggle":
        section.is_active = not section.is_active
        section.save(update_fields=["is_active", "updated_at"])
    elif action == "up":
        section.sort_order = max(section.sort_order - 1, 0)
        section.save(update_fields=["sort_order", "updated_at"])
    elif action == "down":
        section.sort_order += 1
        section.save(update_fields=["sort_order", "updated_at"])
    elif action == "delete":
        section.delete()
        messages.success(request, "Block deleted.")
    return redirect("dashboard:content_settings")


# ------------------------------------------------------------------ newsletter


@staff_required
def newsletter_list(request):
    return render(
        request,
        "dashboard/newsletter/list.html",
        {
            "page_title": "Newsletter",
            "subscribers": paginate(request, NewsletterSubscriber.objects.all(), 50),
            "total": NewsletterSubscriber.objects.filter(is_active=True).count(),
            "messages_received": ContactMessage.objects.filter(is_handled=False)[:10],
        },
    )


@staff_required
def newsletter_export(request):
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="subscribers.csv"'
    writer = csv.writer(response)
    writer.writerow(["email", "active", "source", "subscribed_at"])
    for sub in NewsletterSubscriber.objects.all():
        writer.writerow(
            [sub.email, sub.is_active, sub.source, sub.created_at.strftime("%Y-%m-%d %H:%M")]
        )
    return response


@staff_required
@require_POST
def contact_message_handled(request, pk):
    message = get_object_or_404(ContactMessage, pk=pk)
    message.is_handled = True
    message.save(update_fields=["is_handled", "updated_at"])
    return redirect("dashboard:newsletter_list")
