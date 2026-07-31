from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

from apps.cart.utils import merge_guest_cart

from .models import Address
from .serializers import (
    AccountSetupSerializer,
    AddressSerializer,
    CompleteAccountSerializer,
    EmailTokenObtainPairSerializer,
    PasswordChangeSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    RegisterSerializer,
    UserSerializer,
)

User = get_user_model()


class LoginView(TokenObtainPairView):
    """POST {email, password} → {access, refresh, user}. Merges any guest cart."""

    serializer_class = EmailTokenObtainPairSerializer
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        email = (request.data.get("email") or "").strip()
        user = User.objects.filter(email__iexact=email).first()
        # A guest who checked out has a passwordless account. Rather than a plain
        # "not recognised", send them to finish setting it up.
        if user is not None and not user.has_usable_password():
            return Response(
                {
                    "code": "needs_account",
                    "email": user.email,
                    "detail": "You've ordered as a guest — finish setting up your account to sign in.",
                },
                status=status.HTTP_409_CONFLICT,
            )
        response = super().post(request, *args, **kwargs)
        if response.status_code == 200 and user:
            merge_guest_cart(request, user)
            # Signing in proves this email is theirs — attach any orders placed
            # as a guest with it (left ownerless on purpose at checkout).
            from apps.orders.services import claim_guest_orders

            claim_guest_orders(user)
        return response


class RegisterView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(request=RegisterSerializer, responses=UserSerializer)
    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        merge_guest_cart(request, user)
        refresh = RefreshToken.for_user(user)
        return Response(
            {
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "user": UserSerializer(user, context={"request": request}).data,
            },
            status=status.HTTP_201_CREATED,
        )


class CompleteAccountView(APIView):
    """Turn the passwordless guest account from checkout into a real one.

    Proof is the order number + email (the BFF passes them from the httpOnly
    cookie set at checkout), so only the shopper who placed the order can finish
    it. Returns JWTs so they're signed in immediately.
    """

    permission_classes = [AllowAny]

    @extend_schema(request=CompleteAccountSerializer, responses=UserSerializer)
    def post(self, request):
        from apps.orders.models import Order

        serializer = CompleteAccountSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        email = data["email"].lower()

        order = Order.objects.filter(number=data["number"], email__iexact=email).first()
        if order is None:
            return Response(
                {"detail": "We couldn't match that order.", "code": "no_order"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = User.objects.filter(email__iexact=email).first()
        if user is None:
            return Response(
                {"detail": "There's no account to complete for this order.", "code": "no_account"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if user.has_usable_password():
            return Response(
                {"detail": "You already have an account — please sign in.", "code": "account_exists"},
                status=status.HTTP_409_CONFLICT,
            )

        user.set_password(data["password"])
        user.first_name = data["first_name"]
        user.last_name = data["last_name"]
        user.is_active = True
        user.save(update_fields=["password", "first_name", "last_name", "is_active"])

        # The order shipped without a name (collected here) — backfill it so the
        # delivery label is complete.
        address = order.shipping_address or {}
        if isinstance(address, dict) and not address.get("first_name"):
            address["first_name"] = data["first_name"]
            address["last_name"] = data["last_name"]
            order.shipping_address = address
            order.save(update_fields=["shipping_address", "updated_at"])

        merge_guest_cart(request, user)
        refresh = RefreshToken.for_user(user)
        return Response(
            {
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "user": UserSerializer(user, context={"request": request}).data,
            },
            status=status.HTTP_201_CREATED,
        )


class AccountSetupView(APIView):
    """Finish a passwordless guest account from the LOGIN flow — set a password
    and profile, then sign in.

    NOTE (security): this is email-only by product decision — there is no
    order-number or email-verification proof, so anyone who knows a guest's email
    can claim their account (and its order history / address). Add verification
    to harden.
    """

    permission_classes = [AllowAny]

    @extend_schema(request=AccountSetupSerializer, responses=UserSerializer)
    def post(self, request):
        serializer = AccountSetupSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        user = User.objects.filter(email__iexact=data["email"]).first()
        if user is None:
            return Response(
                {"detail": "There's no guest account for that email — please sign up.", "code": "no_account"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if user.has_usable_password():
            return Response(
                {"detail": "You already have an account — please sign in.", "code": "account_exists"},
                status=status.HTTP_409_CONFLICT,
            )

        user.set_password(data["password"])
        for field in ("first_name", "last_name", "phone", "location", "postcode", "country"):
            setattr(user, field, data[field])
        user.marketing_opt_in = data.get("marketing_opt_in", False)
        user.is_active = True
        user.save()

        merge_guest_cart(request, user)
        refresh = RefreshToken.for_user(user)
        return Response(
            {
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "user": UserSerializer(user, context={"request": request}).data,
            },
            status=status.HTTP_201_CREATED,
        )


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=UserSerializer)
    def get(self, request):
        return Response(UserSerializer(request.user, context={"request": request}).data)

    @extend_schema(request=UserSerializer, responses=UserSerializer)
    def patch(self, request):
        serializer = UserSerializer(
            request.user, data=request.data, partial=True, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class LogoutView(APIView):
    """Blacklist the supplied refresh token."""

    permission_classes = [AllowAny]

    def post(self, request):
        token = request.data.get("refresh")
        if token:
            try:
                RefreshToken(token).blacklist()
            except Exception:
                pass
        return Response({"detail": "Signed out."})


class PasswordChangeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = PasswordChangeSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        request.user.set_password(serializer.validated_data["new_password"])
        request.user.save(update_fields=["password"])
        return Response({"detail": "Password updated."})


class PasswordResetRequestView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = User.objects.filter(email__iexact=serializer.validated_data["email"]).first()
        if user:
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = default_token_generator.make_token(user)
            link = f"{settings.FRONTEND_URL}/account/reset-password?uid={uid}&token={token}"
            send_mail(
                "Reset your Lavender Hill password",
                f"Use this link to choose a new password:\n\n{link}\n",
                settings.DEFAULT_FROM_EMAIL,
                [user.email],
                fail_silently=True,
            )
        # Always 200 so the endpoint can't be used to enumerate accounts.
        return Response({"detail": "If that email exists, a reset link is on its way."})


class PasswordResetConfirmView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            uid = force_str(urlsafe_base64_decode(serializer.validated_data["uid"]))
            user = User.objects.get(pk=uid)
        except (User.DoesNotExist, ValueError, TypeError, OverflowError):
            return Response(
                {"detail": "That reset link is invalid."}, status=status.HTTP_400_BAD_REQUEST
            )
        if not default_token_generator.check_token(user, serializer.validated_data["token"]):
            return Response(
                {"detail": "That reset link has expired."}, status=status.HTTP_400_BAD_REQUEST
            )
        user.set_password(serializer.validated_data["new_password"])
        user.save(update_fields=["password"])
        return Response({"detail": "Password reset. You can sign in now."})


class AddressViewSet(viewsets.ModelViewSet):
    serializer_class = AddressSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None
    filter_backends = []

    def get_queryset(self):
        return Address.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)
