"""Уведомления Дарье о том, что произошло на сайте.

Пока канал один — Telegram. Причина простая: почту она смотрит раз
в день, а заявка без быстрого ответа — это заявка, ушедшая к тому,
кто ответил первым. Регламент обещает сутки рабочего времени, но
обещание держит человек, а не система: система обязана хотя бы
вовремя ткнуть.

Правило номер один: **уведомление не имеет права уронить заявку.**
Заявка уже в базе, и если Telegram лежит, недоступен или токен
протух — это проблема уведомления, а не заказчика, который только что
заполнил форму. Поэтому здесь всё завёрнуто в try/except и уходит
в журнал.

Токен бота живёт ТОЛЬКО в переменных окружения (`.env` на сервере,
права 600). В репозитории его нет и быть не может: репозиторий
публичный, а по токену бота можно писать от имени Дарьи.
"""

import logging

import requests
from django.conf import settings
from django.urls import reverse

log = logging.getLogger(__name__)

TIMEOUT = 5  # секунд: дольше ждать нельзя — за нами стоит живой запрос


def enabled():
    return bool(settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID)


def send(text):
    """Отправить сообщение в Telegram. Возвращает True, если ушло."""
    if not enabled():
        log.info("Telegram не настроен, сообщение не отправлено: %s", text[:80])
        return False

    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        response = requests.post(
            url,
            json={
                "chat_id": settings.TELEGRAM_CHAT_ID,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=TIMEOUT,
        )
        if response.status_code != 200:
            log.warning("Telegram ответил %s: %s", response.status_code, response.text[:200])
            return False
        return True
    except requests.RequestException as error:
        # Сеть отвалилась — заявка от этого не пострадала.
        log.warning("Telegram недоступен: %s", error)
        return False


def escape(value):
    """Экранирование для parse_mode=HTML.

    Имя заказчика приходит из формы, и «<b>» в имени не должно ни
    ломать разметку, ни превращаться в неё.
    """
    return (
        str(value or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def new_lead(lead):
    """Заявка с сайта."""
    client = lead.client
    lines = [
        "<b>Заявка с сайта</b>",
        f"Имя: {escape(client.name)}",
    ]
    if client.phone:
        lines.append(f"Телефон: {escape(client.phone)}")
    if client.email:
        lines.append(f"Почта: {escape(client.email)}")
    if lead.estate:
        lines.append(
            f"Объект: {escape(lead.estate.city)}, "
            f"{lead.estate.area} м², {lead.estate.rooms} помещений"
        )
    if lead.message:
        lines.append(f"Сообщение: {escape(lead.message[:500])}")
    lines.append(
        f"Ответить до: {lead.next_action_at:%d.%m %H:%M}"
        if lead.next_action_at
        else "Срок ответа не проставлен"
    )
    lines.append(f"{settings.SITE_URL}{reverse('cabinet:lead_detail', args=[lead.pk])}")
    return send("\n".join(lines))
