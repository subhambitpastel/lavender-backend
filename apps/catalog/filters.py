import django_filters as filters
from django.db.models import F, Q

from .models import Product


class ProductFilter(filters.FilterSet):
    """PLP facets. Multi-value params accept comma-separated slugs."""

    category = filters.CharFilter(method="filter_category")
    collection = filters.CharFilter(method="filter_collection")
    fabric = filters.CharFilter(method="filter_fabric")
    colour = filters.CharFilter(method="filter_colour")
    size = filters.CharFilter(method="filter_size")
    min_price = filters.NumberFilter(field_name="base_price", lookup_expr="gte")
    max_price = filters.NumberFilter(field_name="base_price", lookup_expr="lte")
    on_sale = filters.BooleanFilter(method="filter_on_sale")
    new_in = filters.BooleanFilter(field_name="is_new_in")
    bestseller = filters.BooleanFilter(field_name="is_bestseller")
    featured = filters.BooleanFilter(field_name="is_featured")
    in_stock = filters.BooleanFilter(method="filter_in_stock")

    class Meta:
        model = Product
        fields = []

    @staticmethod
    def _values(value):
        return [v.strip() for v in value.split(",") if v.strip()]

    def filter_category(self, queryset, name, value):
        slugs = self._values(value)
        return queryset.filter(
            Q(category__slug__in=slugs) | Q(category__parent__slug__in=slugs)
        ).distinct()

    def filter_collection(self, queryset, name, value):
        return queryset.filter(collections__slug__in=self._values(value)).distinct()

    def filter_fabric(self, queryset, name, value):
        return queryset.filter(fabrics__slug__in=self._values(value)).distinct()

    def filter_colour(self, queryset, name, value):
        return queryset.filter(colours__name__in=self._values(value)).distinct()

    def filter_size(self, queryset, name, value):
        return queryset.filter(
            colours__variants__size__name__in=self._values(value),
            colours__variants__is_active=True,
        ).distinct()

    def filter_on_sale(self, queryset, name, value):
        on_sale = Q(compare_at_price__isnull=False) & Q(compare_at_price__gt=F("base_price"))
        return queryset.filter(on_sale) if value else queryset.exclude(on_sale)

    def filter_in_stock(self, queryset, name, value):
        return queryset.in_stock() if value else queryset
