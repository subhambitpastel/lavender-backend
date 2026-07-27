from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.core.validators import RegexValidator
from django.db import models

from apps.core.models import TimeStamped

from .countries import COUNTRIES

# Shared, permissive-but-real validators. They only run when a value is present
# (blank fields skip validation), so optional fields stay optional.
phone_validator = RegexValidator(
    r"^\+?[0-9][0-9\s\-()]{6,19}$",
    "Enter a valid phone number — 7–20 digits, e.g. +44 7700 900123.",
)
postcode_validator = RegexValidator(
    r"^[A-Za-z0-9][A-Za-z0-9\s\-]{1,9}$",
    "Enter a valid postal / PIN code, e.g. SW1A 1AA or 560001.",
)


class UserManager(BaseUserManager):
    """Manager for the email-login user model."""

    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("An email address is required.")
        email = self.normalize_email(email)
        extra_fields.setdefault("username", email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")
        return self._create_user(email, password, **extra_fields)


class User(AbstractUser):
    """Customer / staff account. Login is by email."""

    email = models.EmailField("email address", unique=True)
    username = models.CharField(max_length=150, blank=True, null=True, unique=False)
    phone = models.CharField(max_length=32, blank=True, validators=[phone_validator])
    # Basic profile location — captured at signup, editable in "My account".
    # Distinct from the shipping Address book below (that's for checkout).
    location = models.CharField("town / city", max_length=120, blank=True)
    postcode = models.CharField(
        "postal / PIN code", max_length=16, blank=True, validators=[postcode_validator]
    )
    country = models.CharField(max_length=2, blank=True, default="GB", choices=COUNTRIES)
    marketing_opt_in = models.BooleanField(default=False)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    class Meta:
        ordering = ("-date_joined",)

    def __str__(self):
        return self.email

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip() or self.email


class Address(TimeStamped):
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="addresses", null=True, blank=True
    )
    label = models.CharField(max_length=64, blank=True, help_text="e.g. Home, Work")
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    line1 = models.CharField("address line 1", max_length=255)
    line2 = models.CharField("address line 2", max_length=255, blank=True)
    city = models.CharField(max_length=120)
    county = models.CharField(max_length=120, blank=True)
    postcode = models.CharField(max_length=20)
    country = models.CharField(max_length=2, default="GB")
    phone = models.CharField(max_length=32, blank=True)
    is_default_shipping = models.BooleanField(default=False)
    is_default_billing = models.BooleanField(default=False)

    class Meta:
        ordering = ("-is_default_shipping", "-created_at")
        verbose_name_plural = "addresses"

    def __str__(self):
        return f"{self.first_name} {self.last_name}, {self.line1}, {self.postcode}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.user_id:
            if self.is_default_shipping:
                Address.objects.filter(user=self.user).exclude(pk=self.pk).update(
                    is_default_shipping=False
                )
            if self.is_default_billing:
                Address.objects.filter(user=self.user).exclude(pk=self.pk).update(
                    is_default_billing=False
                )

    def as_snapshot(self):
        """Plain dict stored on orders so history survives address edits."""
        return {
            "first_name": self.first_name,
            "last_name": self.last_name,
            "line1": self.line1,
            "line2": self.line2,
            "city": self.city,
            "county": self.county,
            "postcode": self.postcode,
            "country": self.country,
            "phone": self.phone,
        }
