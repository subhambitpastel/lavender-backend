from django.urls import include, path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView, TokenVerifyView

from apps.accounts import views as account_views
from apps.cart import views as cart_views
from apps.catalog import views as catalog_views
from apps.marketing import views as marketing_views
from apps.orders import views as order_views
from apps.wishlist import views as wishlist_views

router = DefaultRouter()
router.register("products", catalog_views.ProductViewSet, basename="product")
router.register("categories", catalog_views.CategoryViewSet, basename="category")
router.register("collections", catalog_views.CollectionViewSet, basename="collection")
router.register("fabrics", catalog_views.FabricViewSet, basename="fabric")
router.register("sizes", catalog_views.SizeViewSet, basename="size")
router.register("journal", marketing_views.JournalViewSet, basename="journal")
router.register("addresses", account_views.AddressViewSet, basename="address")
router.register("orders", order_views.OrderViewSet, basename="order")

auth_patterns = [
    path("register", account_views.RegisterView.as_view(), name="auth-register"),
    path("complete", account_views.CompleteAccountView.as_view(), name="auth-complete"),
    path("login", account_views.LoginView.as_view(), name="auth-login"),
    path("refresh", TokenRefreshView.as_view(), name="auth-refresh"),
    path("verify", TokenVerifyView.as_view(), name="auth-verify"),
    path("logout", account_views.LogoutView.as_view(), name="auth-logout"),
    path("me", account_views.MeView.as_view(), name="auth-me"),
    path("password/change", account_views.PasswordChangeView.as_view(), name="password-change"),
    path("password/reset", account_views.PasswordResetRequestView.as_view(), name="password-reset"),
    path(
        "password/reset/confirm",
        account_views.PasswordResetConfirmView.as_view(),
        name="password-reset-confirm",
    ),
]

cart_patterns = [
    path("", cart_views.CartView.as_view(), name="cart"),
    path("items/", cart_views.CartItemsView.as_view(), name="cart-items"),
    path("items/<int:pk>/", cart_views.CartItemDetailView.as_view(), name="cart-item"),
    path("apply-discount/", cart_views.CartDiscountView.as_view(), name="cart-discount"),
    path("merge/", cart_views.CartMergeView.as_view(), name="cart-merge"),
]

content_patterns = [
    path("site", marketing_views.SiteContentView.as_view(), name="content-site"),
    path("home", marketing_views.HomeContentView.as_view(), name="content-home"),
]

urlpatterns = [
    # Must precede the router so it isn't swallowed by /orders/{number}/.
    path("orders/lookup/", order_views.OrderLookupView.as_view(), name="order-lookup"),
    path("", include(router.urls)),
    path("auth/", include(auth_patterns)),
    path("cart/", include(cart_patterns)),
    path("content/", include(content_patterns)),
    path("checkout/", order_views.CheckoutView.as_view(), name="checkout"),
    path("discounts/validate", order_views.DiscountPreviewView.as_view(), name="discount-validate"),
    path("search/", catalog_views.SearchView.as_view(), name="search"),
    path("wishlist/", wishlist_views.WishlistView.as_view(), name="wishlist"),
    path("wishlist/<slug:slug>/", wishlist_views.WishlistItemView.as_view(), name="wishlist-item"),
    path(
        "journal-categories/",
        marketing_views.JournalCategoryListView.as_view(),
        name="journal-categories",
    ),
    path("newsletter/subscribe", marketing_views.NewsletterSubscribeView.as_view(), name="newsletter"),
    path("contact", marketing_views.ContactView.as_view(), name="contact"),
    path("schema/", SpectacularAPIView.as_view(), name="schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
]
