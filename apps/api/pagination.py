from rest_framework.pagination import PageNumberPagination


class StandardPagination(PageNumberPagination):
    """12 per page to match the PLP grid; `?page_size=` up to 60."""

    page_size = 12
    page_size_query_param = "page_size"
    # Generous ceiling so the storefront's cumulative "load more" can request
    # page*pageSize rows in a single call.
    max_page_size = 120
