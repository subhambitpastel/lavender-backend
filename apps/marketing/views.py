from django.conf import settings
from django.core.mail import mail_admins
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import ContactMessage, HomeSection, JournalPost, NewsletterSubscriber, SiteSettings
from .serializers import (
    ContactMessageSerializer,
    HomeSectionSerializer,
    JournalCategorySerializer,
    JournalPostDetailSerializer,
    JournalPostListSerializer,
    NewsletterSerializer,
    SiteSettingsSerializer,
)


class JournalViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    lookup_field = "slug"
    permission_classes = [AllowAny]
    filterset_fields = {"category__slug": ["exact"], "is_featured": ["exact"]}
    search_fields = ("title", "excerpt", "body")
    ordering_fields = ("published_at", "created_at")

    def get_queryset(self):
        return JournalPost.objects.filter(is_published=True).select_related("category")

    def get_serializer_class(self):
        return (
            JournalPostDetailSerializer if self.action == "retrieve" else JournalPostListSerializer
        )


class JournalCategoryListView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(responses=JournalCategorySerializer(many=True))
    def get(self, request):
        from .models import JournalCategory

        categories = JournalCategory.objects.all()
        return Response(JournalCategorySerializer(categories, many=True).data)


class SiteContentView(APIView):
    """Announcement bar, USPs, footer, socials, FAQs — the storefront chrome."""

    permission_classes = [AllowAny]

    @extend_schema(responses=SiteSettingsSerializer)
    def get(self, request):
        site = SiteSettings.load()
        return Response(SiteSettingsSerializer(site, context={"request": request}).data)


class HomeContentView(APIView):
    """Ordered homepage blocks."""

    permission_classes = [AllowAny]

    @extend_schema(responses=HomeSectionSerializer(many=True))
    def get(self, request):
        sections = HomeSection.objects.filter(is_active=True).select_related("collection")
        return Response(
            HomeSectionSerializer(sections, many=True, context={"request": request}).data
        )


class NewsletterSubscribeView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(request=NewsletterSerializer, responses=NewsletterSerializer)
    def post(self, request):
        serializer = NewsletterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"].lower()
        subscriber, created = NewsletterSubscriber.objects.get_or_create(
            email=email,
            defaults={"source": serializer.validated_data.get("source", "footer")},
        )
        if not created and not subscriber.is_active:
            subscriber.is_active = True
            subscriber.save(update_fields=["is_active", "updated_at"])
        return Response(
            {"detail": "Thank you — welcome to Lavender Hill.", "email": email},
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class ContactView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(request=ContactMessageSerializer)
    def post(self, request):
        serializer = ContactMessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        message = ContactMessage.objects.create(**serializer.validated_data)
        mail_admins(
            f"Contact form: {message.subject or 'Enquiry'}",
            f"From {message.name} <{message.email}>\n\n{message.message}",
            fail_silently=True,
        )
        return Response(
            {"detail": "Thank you — we'll be in touch shortly."},
            status=status.HTTP_201_CREATED,
        )
