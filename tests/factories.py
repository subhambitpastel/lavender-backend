import factory
from django.contrib.auth import get_user_model

from apps.catalog.models import (
    Category,
    Collection,
    Fabric,
    Product,
    ProductColour,
    ProductVariant,
    Review,
    Size,
)
from apps.orders.models import Discount

User = get_user_model()


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User
        django_get_or_create = ("email",)

    email = factory.Sequence(lambda n: f"customer{n}@example.com")
    first_name = "Test"
    last_name = "Customer"

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        password = kwargs.pop("password", "testpass123")
        return model_class.objects.create_user(password=password, **kwargs)


class StaffFactory(UserFactory):
    email = factory.Sequence(lambda n: f"staff{n}@example.com")
    is_staff = True


class CategoryFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Category
        django_get_or_create = ("name",)

    name = factory.Sequence(lambda n: f"Category {n}")


class CollectionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Collection
        django_get_or_create = ("name",)

    name = factory.Sequence(lambda n: f"Collection {n}")


class FabricFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Fabric
        django_get_or_create = ("name",)

    name = factory.Sequence(lambda n: f"Fabric {n}")


class SizeFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Size
        django_get_or_create = ("name",)

    name = factory.Sequence(lambda n: f"S{n}")
    sort_order = factory.Sequence(lambda n: n)


class ProductFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Product

    name = factory.Sequence(lambda n: f"Product {n}")
    description = "A lovely thing."
    category = factory.SubFactory(CategoryFactory)
    base_price = 100


class ProductColourFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ProductColour

    product = factory.SubFactory(ProductFactory)
    name = factory.Sequence(lambda n: f"Colour {n}")
    swatch_hex = "#DCD3C6"


class ProductVariantFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ProductVariant

    colour = factory.SubFactory(ProductColourFactory)
    size = factory.SubFactory(SizeFactory)
    stock_quantity = 10


class ReviewFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Review

    product = factory.SubFactory(ProductFactory)
    author_name = "Reviewer"
    rating = 5
    body = "Excellent."
    is_approved = True
    status = factory.LazyAttribute(lambda o: "approved" if o.is_approved else "pending")


class DiscountFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Discount

    code = factory.Sequence(lambda n: f"CODE{n}")
    kind = Discount.Kind.PERCENT
    value = 10
