from django.urls import path

from . import views

app_name = "dashboard"

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("", views.home, name="home"),

    # products
    path("products/", views.product_list, name="product_list"),
    path("products/new/", views.product_form, name="product_create"),
    path("products/<int:pk>/edit/", views.product_form, name="product_edit"),
    path("products/<int:pk>/delete/", views.product_delete, name="product_delete"),
    path("products/<int:pk>/toggle/", views.product_toggle_active, name="product_toggle"),

    # product editor — HTMX partials
    path("colours/<int:colour_id>/images/", views.colour_images_upload, name="colour_images_upload"),
    path("colours/<int:colour_id>/images/reorder/", views.colour_images_reorder, name="colour_images_reorder"),
    path("colours/<int:colour_id>/stock/", views.colour_stock_save, name="colour_stock_save"),
    path("colours/<int:colour_id>/delete/", views.colour_delete, name="colour_delete"),
    path("images/<int:image_id>/delete/", views.colour_image_delete, name="image_delete"),
    path("images/<int:image_id>/primary/", views.colour_image_primary, name="image_primary"),

    # inventory
    path("inventory/", views.inventory, name="inventory"),
    path("inventory/bulk/", views.inventory_bulk_save, name="inventory_bulk"),
    path("inventory/<int:pk>/quick/", views.inventory_quick_update, name="inventory_quick"),

    # taxonomy
    path("categories/", views.category_list, name="category_list"),
    path("collections/", views.collection_list, name="collection_list"),
    path("fabrics/", views.fabric_list, name="fabric_list"),
    path("sizes/", views.size_list, name="size_list"),
    path("taxonomy/<str:kind>/<int:pk>/delete/", views.taxonomy_delete, name="taxonomy_delete"),

    # orders
    path("orders/", views.order_list, name="order_list"),
    path("orders/<str:number>/", views.order_detail, name="order_detail"),
    path("orders/<str:number>/status/", views.order_set_status, name="order_status"),
    path("orders/<str:number>/cancel/", views.order_cancel, name="order_cancel"),

    # returns
    path("returns/", views.return_list, name="return_list"),
    path("returns/<str:number>/<str:action>/", views.return_resolve, name="return_resolve"),

    # customers
    path("customers/", views.customer_list, name="customer_list"),
    path("customers/<int:pk>/", views.customer_detail, name="customer_detail"),

    # discounts
    path("discounts/", views.discount_list, name="discount_list"),
    path("discounts/<int:pk>/delete/", views.discount_delete, name="discount_delete"),

    # reviews
    path("reviews/", views.review_list, name="review_list"),
    path("reviews/<int:pk>/", views.review_detail, name="review_detail"),
    path("reviews/<int:pk>/<str:action>/", views.review_moderate, name="review_moderate"),

    # journal
    path("journal/", views.journal_list, name="journal_list"),
    path("journal/new/", views.journal_form, name="journal_create"),
    path("journal/<int:pk>/edit/", views.journal_form, name="journal_edit"),
    path("journal/<int:pk>/delete/", views.journal_delete, name="journal_delete"),
    path("journal/categories/<int:pk>/delete/", views.journal_category_delete, name="journal_category_delete"),

    # content
    path("content/", views.content_settings, name="content_settings"),
    path("content/sections/new/", views.home_section_form, name="home_section_create"),
    path("content/sections/<int:pk>/edit/", views.home_section_form, name="home_section_edit"),
    path("content/sections/<int:pk>/<str:action>/", views.home_section_action, name="home_section_action"),

    # newsletter
    path("newsletter/", views.newsletter_list, name="newsletter_list"),
    path("newsletter/export/", views.newsletter_export, name="newsletter_export"),
    path("messages/", views.contact_message_list, name="contact_list"),
    path("newsletter/messages/<int:pk>/handled/", views.contact_message_handled, name="contact_handled"),
]
