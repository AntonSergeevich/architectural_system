"""Оплата: подпись, идемпотентность уведомлений, статусы счёта."""

import json
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse

from apps.crm.models import Client

from . import getplatinum
from .models import Invoice, Payment

PAYMENT_SETTINGS = dict(
    GETPLATINUM_MERCHANT_ID="merchant-1",
    GETPLATINUM_SECRET_KEY="secret",
    GETPLATINUM_API_URL="https://example.test/pay",
    PAYMENTS_ENABLED=True,
)


@override_settings(**PAYMENT_SETTINGS)
class WebhookTests(TestCase):
    def setUp(self):
        self.client_obj = Client.objects.create(name="Мария")
        self.invoice = Invoice.objects.create(
            client=self.client_obj,
            title="Первый этап",
            amount=Decimal("100000"),
            status=Invoice.Status.ISSUED,
        )

    def _signed(self, **extra):
        params = {
            "order_id": str(self.invoice.pk),
            "payment_id": "pay-1",
            "status": "success",
            "amount": "10000000",  # копейки
        }
        params.update(extra)
        params["signature"] = getplatinum.signature(params)
        return params

    def test_valid_notification_marks_invoice_paid(self):
        response = self.client.post(reverse("billing:webhook"), self._signed())
        self.assertEqual(response.status_code, 200)

        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, Invoice.Status.PAID)
        self.assertIsNotNone(self.invoice.paid_at)
        self.assertEqual(self.invoice.paid_amount, Decimal("100000"))

    def test_bad_signature_rejected(self):
        params = self._signed()
        params["signature"] = "0" * 64
        response = self.client.post(reverse("billing:webhook"), params)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Payment.objects.exists())

    def test_missing_signature_rejected(self):
        params = self._signed()
        del params["signature"]
        self.assertEqual(self.client.post(reverse("billing:webhook"), params).status_code, 400)

    def test_repeated_notification_does_not_double_the_payment(self):
        """Повторное уведомление — норма, так устроены вебхуки."""
        for _ in range(3):
            self.client.post(reverse("billing:webhook"), self._signed())

        self.assertEqual(Payment.objects.count(), 1)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.paid_amount, Decimal("100000"))

    def test_json_payload_accepted(self):
        response = self.client.post(
            reverse("billing:webhook"),
            data=json.dumps(self._signed()),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)

    def test_partial_payment_keeps_invoice_open(self):
        params = self._signed(amount="4000000")  # 40 000 ₽
        self.client.post(reverse("billing:webhook"), params)

        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, Invoice.Status.PARTIAL)
        self.assertEqual(self.invoice.left_to_pay, Decimal("60000"))
        self.assertTrue(self.invoice.is_payable)

    def test_failed_payment_does_not_count(self):
        self.client.post(reverse("billing:webhook"), self._signed(status="failed"))

        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.paid_amount, Decimal("0"))
        self.assertEqual(self.invoice.status, Invoice.Status.ISSUED)

    def test_unknown_invoice_rejected(self):
        params = {"order_id": "99999", "payment_id": "x", "status": "success", "amount": "100"}
        params["signature"] = getplatinum.signature(params)
        self.assertEqual(self.client.post(reverse("billing:webhook"), params).status_code, 400)


class PaymentsDisabledTests(TestCase):
    """Пока реквизитов нет, кнопка оплаты не показывается.

    Кнопка, ведущая в никуда, хуже её отсутствия.
    """

    def setUp(self):
        self.invoice = Invoice.objects.create(
            client=Client.objects.create(name="Мария"),
            title="Первый этап",
            amount=Decimal("50000"),
            status=Invoice.Status.ISSUED,
        )

    @override_settings(PAYMENTS_ENABLED=False)
    def test_invoice_page_offers_transfer_instead(self):
        response = self.client.get(self.invoice.get_absolute_url())
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Оплатить картой")
        self.assertContains(response, "реквизиты")

    @override_settings(PAYMENTS_ENABLED=False)
    def test_pay_redirects_with_message(self):
        response = self.client.post(reverse("billing:pay", args=[self.invoice.token]))
        self.assertRedirects(response, self.invoice.get_absolute_url())

    def test_manual_payment_closes_invoice(self):
        """Самозанятая принимает переводы и без эквайринга."""
        Payment.objects.create(
            invoice=self.invoice,
            provider=Payment.Provider.MANUAL,
            amount=Decimal("50000"),
            status=Payment.Status.SUCCEEDED,
        )
        self.invoice.refresh_status()
        self.assertEqual(self.invoice.status, Invoice.Status.PAID)
