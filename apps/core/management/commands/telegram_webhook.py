"""Регистрация вебхука бота.

Telegram не знает, куда слать сообщения, пока ему это не сказали.
Команда говорит: адрес — вот такой, секрет — вот такой. Делается один
раз после установки и ещё раз, если сменился домен.

Без вебхука бот работает наполовину: писать он умеет (уведомления
уходят), а слышать — нет, и кнопка «Подключить Telegram» не сработает.
"""

from django.conf import settings
from django.core.management.base import BaseCommand
from django.urls import reverse

from apps.core import notify


class Command(BaseCommand):
    help = "Зарегистрировать (или снять) вебхук Telegram-бота"

    def add_arguments(self, parser):
        parser.add_argument(
            "--delete", action="store_true", help="Снять вебхук вместо регистрации"
        )
        parser.add_argument(
            "--info", action="store_true", help="Показать, что сейчас зарегистрировано"
        )

    def handle(self, *args, **options):
        if not settings.TELEGRAM_BOT_TOKEN:
            self.stdout.write(self.style.ERROR("Пустой TELEGRAM_BOT_TOKEN в .env."))
            return

        if options["info"]:
            data = notify.api("getWebhookInfo", {})
            self.stdout.write(str(data))
            return

        if options["delete"]:
            notify.api("deleteWebhook", {})
            self.stdout.write(self.style.SUCCESS("Вебхук снят."))
            return

        if not settings.TELEGRAM_WEBHOOK_SECRET:
            self.stdout.write(
                self.style.ERROR(
                    "Пустой TELEGRAM_WEBHOOK_SECRET в .env.\n"
                    "Сгенерировать: python3 -c \"import secrets;print(secrets.token_urlsafe(24))\""
                )
            )
            return

        if not settings.SITE_URL.startswith("https://"):
            self.stdout.write(
                self.style.ERROR(
                    f"SITE_URL = {settings.SITE_URL}. Telegram принимает вебхук только "
                    "по HTTPS — сначала выпустите сертификат."
                )
            )
            return

        url = settings.SITE_URL + reverse(
            "accounts:telegram_webhook", args=[settings.TELEGRAM_WEBHOOK_SECRET]
        )
        answer = notify.api(
            "setWebhook",
            {
                "url": url,
                # Секрет дублируется заголовком: адрес мог утечь из логов
                # прокси, заголовок туда не попадает.
                "secret_token": settings.TELEGRAM_WEBHOOK_SECRET,
                "allowed_updates": ["message"],
                "drop_pending_updates": True,
            },
        )
        if answer and answer.get("ok"):
            self.stdout.write(self.style.SUCCESS(f"Вебхук зарегистрирован: {url}"))
        else:
            self.stdout.write(self.style.ERROR(f"Не получилось: {answer}"))
