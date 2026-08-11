"""Оплата: подпись, идемпотентность уведомлений, статусы счёта."""

import json
from decimal import Decimal
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse

from apps.crm.models import Client

from . import getplatinum
from .models import Invoice, Payment

PAYMENT_SETTINGS = dict(
    GETPLATINUM_API_URL="https://example.getplatinum.ru/api/public/pay",
    GETPLATINUM_API_KEY="test-api-key",
    GETPLATINUM_VAT="none",
    PAYMENTS_ENABLED=True,
)


@override_settings(**PAYMENT_SETTINGS)
class WebhookTests(TestCase):
    def setUp(self):
        self.client_obj = Client.objects.create(name="Мария", email="m@example.ru")
        self.invoice = Invoice.objects.create(
            client=self.client_obj,
            title="Первый этап",
            amount=Decimal("100000"),
            status=Invoice.Status.ISSUED,
        )

    def _signed(self, **extra):
        params = {
            "notificationType": 1,
            "dealId": getplatinum.deal_id(self.invoice),
            "isSuccess": True,
            "offerId": 12345,
            "offerName": "Дизайн-проект",
            "paymentData": {
                "mdOrder": 53082785,
                "amount": 10000000,  # копейки
                "currency": "RUB",
                "commission": 15000,
                "commissionCurrency": "RUB",
                "paymentSystem": "sberbank",
                "type": 1,
            },
            "clientInfo": {"email": "m@example.ru", "phone": "+79130000001"},
        }
        params.update(extra)
        params["checksum"] = getplatinum.checksum(params)
        return params

    def _post(self, params):
        return self.client.post(
            reverse("billing:webhook"),
            data=json.dumps(params),
            content_type="application/json",
        )

    def test_valid_notification_marks_invoice_paid(self):
        response = self._post(self._signed())
        self.assertEqual(response.status_code, 200)

        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, Invoice.Status.PAID)
        self.assertIsNotNone(self.invoice.paid_at)
        self.assertEqual(self.invoice.paid_amount, Decimal("100000"))

    def test_bad_checksum_falls_back_to_status_check(self):
        """Выбросить уведомление с несошедшейся подписью нельзя.

        У GetPlatinum нет повторных попыток: любой ответ кроме 200 означает,
        что уведомление потеряно навсегда. Поэтому при расхождении подписи
        мы идём и спрашиваем статус платежа напрямую.
        """
        params = self._signed()
        params["checksum"] = "0" * 64

        with mock.patch.object(
            getplatinum,
            "fetch_status",
            return_value={
                "is_success": True,
                "payment_id": "53082785",
                "amount": Decimal("100000"),
                "payment_system": "sberbank",
                "raw": {},
            },
        ) as fetch:
            response = self._post(params)

        self.assertEqual(response.status_code, 200)
        fetch.assert_called_once()
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, Invoice.Status.PAID)

    def test_bad_checksum_and_unreachable_provider_changes_nothing(self):
        params = self._signed()
        params["checksum"] = "0" * 64

        with mock.patch.object(
            getplatinum, "fetch_status", side_effect=getplatinum.PaymentError("нет связи")
        ):
            response = self._post(params)

        self.assertEqual(response.status_code, 200)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, Invoice.Status.ISSUED)
        self.assertEqual(self.invoice.paid_amount, Decimal("0"))

    def test_repeated_notification_does_not_double_the_payment(self):
        """Повторное уведомление — норма, так устроены вебхуки."""
        for _ in range(3):
            self._post(self._signed())

        self.assertEqual(Payment.objects.count(), 1)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.paid_amount, Decimal("100000"))

    def test_partial_payment_keeps_invoice_open(self):
        params = self._signed()
        params["paymentData"] = dict(params["paymentData"], amount=4000000)  # 40 000 ₽
        params["checksum"] = getplatinum.checksum(params)
        self._post(params)

        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, Invoice.Status.PARTIAL)
        self.assertEqual(self.invoice.left_to_pay, Decimal("60000"))
        self.assertTrue(self.invoice.is_payable)

    def test_failed_payment_does_not_count(self):
        params = self._signed(isSuccess=False)
        params["checksum"] = getplatinum.checksum(params)
        self._post(params)

        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.paid_amount, Decimal("0"))
        self.assertEqual(self.invoice.status, Invoice.Status.ISSUED)

    def test_unknown_deal_is_accepted_but_ignored(self):
        """Отвечаем 200 всегда: иначе провайдер сочтёт нас сломанными."""
        params = {"dealId": "INV-99999", "isSuccess": True, "notificationType": 1}
        params["checksum"] = getplatinum.checksum(params)
        self.assertEqual(self._post(params).status_code, 200)
        self.assertFalse(Payment.objects.exists())

    def test_checksum_matches_documented_algorithm(self):
        """Проверка формулы на примере из документации GetPlatinum."""
        params = {
            "mdOrder": 53082785,
            "dealId": "DEAL-12345",
            "isSuccess": True,
            "amount": 10000,
            "currency": "RUB",
        }
        expected_string = (
            "amount;10000;currency;RUB;dealId;DEAL-12345;isSuccess;1;mdOrder;53082785;"
        )
        self.assertEqual(getplatinum._sign_string(params), expected_string)


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
