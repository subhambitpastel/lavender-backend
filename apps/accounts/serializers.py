import phonenumbers
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .countries import COUNTRY_CODES
from .models import Address

User = get_user_model()

# The customer profile fields shared by "sign up" and "my account". Format checks
# live here (country whitelist, real phone validation); here we only decide which
# are required in each context.
PROFILE_FIELDS = ("first_name", "last_name", "phone", "location", "postcode", "country")


def validate_country(value):
    if value and value not in COUNTRY_CODES:
        raise serializers.ValidationError("Choose a country from the list.")
    return value


def validate_phone_number(value):
    """Validate a phone against Google's libphonenumber and normalise to E.164.

    The storefront sends the number in international format (e.g. ``+447700900123``),
    so a region hint isn't needed. Per-country validity is real, not a regex guess,
    and the stored value is always canonical E.164 — the scalable production choice.
    """
    if not value:
        return value
    try:
        parsed = phonenumbers.parse(value, None)
    except phonenumbers.NumberParseException:
        raise serializers.ValidationError(
            "Enter the number in international format, e.g. +44 7700 900123."
        )
    if not phonenumbers.is_valid_number(parsed):
        raise serializers.ValidationError("That doesn't look like a valid phone number.")
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


class UserSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)
    # Declared explicitly so the model's regex validator isn't copied on — phone
    # is validated authoritatively by libphonenumber in validate_phone().
    phone = serializers.CharField(required=False, allow_blank=True, validators=[])

    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "first_name",
            "last_name",
            "full_name",
            "phone",
            "location",
            "postcode",
            "country",
            "marketing_opt_in",
            "date_joined",
            "is_staff",
        )
        # Email is the login identity and never editable from the storefront.
        read_only_fields = ("id", "email", "date_joined", "is_staff")

    def validate_country(self, value):
        return validate_country(value)

    def validate_phone(self, value):
        return validate_phone_number(value)


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, validators=[validate_password])
    password_confirm = serializers.CharField(write_only=True, required=False)
    # Explicit (no model regex) so libphonenumber in validate_phone() is the sole
    # authority; required at signup.
    phone = serializers.CharField(required=True, allow_blank=False, validators=[])

    class Meta:
        model = User
        fields = (
            "email",
            "password",
            "password_confirm",
            *PROFILE_FIELDS,
            "marketing_opt_in",
        )
        # Signup collects the whole profile, so these are required here even
        # though the model keeps them optional (staff/seed accounts don't need them).
        # (phone is declared above, so it's excluded here.)
        extra_kwargs = {
            name: {"required": True, "allow_blank": False}
            for name in PROFILE_FIELDS
            if name != "phone"
        }

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return value.lower()

    def validate_country(self, value):
        return validate_country(value)

    def validate_phone(self, value):
        return validate_phone_number(value)

    def validate(self, attrs):
        confirm = attrs.pop("password_confirm", None)
        if confirm is not None and confirm != attrs["password"]:
            raise serializers.ValidationError({"password_confirm": "Passwords do not match."})
        return attrs

    def create(self, validated_data):
        return User.objects.create_user(**validated_data)


class CompleteAccountSerializer(serializers.Serializer):
    """Finish a guest account by setting a password.

    Proof of ownership is the order number + email placed in this browser — the
    BFF reads those from the httpOnly ``lh_last_order`` cookie, so only the
    shopper who just checked out can complete their own account.
    """

    number = serializers.CharField()
    email = serializers.EmailField()
    first_name = serializers.CharField(max_length=150)
    last_name = serializers.CharField(max_length=150)
    password = serializers.CharField(write_only=True, validators=[validate_password])
    password_confirm = serializers.CharField(write_only=True, required=False)

    def validate(self, attrs):
        confirm = attrs.pop("password_confirm", None)
        if confirm is not None and confirm != attrs["password"]:
            raise serializers.ValidationError({"password_confirm": "Passwords do not match."})
        return attrs


class AccountSetupSerializer(serializers.ModelSerializer):
    """Finish a passwordless guest account from the login flow — the same fields
    as sign-up, but the account already exists (keyed by email), so the email
    uniqueness check is dropped. The view enforces the account is still a guest.
    """

    password = serializers.CharField(write_only=True, validators=[validate_password])
    password_confirm = serializers.CharField(write_only=True, required=False)
    # Explicit (no model regex) so libphonenumber in validate_phone() is the sole
    # authority and the stored value is canonical E.164 — same as sign-up.
    phone = serializers.CharField(required=True, allow_blank=False, validators=[])

    class Meta:
        model = User
        fields = ("email", "password", "password_confirm", *PROFILE_FIELDS, "marketing_opt_in")
        extra_kwargs = {
            # The account already exists — don't reject the email as a duplicate.
            "email": {"validators": []},
            # phone is declared above, so it's excluded here.
            **{
                name: {"required": True, "allow_blank": False}
                for name in PROFILE_FIELDS
                if name != "phone"
            },
        }

    def validate_country(self, value):
        return validate_country(value)

    def validate_phone(self, value):
        return validate_phone_number(value)

    def validate(self, attrs):
        confirm = attrs.pop("password_confirm", None)
        if confirm is not None and confirm != attrs["password"]:
            raise serializers.ValidationError({"password_confirm": "Passwords do not match."})
        return attrs


class EmailTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Accept ``email`` instead of ``username`` and return the user alongside tokens."""

    username_field = User.USERNAME_FIELD

    def validate(self, attrs):
        data = super().validate(attrs)
        data["user"] = UserSerializer(self.user, context=self.context).data
        return data


class AddressSerializer(serializers.ModelSerializer):
    class Meta:
        model = Address
        fields = (
            "id",
            "label",
            "first_name",
            "last_name",
            "line1",
            "line2",
            "city",
            "county",
            "postcode",
            "country",
            "phone",
            "is_default_shipping",
            "is_default_billing",
        )


class PasswordChangeSerializer(serializers.Serializer):
    current_password = serializers.CharField()
    new_password = serializers.CharField(validators=[validate_password])

    def validate_current_password(self, value):
        user = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError("Your current password is incorrect.")
        return value


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()


class PasswordResetConfirmSerializer(serializers.Serializer):
    uid = serializers.CharField()
    token = serializers.CharField()
    new_password = serializers.CharField(validators=[validate_password])
