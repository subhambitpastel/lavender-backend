import pytest

from apps.marketing.models import HomeSection, JournalPost, NewsletterSubscriber, SiteSettings
from tests import factories


@pytest.mark.django_db
class TestSiteContent:
    def test_site_endpoint_creates_and_returns_the_singleton(self, api):
        response = api.get("/api/v1/content/site")
        assert response.status_code == 200
        assert "announcement_text" in response.data
        assert SiteSettings.objects.count() == 1

    def test_home_returns_active_blocks_in_order(self, api, db):
        HomeSection.objects.create(kind=HomeSection.Kind.HERO, title="Second", sort_order=2)
        HomeSection.objects.create(kind=HomeSection.Kind.EDITORIAL, title="First", sort_order=1)
        HomeSection.objects.create(kind=HomeSection.Kind.JOURNAL, title="Off", is_active=False)

        response = api.get("/api/v1/content/home")
        assert [b["title"] for b in response.data] == ["First", "Second"]

    def test_collection_rows_carry_their_products(self, api, product):
        collection = factories.CollectionFactory(name="New Arrivals")
        product.collections.add(collection)
        HomeSection.objects.create(
            kind=HomeSection.Kind.COLLECTION_ROW,
            title="New in",
            collection=collection,
            payload={"limit": 4},
        )
        response = api.get("/api/v1/content/home")
        assert response.data[0]["products"][0]["slug"] == product.slug


@pytest.mark.django_db
class TestJournal:
    def test_only_published_posts_are_listed(self, api, db):
        JournalPost.objects.create(title="Live", is_published=True)
        JournalPost.objects.create(title="Draft", is_published=False)
        response = api.get("/api/v1/journal/")
        assert [p["title"] for p in response.data["results"]] == ["Live"]

    def test_detail_includes_the_body_and_related_posts(self, api, db):
        from apps.marketing.models import JournalCategory

        category = JournalCategory.objects.create(name="Care")
        post = JournalPost.objects.create(
            title="How to care for cashmere", body="<p>Wash cool.</p>",
            category=category, is_published=True,
        )
        JournalPost.objects.create(title="Sibling", category=category, is_published=True)

        response = api.get(f"/api/v1/journal/{post.slug}/")
        assert response.data["body"] == "<p>Wash cool.</p>"
        assert response.data["related"][0]["title"] == "Sibling"


@pytest.mark.django_db
class TestNewsletterAndContact:
    def test_subscribe(self, api):
        response = api.post(
            "/api/v1/newsletter/subscribe", {"email": "Reader@Example.com"}, format="json"
        )
        assert response.status_code == 201
        assert NewsletterSubscriber.objects.get().email == "reader@example.com"

    def test_subscribing_twice_is_safe(self, api):
        api.post("/api/v1/newsletter/subscribe", {"email": "r@example.com"}, format="json")
        again = api.post("/api/v1/newsletter/subscribe", {"email": "r@example.com"}, format="json")
        assert again.status_code == 200
        assert NewsletterSubscriber.objects.count() == 1

    def test_invalid_email_is_rejected(self, api, db):
        response = api.post("/api/v1/newsletter/subscribe", {"email": "nope"}, format="json")
        assert response.status_code == 400

    def test_contact_form_stores_the_message(self, api, db):
        from apps.marketing.models import ContactMessage

        response = api.post(
            "/api/v1/contact",
            {"name": "Jo", "email": "jo@example.com", "subject": "Sizing", "message": "Help?"},
            format="json",
        )
        assert response.status_code == 201
        assert ContactMessage.objects.get().subject == "Sizing"
