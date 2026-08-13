"""Окончательное удаление карточек, пролежавших в архиве месяц.

Архив нужен не как «корзина на всякий случай», а как страховка от одного
неверного нажатия: месяца хватает, чтобы заметить ошибку. Дальше карточку
надо действительно удалять — хранить вечно данные человека, с которым
работа закончена, закон не разрешает, да и незачем.
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.crm.models import Client


class Command(BaseCommand):
    help = "Удалить заказчиков, пролежавших в архиве дольше срока хранения"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Показать, что будет удалено, и ничего не трогать",
        )

    def handle(self, *args, **options):
        edge = timezone.now() - timezone.timedelta(days=Client.ARCHIVE_DAYS)
        doomed = Client.objects.filter(archived_at__lt=edge)

        if not doomed:
            self.stdout.write("Архив пуст, удалять нечего.")
            return

        for client in doomed:
            self.stdout.write(f"{client.name} — в архиве с {client.archived_at:%d.%m.%Y}")

        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("Пробный запуск: ничего не удалено."))
            return

        count = doomed.count()
        for client in doomed:
            user = client.user
            # Порядок важен: проекты, договоры и счета связаны с заказчиком
            # защищённой связью — она стоит там намеренно, чтобы карточку
            # нельзя было снести случайно вместе с доказательной базой.
            # Здесь удаление осознанное, поэтому снимаем всё по очереди.
            client.invoices.all().delete()
            client.contracts.all().delete()
            client.projects.all().delete()
            client.properties.all().delete()
            client.delete()
            # Аккаунт уходит следом: без карточки он ведёт в никуда,
            # а лишний живой логин — это лишняя дверь.
            if user:
                user.delete()

        self.stdout.write(self.style.SUCCESS(f"Удалено карточек: {count}."))
