from django.db.models import Count, Prefetch, Q
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .filters import ProductFilter
from .models import Category, Collection, Fabric, Product, ProductColour, Review, ReviewEvent, Size
from .serializers import (
    CategorySerializer,
    CollectionSerializer,
    FabricSerializer,
    ProductCardSerializer,
    ProductDetailSerializer,
    ReviewCreateSerializer,
    ReviewSerializer,
    SizeSerializer,
)

def _reviewer_display_name(user):
    """A friendly, privacy-respecting name for a review, e.g. "Eleanor M."."""
    first = (user.first_name or "").strip()
    last = (user.last_name or "").strip()
    if first and last:
        return f"{first} {last[0]}."
    return first or "A customer"


def card_prefetch(path="colours"):
    """Prefetch of active colours (+images/variants) for ProductCard serialization.

    ``path`` lets callers reach products through a relation, e.g. ``product__colours``.
    """
    return Prefetch(
        path,
        queryset=ProductColour.objects.filter(is_active=True).prefetch_related(
            "images", "variants__size"
        ),
    )


CARD_PREFETCH = card_prefetch()


class ProductViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Public catalogue: PLP listing and PDP detail."""

    lookup_field = "slug"
    permission_classes = [AllowAny]
    filterset_class = ProductFilter
    search_fields = ("name", "description", "category__name", "colours__name")
    ordering_fields = (
        "created_at",
        "base_price",
        "rating_avg",
        "review_count",
        "name",
        "sort_order",
        "is_bestseller",
        "is_new_in",
    )
    ordering = ("sort_order", "-created_at")

    def get_queryset(self):
        return (
            Product.objects.active()
            .select_related("category")
            .prefetch_related(CARD_PREFETCH, "fabrics", "collections")
        )

    def get_serializer_class(self):
        return ProductDetailSerializer if self.action == "retrieve" else ProductCardSerializer

    @extend_schema(
        parameters=[
            OpenApiParameter("category", str, description="Category slug(s), comma separated"),
            OpenApiParameter("collection", str, description="Collection slug(s)"),
            OpenApiParameter("fabric", str, description="Fabric slug(s)"),
            OpenApiParameter("colour", str, description="Colour name(s)"),
            OpenApiParameter("size", str, description="Size name(s)"),
            OpenApiParameter("min_price", float),
            OpenApiParameter("max_price", float),
            OpenApiParameter("on_sale", bool),
            OpenApiParameter("new_in", bool),
            OpenApiParameter("search", str),
            OpenApiParameter(
                "ordering",
                str,
                description=(
                    "-created_at | base_price | -rating_avg | -review_count | name. "
                    "Comma-separate to break ties, e.g. `-rating_avg,-review_count`."
                ),
            ),
        ]
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(responses=ReviewSerializer(many=True))
    @action(detail=True, methods=["get", "post"], url_path="reviews")
    def reviews(self, request, slug=None):
        product = self.get_object()
        if request.method == "GET":
            queryset = product.reviews.filter(is_approved=True)
            page = self.paginate_queryset(queryset)
            serializer = ReviewSerializer(page, many=True, context={"request": request})
            return self.get_paginated_response(serializer.data)

        # Only a signed-in shopper who has actually had this product delivered
        # may review it — a genuine verified purchase.
        if not request.user.is_authenticated:
            return Response(
                {"detail": "Please sign in to leave a review.", "code": "auth_required"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        from apps.orders.models import Order, OrderItem

        bought = OrderItem.objects.filter(
            order__user=request.user,
            order__status__in=[Order.Status.DELIVERED, Order.Status.CLOSED],
            product_slug=product.slug,
        ).exists()
        if not bought:
            return Response(
                {
                    "detail": "You can review this once your order has been delivered.",
                    "code": "not_delivered",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = ReviewCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # Editing an existing review is bounded by two rules:
        existing = Review.objects.filter(product=product, user=request.user).first()
        if existing is not None:
            # 1. Only within 24 hours of first posting it.
            if not existing.is_editable:
                return Response(
                    {
                        "detail": "The 24-hour window to change this review has closed.",
                        "code": "edit_window_closed",
                    },
                    status=status.HTTP_403_FORBIDDEN,
                )
            # 2. Something must actually change — no resubmitting it unchanged.
            if existing.matches(
                rating=data["rating"], title=data.get("title", ""), body=data["body"]
            ):
                return Response(
                    {
                        "detail": "Please change your rating, headline or review before resubmitting.",
                        "code": "no_change",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # One review per shopper per product — a repeat submission edits it. A
        # new or edited review always (re-)enters moderation as PENDING; it goes
        # live only once staff approve it. The post_save signal recomputes the
        # product's average, which only counts approved reviews.
        review, created = Review.objects.update_or_create(
            product=product,
            user=request.user,
            defaults={
                "author_name": _reviewer_display_name(request.user),
                "author_location": request.user.location or "",
                "rating": data["rating"],
                "title": data.get("title", ""),
                "body": data["body"],
                "is_verified": True,
                "status": Review.Status.PENDING,
                "is_approved": False,
                "rejection_reason": "",
            },
        )
        review.add_event(
            ReviewEvent.Action.SUBMITTED if created else ReviewEvent.Action.RESUBMITTED,
            actor=request.user,
            snapshot=True,
        )
        return Response(
            {
                "detail": (
                    "Thank you — your review has been submitted and will appear once approved."
                    if created
                    else "Thanks — your updated review has been resubmitted for approval."
                ),
                "status": review.status,
            },
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class CategoryViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = CategorySerializer
    lookup_field = "slug"
    pagination_class = None
    permission_classes = [AllowAny]
    filter_backends = []

    def get_queryset(self):
        queryset = Category.objects.filter(is_active=True).prefetch_related("children")
        if self.action == "list":
            queryset = queryset.filter(parent__isnull=True)
        return queryset


class CollectionViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = CollectionSerializer
    lookup_field = "slug"
    pagination_class = None
    permission_classes = [AllowAny]
    filter_backends = []
    queryset = Collection.objects.filter(is_active=True)

    @action(detail=True, methods=["get"], url_path="products")
    def products(self, request, slug=None):
        collection = self.get_object()
        queryset = (
            Product.objects.active()
            .filter(collections=collection)
            .select_related("category")
            .prefetch_related(CARD_PREFETCH)
        )
        page = self.paginate_queryset(queryset)
        serializer = ProductCardSerializer(page, many=True, context={"request": request})
        return self.get_paginated_response(serializer.data)


class FabricViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = FabricSerializer
    lookup_field = "slug"
    pagination_class = None
    permission_classes = [AllowAny]
    filter_backends = []
    queryset = Fabric.objects.filter(is_active=True).annotate(
        product_count_annotated=Count("products", filter=Q(products__is_active=True))
    )


class SizeViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = SizeSerializer
    pagination_class = None
    permission_classes = [AllowAny]
    filter_backends = []
    queryset = Size.objects.all()


class SearchView(APIView):
    """Typeahead + results: products plus matching categories/collections."""

    permission_classes = [AllowAny]

    @extend_schema(parameters=[OpenApiParameter("q", str, required=True)])
    def get(self, request):
        q = (request.query_params.get("q") or "").strip()
        if not q:
            return Response({"query": "", "products": [], "categories": [], "collections": []})

        products = (
            Product.objects.active()
            .filter(
                Q(name__icontains=q)
                | Q(description__icontains=q)
                | Q(category__name__icontains=q)
                | Q(colours__name__icontains=q)
            )
            .distinct()
            .select_related("category")
            .prefetch_related(CARD_PREFETCH)[:24]
        )
        categories = Category.objects.filter(is_active=True, name__icontains=q)[:5]
        collections = Collection.objects.filter(is_active=True, name__icontains=q)[:5]
        ctx = {"request": request}
        return Response(
            {
                "query": q,
                "count": len(products),
                "products": ProductCardSerializer(products, many=True, context=ctx).data,
                "categories": CategorySerializer(categories, many=True, context=ctx).data,
                "collections": CollectionSerializer(collections, many=True, context=ctx).data,
            }
        )
