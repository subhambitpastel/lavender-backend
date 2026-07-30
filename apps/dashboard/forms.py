from django import forms
from django.contrib.auth import get_user_model
from django.forms import inlineformset_factory

from apps.catalog.models import (
    Category,
    Collection,
    Fabric,
    Product,
    ProductColour,
    ProductImage,
    ProductVariant,
    Review,
    Size,
)
from apps.marketing.models import HomeSection, JournalCategory, JournalPost, SiteSettings
from apps.orders.models import Discount, Order

User = get_user_model()


class StyledFormMixin:
    """Give every widget the dashboard's input classes.

    Also applies two rules uniformly across every dashboard form:

    * a ``slug`` field is never required — the model generates one from the
      name on save, so leaving it blank is the normal path;
    * uploads are never rejected for having a long filename. Django's storage
      shortens the stored name to fit the column, so the only thing the form's
      ``max_length`` achieved was blocking legitimate files.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if isinstance(field, forms.FileField):
                field.max_length = None
            if name == "slug":
                field.required = False
                field.widget.attrs.setdefault(
                    "placeholder", "auto-generated from the name"
                )
                if not field.help_text:
                    field.help_text = "Leave blank to generate one from the name."

            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault("class", "check")
            elif isinstance(widget, forms.SelectMultiple):
                widget.attrs.setdefault("class", "input input--multi")
            elif isinstance(widget, forms.Select):
                widget.attrs.setdefault("class", "input")
            elif isinstance(widget, forms.Textarea):
                widget.attrs.setdefault("class", "input input--area")
                widget.attrs.setdefault("rows", 4)
            elif isinstance(widget, forms.ClearableFileInput):
                widget.attrs.setdefault("class", "input input--file")
            else:
                widget.attrs.setdefault("class", "input")


class StaffLoginForm(StyledFormMixin, forms.Form):
    email = forms.EmailField(widget=forms.EmailInput(attrs={"autofocus": True, "placeholder": "you@lavenderhill.com"}))
    password = forms.CharField(widget=forms.PasswordInput(attrs={"placeholder": "••••••••"}))


# --------------------------------------------------------------------- catalog


class ProductForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Product
        fields = (
            "name",
            "slug",
            "description",
            "category",
            "fabrics",
            "collections",
            "base_price",
            "compare_at_price",
            "is_active",
            "is_featured",
            "is_new_in",
            "is_bestseller",
            "composition",
            "care_instructions",
            "sustainability_note",
            "meta_title",
            "meta_description",
            "sort_order",
        )
        widgets = {
            "slug": forms.TextInput(attrs={"placeholder": "auto-generated from the name"}),
            "fabrics": forms.CheckboxSelectMultiple,
            "collections": forms.CheckboxSelectMultiple,
        }
        help_texts = {
            "compare_at_price": "Set this above the price to mark the product as on sale.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["fabrics"].widget.attrs.pop("class", None)
        self.fields["collections"].widget.attrs.pop("class", None)

    def clean(self):
        cleaned = super().clean()
        base = cleaned.get("base_price")
        compare = cleaned.get("compare_at_price")
        if base is not None and compare is not None and compare <= base:
            self.add_error(
                "compare_at_price",
                "The compare-at price must be higher than the price (or left blank).",
            )
        return cleaned


class ProductColourForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = ProductColour
        fields = ("name", "swatch_hex", "sort_order", "is_active")
        widgets = {
            "swatch_hex": forms.TextInput(attrs={"type": "color", "class": "input input--colour"}),
        }

    def _row_was_filled_in(self):
        """Did the user put anything into this row — name, stock or images?

        Stock and images post outside the formset's own fields (they're keyed
        ``<prefix>-stock_<size_id>`` / ``<prefix>-images``), so the formset can't
        see them. Without this, a row with stock typed in but no name looks
        untouched and everything entered is dropped on save.
        """
        prefix = f"{self.prefix}-"
        if (self.data.get(self.add_prefix("name")) or "").strip():
            return True
        for key, value in self.data.items():
            if key.startswith(f"{prefix}stock_") and str(value).strip():
                return True
        if hasattr(self.files, "getlist") and any(self.files.getlist(f"{prefix}images")):
            return True
        return False

    def has_changed(self):
        """An empty new row is an untouched spare, not a colour to validate.

        Django only validates extra formset rows that report a change, but a
        ``type="color"`` input *always* posts a value and lowercases it, so the
        default comparison ("#DCD3C6" vs "#dcd3c6") marked every blank spare row
        as edited — which then failed on the required name.
        """
        if self.instance.pk:
            return super().has_changed()
        return self._row_was_filled_in()

    def clean(self):
        cleaned = super().clean()
        # Reached when stock or images were entered but the name was left blank:
        # say what to do rather than let the generic "required" carry the blame.
        if not cleaned.get("name") and self._row_was_filled_in():
            self.add_error(
                "name",
                "Name this colour — its stock and images are saved against it.",
            )
        return cleaned


ProductColourFormSet = inlineformset_factory(
    Product, ProductColour, form=ProductColourForm, extra=1, can_delete=True
)


class ProductImageForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = ProductImage
        fields = ("image", "alt_text", "sort_order", "is_primary")


ProductImageFormSet = inlineformset_factory(
    ProductColour, ProductImage, form=ProductImageForm, extra=0, can_delete=True
)


class ProductVariantForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = ProductVariant
        fields = ("size", "sku", "stock_quantity", "price_override", "is_active")
        widgets = {
            "stock_quantity": forms.NumberInput(attrs={"min": 0, "class": "input input--stock"}),
            "sku": forms.TextInput(attrs={"placeholder": "auto"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["sku"].required = False


ProductVariantFormSet = inlineformset_factory(
    ProductColour, ProductVariant, form=ProductVariantForm, extra=0, can_delete=True
)


class CategoryForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Category
        fields = (
            "name",
            "slug",
            "description",
            "image",
            "parent",
            "sort_order",
            "is_active",
            "show_in_nav",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["parent"].queryset = Category.objects.exclude(pk=self.instance.pk)


class CollectionForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Collection
        fields = ("name", "slug", "description", "hero_image", "sort_order", "is_active")


class FabricForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Fabric
        fields = ("name", "slug", "description", "image", "sort_order", "is_active")


class SizeForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Size
        fields = ("name", "sort_order")


class ReviewForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Review
        fields = ("author_name", "author_location", "rating", "title", "body", "is_verified", "is_approved")


# ---------------------------------------------------------------------- orders


class OrderStatusForm(StyledFormMixin, forms.ModelForm):
    # Delivery status is changed with the one-click buttons in the "Delivery
    # status" card, so it isn't in this form — this handles payment & notes.
    class Meta:
        model = Order
        fields = ("payment_status", "tracking_number", "staff_note")


def suggest_discount_codes(base, *, limit=5, exclude_pk=None):
    """Free alternative codes near ``base``, for when the entered one is taken.

    Numeric bumps first (SUMMER2, SUMMER3…) plus a few word variants, each
    checked against every code already in use so every suggestion is guaranteed
    available for the admin to pick.
    """
    base = (base or "").strip().upper()
    if not base:
        return []
    taken = set(Discount.objects.values_list("code", flat=True))
    if exclude_pk is not None:
        own = Discount.objects.filter(pk=exclude_pk).values_list("code", flat=True).first()
        taken.discard(own)
    seeds = [f"{base}2", f"{base}NEW", f"{base}3", f"{base}SAVE", f"{base}25", f"{base}PLUS"]
    seeds += [f"{base}{n}" for n in range(4, 60)]
    out = []
    for candidate in seeds:
        if len(candidate) <= 40 and candidate not in taken and candidate not in out:
            out.append(candidate)
        if len(out) >= limit:
            break
    return out


class DiscountForm(StyledFormMixin, forms.ModelForm):
    # Populated by clean_code when the entered code clashes — the template offers
    # these as one-tap alternatives.
    code_suggestions = []

    class Meta:
        model = Discount
        # Just the essentials: a code always applies (active, no minimum spend, no
        # start/end window, no usage cap) until it's deleted.
        fields = ("code", "description", "kind", "value")
        labels = {"code": "Title"}
        help_texts = {"code": "The code customers type at checkout, e.g. SUMMER10."}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # All four fields are required now — description is optional on the model,
        # so force it here.
        self.fields["description"].required = True
        self.code_suggestions = []

    def clean_code(self):
        code = (self.cleaned_data.get("code") or "").strip().upper()
        clash = Discount.objects.filter(code=code)
        if self.instance and self.instance.pk:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            self.code_suggestions = suggest_discount_codes(
                code, exclude_pk=self.instance.pk if self.instance else None
            )
            raise forms.ValidationError(
                f"The code “{code}” already exists — choose another, "
                "or pick one of the suggestions below."
            )
        return code


# -------------------------------------------------------------------- content


class JournalPostForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = JournalPost
        fields = (
            "title",
            "slug",
            "category",
            "excerpt",
            "body",
            "hero_image",
            "author",
            "read_minutes",
            "is_published",
            "is_featured",
            "published_at",
        )
        widgets = {
            "body": forms.Textarea(attrs={"rows": 16, "class": "input input--area input--rich"}),
            "published_at": forms.DateTimeInput(
                attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["published_at"].input_formats = ["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S"]


class JournalCategoryForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = JournalCategory
        fields = ("name", "slug", "sort_order")


class SiteSettingsForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = SiteSettings
        fields = (
            "announcement_text",
            "announcement_href",
            "announcement_active",
            "free_shipping_threshold",
            "usp_items",
            "footer_links",
            "faqs",
            "social_instagram",
            "social_facebook",
            "social_pinterest",
            "contact_email",
            "contact_phone",
            "studio_address",
            "about_body",
            "currency",
        )
        widgets = {
            # data-editor turns each raw-JSON textarea into a friendly row editor
            # (see static/dashboard/content-editors.js). The textarea stays as the
            # value store and a raw-JSON fallback if the script can't run.
            "usp_items": forms.Textarea(
                attrs={"rows": 5, "class": "input input--area input--json", "data-editor": "usp"}
            ),
            "footer_links": forms.Textarea(
                attrs={"rows": 8, "class": "input input--area input--json", "data-editor": "footer"}
            ),
            "faqs": forms.Textarea(
                attrs={"rows": 10, "class": "input input--area input--json", "data-editor": "faq"}
            ),
        }
        help_texts = {
            "usp_items": "Trust badges shown across the storefront — pick an icon and write the label.",
            "footer_links": "Columns of links in the site footer. Add columns and links, drag to reorder.",
            "faqs": "Questions for the FAQ page. The group heading buckets related questions together.",
        }


class HomeSectionForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = HomeSection
        fields = (
            "kind",
            "eyebrow",
            "title",
            "subtitle",
            "cta_label",
            "cta_href",
            "image",
            "collection",
            "payload",
            "sort_order",
            "is_active",
        )
        widgets = {
            "payload": forms.Textarea(attrs={"rows": 6, "class": "input input--area input--json"}),
        }


class CustomerForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = User
        fields = (
            "first_name",
            "last_name",
            "email",
            "phone",
            "marketing_opt_in",
            "is_active",
            "is_staff",
        )
