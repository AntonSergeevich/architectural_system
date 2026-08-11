"""Проверка, что бот настроен и пишет Дарье.

Нужна ровно один раз — после установки. Настройка уведомлений имеет
свойство «вроде сделали», а выясняется это на первой потерянной заявке.
"""

from django.core.management.base import BaseCommand

from apps.core import notify


class Command(BaseCommand):
    help = "Отправить проверочное сообщение в Telegram"

    def handle(self, *args, **options):
        if not notify.enabled():
            self.stdout.write(
                self.style.ERROR(
                    "Telegram не настроен: в .env пустые TELEGRAM_BOT_TOKEN "
                    "или TELEGRAM_CHAT_ID.\n"
                    "Токен берётся у @BotFather, chat_id — из "
                    "https://api.telegram.org/bot<ТОКЕН>/getUpdates "
                    "после любого сообщения боту."
                )
            )
            return

        ok = notify.send(
            "<b>Проверка связи</b>\n"
            "Если вы это видите — уведомления о заявках будут приходить сюда."
        )
        if ok:
            self.stdout.write(self.style.SUCCESS("Отправлено. Проверьте Telegram."))
        else:
            self.stdout.write(
                self.style.ERROR(
                    "Не отправилось. Частые причины: неверный токен, "
                    "неверный chat_id, либо вы ещё не написали боту первым — "
                    "боты не могут начинать переписку сами."
                )
            )
