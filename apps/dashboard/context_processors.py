def dashboard_context(request):
    """Counts for the sidebar badges, only for staff on dashboard pages."""
    if not request.path.startswith("/dashboard/"):
        return {}
    user = getattr(request, "user", None)
    if not (user and user.is_authenticated and user.is_staff):
        return {}

    from apps.catalog.models import Review
    from apps.marketing.models import ContactMessage
    from apps.orders.models import Order, Return

    return {
        # Orders still needing staff action (not yet shipped or closed off).
        "nav_pending_orders": Order.objects.filter(
            status__in=[
                Order.Status.DRAFT,
                Order.Status.CONFIRMED,
                Order.Status.FULFILLMENT,
            ]
        ).count(),
        "nav_pending_reviews": Review.objects.filter(status=Review.Status.PENDING).count(),
        "nav_pending_returns": Return.objects.filter(
            status=Return.Status.REQUESTED
        ).count(),
        "nav_pending_messages": ContactMessage.objects.filter(is_handled=False).count(),
    }
