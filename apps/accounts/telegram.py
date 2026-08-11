"""Приём сообщений от бота: привязка кабинета к Telegram.

Как это устроено. Кабинет показывает кнопку со ссылкой
`t.me/<бот>?start=КОД`. Человек нажимает, Telegram открывает бота
и сам отправляет ему `/start КОД`. Бот пересылает это нам вебхуком —
и мы наконец узнаём chat_id.

Почему именно так, а не «введите свой chat_id»: своего chat_id
не знает никто, и просить его — значит не получить ни одной привязки.

Вебхук, а не постоянный опрос: опрос требует живого процесса, который
надо запускать, следить и перезапускать. Вебхук — обычный POST, который
приходит на тот же сервер, что и сайт.
"""

import json
import logging

from django.conf import settings
from django.http import HttpResponse, HttpResponseForbidden
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.core import notify

from .models import TelegramAccount

log = logging.getLogger(__name__)

HELP = (
    "Это бот кабинета. Чтобы получать уведомления по проекту, "
    "зайдите в кабинет и нажмите «Подключить Telegram» — "
    "бот откроется сам, с нужным кодом.\n\n"
    "Отключить уведомления: /stop"
)


@csrf_exempt
@require_POST
def webhook(request, secret):
    """Точка приёма обновлений от Telegram.

    Отвечаем 200 всегда: Telegram на любой другой ответ начинает
    повторять доставку, а повторять здесь нечего — все действия
    идемпотентны.
    """
    if not settings.TELEGRAM_WEBHOOK_SECRET or secret != settings.TELEGRAM_WEBHOOK_SECRET:
        return HttpResponseForbidden("нет")

    # Telegram умеет дублировать секрет заголовком — проверяем и его,
    # если он выставлен при регистрации вебхука.
    header = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if header and header != settings.TELEGRAM_WEBHOOK_SECRET:
        return HttpResponseForbidden("нет")

    try:
        update = json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return HttpResponse("ok")

    try:
        handle(update)
    except Exception:  # noqa: BLE001 — упавший обработчик не должен ломать доставку
        log.exception("Не смогли разобрать обновление Telegram")

    return HttpResponse("ok")


def handle(update):
    message = update.get("message") or update.get("edited_message") or {}
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    text = (message.get("text") or "").strip()
    if not chat_id:
        return

    if text.startswith("/start"):
        parts = text.split(maxsplit=1)
        code = parts[1].strip() if len(parts) > 1 else ""
        return start(chat_id, code, chat)

    if text.startswith("/stop"):
        return stop(chat_id)

    notify.send(HELP, chat_id)


def start(chat_id, code, chat):
    if not code:
        notify.send(HELP, chat_id)
        return

    account = TelegramAccount.objects.filter(link_code=code).select_related("user").first()
    if account is None:
        notify.send(
            "Код не подошёл. Откройте кабинет и нажмите «Подключить Telegram» ещё раз — "
            "ссылка выдаётся заново.",
            chat_id,
        )
        return

    # Один Telegram — один аккаунт. Иначе уведомления по чужому проекту
    # начнут приходить тому, кто просто открыл ссылку из переписки.
    TelegramAccount.objects.filter(chat_id=str(chat_id)).exclude(pk=account.pk).update(
        chat_id="", linked_at=None
    )

    from django.utils import timezone

    account.chat_id = str(chat_id)
    account.username = chat.get("username", "")[:64]
    account.linked_at = timezone.now()
    account.save(update_fields=["chat_id", "username", "linked_at"])

    notify.send(
        f"Готово, {notify.escape(account.user.get_short_name())}. "
        "Буду присылать сюда, что происходит по проекту: смена этапа, "
        "новые задачи для вас, сообщения и всё про деньги.\n\n"
        "Что именно присылать — настраивается в кабинете. "
        "Отключить совсем: /stop\n\n" + notify.link(reverse("cabinet:home")),
        chat_id,
    )


def stop(chat_id):
    account = TelegramAccount.objects.filter(chat_id=str(chat_id)).first()
    if account is None:
        notify.send("Этот чат и так не привязан.", chat_id)
        return
    account.unlink()
    notify.send(
        "Отключила уведомления. Кабинет продолжает работать как обычно — "
        "всё то же самое видно на сайте.",
        chat_id,
    )
