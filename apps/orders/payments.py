"""Payment provider seam.

Checkout only ever calls :func:`create_payment` / :func:`refund_payment`, so
swapping ``PAYMENT_PROVIDER=stripe`` later needs no changes in the order code.
"""

import uuid
from dataclasses import dataclass

from django.conf import settings


@dataclass
class PaymentResult:
    payment_ref: str
    client_secret: str
    status: str  # "paid" | "requires_action" | "failed"
    provider: str

    def as_dict(self):
        return {
            "payment_ref": self.payment_ref,
            "client_secret": self.client_secret,
            "status": self.status,
            "provider": self.provider,
        }


class BaseProvider:
    name = "base"

    def create_payment(self, order) -> PaymentResult:  # pragma: no cover - interface
        raise NotImplementedError

    def refund_payment(self, order) -> bool:  # pragma: no cover - interface
        raise NotImplementedError


class MockProvider(BaseProvider):
    """Marks the order paid immediately and hands back a fake client secret."""

    name = "mock"

    def create_payment(self, order) -> PaymentResult:
        ref = f"mock_pi_{uuid.uuid4().hex[:24]}"
        return PaymentResult(
            payment_ref=ref,
            client_secret=f"{ref}_secret_{uuid.uuid4().hex[:16]}",
            status="paid",
            provider=self.name,
        )

    def refund_payment(self, order) -> bool:
        return True


class StripeProvider(BaseProvider):
    """Placeholder for the real integration (M10).

    Implement with ``stripe.PaymentIntent.create(amount=..., currency=...)`` and
    confirm through the ``/api/v1/payments/webhook`` endpoint.
    """

    name = "stripe"

    def create_payment(self, order) -> PaymentResult:
        raise NotImplementedError(
            "StripeProvider is not wired up yet — set PAYMENT_PROVIDER=mock."
        )

    def refund_payment(self, order) -> bool:
        raise NotImplementedError


PROVIDERS = {"mock": MockProvider, "stripe": StripeProvider}


def get_provider() -> BaseProvider:
    return PROVIDERS.get(settings.PAYMENT_PROVIDER, MockProvider)()


def create_payment(order) -> PaymentResult:
    return get_provider().create_payment(order)


def refund_payment(order) -> bool:
    return get_provider().refund_payment(order)
