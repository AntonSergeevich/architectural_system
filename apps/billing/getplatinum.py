"""Интеграция с платёжным сервисом GetPlatinum.

Написана по их OpenAPI-документации (Integration API GetPlatinum).
Весь код, зависящий от протокола провайдера, собран здесь: остальная
система знает только про счета и платежи.

Как это работает:

1. `create_payment()` дёргает `/init-payment-url` — это метод, который
   отдаёт ссылку на платёжную форму сразу, минуя двухшаговую схему
   «инициализация заказа → инициализация платежа». Нам не нужно
   показывать заказчику список платёжных систем: пусть выбирает
   на их форме.
2. Заказчик платит, GetPlatinum шлёт коллбэк на `notificationUrl`.
3. Коллбэк подписан HMAC-SHA256 по их схеме (см. `checksum`).

Три вещи, которые нужно знать про их коллбэк:

- **Он приходит ровно один раз.** Если мы ответим не 200, повторной
  попытки не будет — платёж останется неучтённым. Поэтому отвечаем 200
  всегда, а решение о зачислении принимаем отдельно.
- **Редирект на successUrl оплату не подтверждает.** Подтверждает только
  коллбэк. Это прямо написано в их документации, и это же логично:
  адрес «спасибо» можно открыть руками.
- **Подпись считается по вложенной структуре.** Объекты сериализуются
  в JSON, и здесь есть риск разойтись с их реализацией в мелочах
  (экранирование, пробелы). Поэтому при несовпадении подписи мы
  не выбрасываем уведомление, а идём проверять статус платежа
  напрямую через `/status`. Хуже несовпавшей подписи только потерянный
  платёж.
"""

import hashlib
import hmac
import json
import logging
from decimal import Decimal

import requests
from django.conf import settings
from django.urls import reverse

log = logging.getLogger(__name__)

TIMEOUT = 20

# Категория позиции для кассового чека. 9 — «Консультация (разовая или
# пакет)»: из их списка это единственное, что описывает услуги дизайнера
# без натяжки. Список у них заточен под инфобизнес.
POSITION_PREFIX = 9


class PaymentError(RuntimeError):
    """Провайдер не принял запрос или ответил непонятным."""


def is_enabled():
    return bool(settings.PAYMENTS_ENABLED)


def _api_url(path):
    base = settings.GETPLATINUM_API_URL.rstrip("/")
    return f"{base}/{path.lstrip('/')}"


def _headers():
    return {
        "Authorization": f"Bearer {settings.GETPLATINUM_API_KEY}",
        "Content-Type": "application/json",
    }


def _absolute(path):
    return f"{settings.SITE_URL.rstrip('/')}{path}"


def to_minor_units(amount):
    """Рубли → копейки. Все суммы у них передаются в минимальных единицах."""
    return int((Decimal(amount) * 100).quantize(Decimal("1")))


def from_minor_units(amount):
    try:
        return (Decimal(str(amount)) / 100).quantize(Decimal("0.01"))
    except (ArithmeticError, ValueError, TypeError):
        return Decimal("0")


def deal_id(invoice):
    """Наш идентификатор заказа на их стороне."""
    return f"INV-{invoice.pk}"


def invoice_id_from_deal(value):
    """Обратное преобразование. Возвращает None, если формат чужой."""
    if not value or not str(value).startswith("INV-"):
        return None
    try:
        return int(str(value)[4:])
    except ValueError:
        return None


# --- Контрольная подпись ----------------------------------------------------


def _sign_string(params):
    """Строка для подписи по алгоритму GetPlatinum.

    Ключи сортируются без учёта регистра, значения склеиваются в формате
    `<ключ>;<значение>;`. `checksum` и `customParams` исключаются, булевы
    значения превращаются в 1/0, вложенные структуры — в JSON.
    """
    parts = []
    for key in sorted(params, key=str.lower):
        if key in {"checksum", "customParams"}:
            continue
        value = params[key]
        if isinstance(value, bool):
            value = 1 if value else 0
        elif isinstance(value, (dict, list)):
            # Компактный JSON без пробелов и с экранированием не-ASCII —
            # так же ведут себя json_encode в PHP и JSON.stringify в JS,
            # на которых написаны их примеры.
            value = json.dumps(value, ensure_ascii=True, separators=(",", ":"))
        elif value is None:
            value = ""
        parts.append(f"{key};{value};")
    return "".join(parts)


def checksum(params, api_key=None):
    """HMAC-SHA256 в верхнем регистре — как у них."""
    api_key = api_key or settings.GETPLATINUM_API_KEY
    return (
        hmac.new(api_key.encode(), _sign_string(params).encode(), hashlib.sha256)
        .hexdigest()
        .upper()
    )


def verify_checksum(params):
    """Проверить подпись входящего уведомления.

    Сравнение — постоянным по времени методом: обычное «==» на секретах
    позволяет подобрать подпись по времени ответа.
    """
    received = str(params.get("checksum") or "")
    if not received:
        return False
    return hmac.compare_digest(received.upper(), checksum(params))


# --- Создание платежа -------------------------------------------------------


def _positions(invoice, amount):
    return [
        {
            "prefix": POSITION_PREFIX,
            "name": invoice.title[:120],
            "price": to_minor_units(amount),
            "quantity": 1,
            "vat": settings.GETPLATINUM_VAT,
        }
    ]


def _client_params(invoice):
    """Данные покупателя.

    Телефон или почта обязательны: без них у них не формируется кассовый
    чек, и заказ просто не создастся.
    """
    client = invoice.client
    params = {"clientId": f"CLIENT-{client.pk}", "name": client.name}
    if client.email:
        params["email"] = client.email
    if client.phone:
        params["phone"] = client.phone
    return params


def create_payment(invoice, amount=None):
    """Создать платёж и получить ссылку на форму оплаты.

    Возвращает (form_url, deal_id).
    """
    if not is_enabled():
        raise PaymentError("Приём оплат не настроен: заполните GETPLATINUM_* в .env")

    amount = invoice.left_to_pay if amount is None else Decimal(amount)
    if amount <= 0:
        raise PaymentError("Счёт уже оплачен")

    if not invoice.client.email and not invoice.client.phone:
        # Ошибка на их стороне была бы невнятной, а причина простая.
        raise PaymentError(
            "У заказчика не заполнены ни почта, ни телефон — "
            "платёжный сервис не сможет отправить кассовый чек"
        )

    payload = {
        "dealId": deal_id(invoice),
        "currency": "RUB",
        "amount": to_minor_units(amount),
        "positions": _positions(invoice, amount),
        "clientParams": _client_params(invoice),
        "notificationUrl": _absolute(reverse("billing:webhook")),
        "successUrl": _absolute(reverse("billing:return_success", args=[invoice.token])),
        "failUrl": _absolute(reverse("billing:return_fail", args=[invoice.token])),
    }

    try:
        response = requests.post(
            _api_url("init-payment-url"), json=payload, headers=_headers(), timeout=TIMEOUT
        )
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        log.exception("GetPlatinum: запрос init-payment-url не прошёл")
        raise PaymentError("Платёжный сервис недоступен, попробуйте позже") from exc
    except ValueError as exc:
        log.exception("GetPlatinum: ответ не разобрался как JSON")
        raise PaymentError("Платёжный сервис ответил непонятным") from exc

    if data.get("errorCode"):
        log.error("GetPlatinum: ошибка %s — %s", data.get("errorCode"), data.get("errorMessage"))
        raise PaymentError(data.get("errorMessage") or "Платёжный сервис отклонил запрос")

    form_url = data.get("formUrl")
    if not form_url:
        log.error("GetPlatinum: в ответе нет formUrl: %s", data)
        raise PaymentError("Платёжный сервис не вернул ссылку на оплату")

    return form_url, str(data.get("dealId") or payload["dealId"])


# --- Уведомление и сверка ---------------------------------------------------


def parse_notification(params):
    """Разобрать коллбэк об оплате в термины системы."""
    payment_data = params.get("paymentData") or {}
    return {
        "notification_type": params.get("notificationType"),
        "deal_id": params.get("dealId"),
        "invoice_id": invoice_id_from_deal(params.get("dealId")),
        "is_success": bool(params.get("isSuccess")),
        "payment_id": str(payment_data.get("mdOrder") or ""),
        "amount": from_minor_units(payment_data.get("amount") or 0),
        "commission": from_minor_units(payment_data.get("commission") or 0),
        "payment_system": payment_data.get("paymentSystem") or "",
    }


def fetch_status(invoice):
    """Спросить у GetPlatinum, оплачен ли заказ.

    Нужно в двух случаях: когда не сошлась подпись коллбэка и когда
    коллбэк вообще не дошёл. Для второго есть команда `sync_payments`.
    """
    if not is_enabled():
        raise PaymentError("Приём оплат не настроен")

    try:
        response = requests.post(
            _api_url("status"),
            json={"dealId": deal_id(invoice)},
            headers=_headers(),
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        log.exception("GetPlatinum: запрос status не прошёл")
        raise PaymentError("Не удалось получить статус платежа") from exc

    return {
        "is_success": bool(data.get("isSuccess")),
        "payment_id": str(data.get("mdOrder") or ""),
        "amount": from_minor_units(data.get("amount") or 0),
        "payment_system": data.get("paymentSystem") or "",
        "raw": data,
    }
