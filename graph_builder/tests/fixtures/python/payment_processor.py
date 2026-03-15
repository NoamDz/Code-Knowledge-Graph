"""Payment processing service."""

import json
from typing import Optional
from .base_service import BaseService
from ..models.payment import Payment, PaymentStatus
from ..utils.logging import get_logger

logger = get_logger(__name__)


class PaymentProcessor(BaseService):
    """Handles payment processing logic."""

    DEFAULT_CURRENCY = "USD"

    def __init__(self, gateway_client):
        super().__init__()
        self.gateway = gateway_client
        self._cache = {}

    def process_payment(self, amount: float, currency: str = None) -> Payment:
        currency = currency or self.DEFAULT_CURRENCY
        logger.info(f"Processing payment: {amount} {currency}")
        result = self.gateway.charge(amount, currency)
        payment = Payment(amount=amount, currency=currency, status=PaymentStatus.COMPLETED)
        self._update_cache(payment)
        return payment

    def refund(self, payment_id: str) -> Optional[Payment]:
        payment = self._lookup(payment_id)
        if not payment:
            return None
        self.gateway.refund(payment_id)
        payment.status = PaymentStatus.REFUNDED
        return payment

    def _update_cache(self, payment):
        self._cache[payment.id] = payment

    def _lookup(self, payment_id):
        return self._cache.get(payment_id)

    @staticmethod
    def validate_amount(amount):
        return amount > 0
