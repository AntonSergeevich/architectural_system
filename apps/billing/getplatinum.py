"""Интеграция с платёжным сервисом GetPlatinum.

Весь код, зависящий от конкретного протокола провайдера, собран здесь.
Остальная система знает только про счета и платежи — сменить или добавить
провайдера означает написать второй такой файл, а не править половину
проекта.

ВНИМАНИЕ. Точный формат запроса, набор полей и алгоритм подписи берутся
из документации личного кабинета GetPlatinum. Ниже реализована самая
распространённая схема (HMAC-SHA256 по отсортированным параметрам),
и три места, которые почти наверняка придётся поправить под реальный
протокол, помечены как TODO. Все они локальные: имена полей в `_payload`,
формула подписи в `signature` и разбор уведомления в `parse_callback`.

Пока реквизиты не заданы в .env, приём оплат выключен: кнопка не
показывается, счёт остаётся с ручной отметкой об оплате. Это лучше, чем
кнопка, ведущая в никуда.
"""

import hashlib
import hmac
import logging
from decimal import Decimal

import requests
from django.conf import settings
from django.urls import reverse

log = logging.getLogger(__name__)

TIMEOUT = 15


class PaymentError(RuntimeError):
    """Провайдер не принял запрос или ответил непонятным."""


def is_enabled():
    return bool(settings.PAYMENTS_ENABLED)


def signature(params, secret=None):
    """Подпись запроса.

    TODO: сверить с документацией GetPlatinum. Здесь — типовая схема:
    параметры сортируются по имени, склеиваются через «&» в виде
    «ключ=значение», от строки берётся HMAC-SHA256 на секретном ключе.
    """
    secret = secret or settings.GETPLATINUM_SECRET_KEY
    payload = "&".join(
        f"{key}={params[key]}" for key in sorted(params) if key != "signature" and params[key] != ""
    )
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def verify_signature(params):
    """Проверить подпись входящего уведомления.

    Сравнение — постоянным по времени методом: обычное «==» на секретах
    даёт возможность подобрать подпись по времени ответа.
    """
    received = str(params.get("signature", ""))
    if not received:
        return False
    return hmac.compare_digest(received.lower(), signature(params).lower())


def _absolute(path):
    return f"{settings.SITE_URL.rstrip('/')}{path}"


def _payload(invoice, amount):
    """Тело запроса на создание платежа.

    TODO: имена полей — под документацию GetPlatinum.
    """
    params = {
        "merchant_id": settings.GETPLATINUM_MERCHANT_ID,
        "order_id": str(invoice.pk),
        # Сумма в копейках: почти все платёжные сервисы принимают целое,
        # и это заодно снимает вопрос округления дробных рублей.
        "amount": str(int((Decimal(amount) * 100).quantize(Decimal("1")))),
        "currency": "RUB",
        "description": invoice.title[:200],
        "success_url": _absolute(reverse("billing:return_success", args=[invoice.token])),
        "fail_url": _absolute(reverse("billing:return_fail", args=[invoice.token])),
        "callback_url": _absolute(reverse("billing:webhook")),
        "test": "1" if settings.GETPLATINUM_TEST_MODE else "0",
    }
    params["signature"] = signature(params)
    return params


def create_payment(invoice, amount=None):
    """Создать платёж и получить ссылку на оплату.

    Возвращает (payment_url, provider_payment_id).
    """
    if not is_enabled():
        raise PaymentError(
            "Приём оплат не настроен: заполните GETPLATINUM_* в .env"
        )

    amount = amount if amount is not None else invoice.left_to_pay
    if amount <= 0:
        raise PaymentError("Счёт уже оплачен")

    try:
        response = requests.post(
            settings.GETPLATINUM_API_URL,
            json=_payload(invoice, amount),
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        log.exception("GetPlatinum: запрос не прошёл")
        raise PaymentError("Платёжный сервис недоступен") from exc
    except ValueError as exc:
        log.exception("GetPlatinum: ответ не разобрался как JSON")
        raise PaymentError("Платёжный сервис ответил непонятным") from exc

    # TODO: имена полей ответа — под документацию GetPlatinum.
    url = data.get("payment_url") or data.get("url") or data.get("redirect_url")
    payment_id = str(data.get("payment_id") or data.get("id") or "")
    if not url:
        log.error("GetPlatinum: в ответе нет ссылки на оплату: %s", data)
        raise PaymentError("Платёжный сервис не вернул ссылку на оплату")
    return url, payment_id


def parse_callback(params):
    """Разобрать уведомление об оплате.

    Возвращает словарь в терминах системы. TODO: имена полей и набор
    статусов — под документацию GetPlatinum.
    """
    status_map = {
        "success": "succeeded",
        "succeeded": "succeeded",
        "paid": "succeeded",
        "fail": "failed",
        "failed": "failed",
        "canceled": "failed",
        "cancelled": "failed",
        "refund": "refunded",
        "refunded": "refunded",
    }
    raw_status = str(params.get("status", "")).lower()
    raw_amount = params.get("amount") or "0"
    try:
        # Сумма приходит в копейках — тем же способом, каким уходила.
        amount = (Decimal(str(raw_amount)) / 100).quantize(Decimal("0.01"))
    except (ArithmeticError, ValueError):
        amount = Decimal("0")

    return {
        "invoice_id": params.get("order_id"),
        "payment_id": str(params.get("payment_id") or params.get("id") or ""),
        "status": status_map.get(raw_status, "pending"),
        "amount": amount,
    }
