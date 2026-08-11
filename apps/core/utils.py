"""Мелкие утилиты, нужные нескольким приложениям."""

import re
import secrets
from datetime import timedelta

from django.utils import timezone

_DIGITS = re.compile(r"\D+")


def normalize_phone(raw):
    """Приводит телефон к виду +7XXXXXXXXXX.

    Один и тот же человек оставляет номер пятью способами, и без нормализации
    он превращается в пять разных заказчиков.
    """
    if not raw:
        return ""
    digits = _DIGITS.sub("", str(raw))
    if len(digits) == 11 and digits[0] == "8":
        digits = "7" + digits[1:]
    if len(digits) == 10:
        digits = "7" + digits
    if len(digits) == 11 and digits[0] == "7":
        return "+" + digits
    return "+" + digits if digits else ""


def format_money(value):
    """15000 → «15 000 ₽». Неразрывные пробелы, чтобы сумма не переносилась."""
    if value is None:
        return ""
    return f"{int(round(value)):,}".replace(",", " ") + " ₽"


def public_token(length=22):
    """Токен для публичной ссылки на расчёт или счёт."""
    return secrets.token_urlsafe(length)[:length]


def working_deadline(start, hours=24, day_start=10, day_end=19, workdays=(0, 1, 2, 3, 4)):
    """Когда истекает срок ответа, если считать его в рабочих часах.

    Регламент Дарьи — «отвечу в течение суток в рабочее время». Календарные
    сутки здесь не годятся: вопрос, заданный вечером пятницы, иначе получает
    срок «суббота», которой в регламенте нет. Считаем только рабочие часы
    и получаем честное «отвечу до понедельника, 19:00», которое можно
    показать человеку сразу при отправке вопроса.
    """
    remaining = timedelta(hours=hours)
    cursor = timezone.localtime(start)
    # Ограничение на всякий случай: длинные праздники не должны крутить цикл
    # бесконечно, если в настройках окажется пустой список рабочих дней.
    for _ in range(400):
        if cursor.weekday() not in workdays:
            cursor = (cursor + timedelta(days=1)).replace(
                hour=day_start, minute=0, second=0, microsecond=0
            )
            continue

        day_open = cursor.replace(hour=day_start, minute=0, second=0, microsecond=0)
        day_close = cursor.replace(hour=day_end, minute=0, second=0, microsecond=0)

        if cursor < day_open:
            cursor = day_open
        if cursor >= day_close:
            cursor = (cursor + timedelta(days=1)).replace(
                hour=day_start, minute=0, second=0, microsecond=0
            )
            continue

        available = day_close - cursor
        if remaining <= available:
            return cursor + remaining
        remaining -= available
        cursor = (cursor + timedelta(days=1)).replace(
            hour=day_start, minute=0, second=0, microsecond=0
        )
    return cursor
