"""Уведомления: что происходит в системе — тому, кого это касается.

Канал один — Telegram. Причина простая: почту смотрят раз в день,
а заявка без быстрого ответа уходит к тому, кто ответил первым.
Заказчику же нужно другое — знать, что проект движется, и не писать
за этим в личку.

Два правила, которые здесь важнее всего.

**Уведомление не имеет права уронить действие.** Заявка уже в базе,
сообщение уже отправлено, договор уже подписан. Если Telegram лежит,
токен протух или сеть моргнула — это проблема уведомления, а не человека,
который только что нажал кнопку. Поэтому всё завёрнуто в try/except
и уходит в журнал.

**Уведомления добровольные.** Дарья получает их на свой chat_id
из настроек сервера, заказчик — только если сам нажал кнопку привязки
в кабинете. Рассылать тому, кто не просил, нельзя.

Токен бота живёт ТОЛЬКО в переменных окружения (`.env` на сервере,
права 600). В репозитории его нет и быть не может: по токену бота можно
писать от имени Дарьи.
"""

import logging

import requests
from django.conf import settings
from django.urls import reverse

log = logging.getLogger(__name__)

TIMEOUT = 5  # секунд: дольше ждать нельзя — за нами стоит живой запрос


def enabled():
    """Бот настроен вообще."""
    return bool(settings.TELEGRAM_BOT_TOKEN)


def api(method, payload):
    """Вызов Telegram Bot API. Возвращает ответ или None."""
    if not enabled():
        log.info("Telegram не настроен, метод %s не вызван", method)
        return None
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/{method}",
            json=payload,
            timeout=TIMEOUT,
        )
        if response.status_code != 200:
            log.warning("Telegram %s ответил %s: %s", method, response.status_code, response.text[:200])
            return None
        return response.json()
    except requests.RequestException as error:
        log.warning("Telegram недоступен (%s): %s", method, error)
        return None


def send(text, chat_id=None):
    """Отправить сообщение. Без chat_id — Дарье, на адрес из настроек."""
    target = chat_id or settings.TELEGRAM_CHAT_ID
    if not target:
        log.info("Некому отправлять, сообщение не ушло: %s", text[:80])
        return False
    return bool(
        api(
            "sendMessage",
            {
                "chat_id": target,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
        )
    )


def escape(value):
    """Экранирование для parse_mode=HTML.

    Имя заказчика приходит из формы, и «<b>» в имени не должно ни ломать
    разметку, ни превращаться в неё.
    """
    return (
        str(value or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def link(path):
    return f"{settings.SITE_URL}{path}"


# --- Кому отправлять --------------------------------------------------------


def to_user(user, text, kind="message"):
    """Сообщение конкретному человеку — если он сам подключил бота.

    `kind` сверяется с его же настройками: тот, кто отключил сообщения,
    не должен получать их «в порядке исключения».
    """
    if user is None:
        return False
    account = getattr(user, "telegram", None)
    if account is None or not account.is_linked or not account.wants(kind):
        return False
    return send(text, account.chat_id)


def to_owner(text):
    """Дарье — на адрес из настроек и всем владельцам с привязкой.

    Адрес в настройках остаётся основным путём: он работает ещё до того,
    как кто-нибудь нажмёт кнопку привязки.
    """
    sent = send(text)

    from apps.accounts.models import Role, TelegramAccount

    for account in TelegramAccount.objects.filter(user__role=Role.OWNER).exclude(chat_id=""):
        if account.chat_id != str(settings.TELEGRAM_CHAT_ID):
            sent = send(text, account.chat_id) or sent
    return sent


def safe(function, *args, **kwargs):
    """Позвать уведомление так, чтобы оно ничего не уронило."""
    try:
        return function(*args, **kwargs)
    except Exception:  # noqa: BLE001 — здесь важно поймать вообще всё
        log.exception("Уведомление не отправилось")
        return False


# --- События ----------------------------------------------------------------


def new_lead(lead):
    """Заявка с сайта — Дарье."""
    client = lead.client
    lines = ["<b>Заявка с сайта</b>", f"Имя: {escape(client.name)}"]
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
    lines.append(link(reverse("cabinet:lead_detail", args=[lead.pk])))
    return to_owner("\n".join(lines))


def _project_user(project):
    client = getattr(project, "client", None)
    return getattr(client, "user", None) if client else None


def stage_changed(stage):
    """Этап поменял статус — заказчику.

    Ровно то, ради чего заказчик пишет «а что там у нас». Пусть лучше
    приходит само.
    """
    project = stage.project
    text = (
        f"<b>{escape(project)}</b>\n"
        f"Этап {stage.number}: {escape(stage.title)} — "
        f"{escape(stage.get_status_display().lower())}"
    )
    if stage.waiting_on == "client":
        text += "\n\nНужно ваше согласование."
    text += f"\n{link(reverse('cabinet:my_project'))}"
    return to_user(_project_user(project), text, kind="stage")


def task_for_client(task):
    """Новая задача на заказчике."""
    project = task.stage.project
    text = (
        f"<b>{escape(project)}</b>\n"
        f"От вас нужно: {escape(task.title)}"
    )
    if task.due_date:
        text += f"\nСрок: {task.due_date:%d.%m}"
    if task.comment:
        text += f"\n{escape(task.comment)}"
    text += f"\n{link(reverse('cabinet:my_project'))}"
    return to_user(_project_user(project), text, kind="task")


def new_message(message):
    """Сообщение в переписке — другой стороне."""
    project = message.project
    body = escape(message.text[:300]) if message.text else "приложен файл"
    text = f"<b>{escape(message.author_name)}</b> по проекту «{escape(project)}»:\n{body}"

    if message.author_is_owner:
        return to_user(
            _project_user(project),
            text + f"\n{link(reverse('cabinet:my_project'))}",
            kind="message",
        )
    return to_owner(text + f"\n{link(reverse('cabinet:project_detail', args=[project.pk]))}")


def budget_change(change):
    """Изменение сметы — заказчику, на согласование."""
    project = change.project
    text = (
        f"<b>{escape(project)}</b>\n"
        f"Изменение сметы: {escape(change.title)} — {change.amount:+.0f} ₽\n\n"
        f"Почему: {escape(change.reason[:400])}\n\n"
        f"Нужно ваше решение: {link(reverse('cabinet:my_project'))}#money"
    )
    return to_user(_project_user(project), text, kind="money")


def budget_decided(change):
    """Решение заказчика по смете — Дарье."""
    verdict = "согласовано" if change.status == "accepted" else "отклонено"
    text = (
        f"<b>{escape(change.project)}</b>\n"
        f"Изменение сметы {verdict}: {escape(change.title)} ({change.amount:+.0f} ₽)"
    )
    if change.client_comment:
        text += f"\n«{escape(change.client_comment)}»"
    return to_owner(text)


def contract_sent(contract):
    """Договор отправлен заказчику."""
    text = (
        f"<b>{escape(contract.project)}</b>\n"
        f"Договор на подпись: {escape(contract.template.title)}\n"
        f"Скачать и подписать: {link(reverse('cabinet:my_project'))}#contracts"
    )
    return to_user(_project_user(contract.project), text, kind="money")


def contract_signed(contract):
    """Заказчик вернул подписанный экземпляр — Дарье."""
    text = (
        f"<b>{escape(contract.project)}</b>\n"
        f"Подписан договор: {escape(contract.template.title)}\n"
        f"Подписал: {escape(contract.signed_by)}"
    )
    return to_owner(text)
