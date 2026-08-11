"""Напоминание о заявках, по которым просрочен следующий шаг.

Это техническое решение боли «заявки теряются». Не «напоминалка вообще»,
а конкретно: заявка без сделанного следующего шага не может тихо пролежать
неделю.

Запускается по cron только в рабочие часы будних дней. Присылать такое
в воскресенье было бы нарушением того самого регламента, который система
обязана защищать — в том числе от самой Дарьи.
"""

from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.core.models import SiteSettings
from apps.crm.models import Lead


class Command(BaseCommand):
    help = "Присылает список заявок с просроченным следующим шагом"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Показать список, ничего не отправляя",
        )

    def handle(self, *args, **options):
        site = SiteSettings.get()
        now = timezone.localtime()

        if now.weekday() not in site.workdays or not (
            site.workday_start <= now.hour < site.workday_end
        ):
            self.stdout.write("Нерабочее время — не беспокоим.")
            return

        overdue = (
            Lead.objects.select_related("client")
            .exclude(status__in=[Lead.Status.WON, Lead.Status.LOST])
            .filter(next_action_at__lt=timezone.now())
            .order_by("next_action_at")
        )
        if not overdue:
            self.stdout.write("Просроченных заявок нет.")
            return

        lines = [
            f"• {lead.client.name} — {lead.next_action} "
            f"(должно было быть {timezone.localtime(lead.next_action_at):%d.%m %H:%M})"
            for lead in overdue
        ]
        body = "Заявки, по которым просрочен следующий шаг:\n\n" + "\n".join(lines)
        body += f"\n\nКабинет: {settings.SITE_URL.rstrip('/')}/cabinet/zayavki/"

        if options["dry_run"] or not site.email:
            self.stdout.write(body)
            return

        send_mail(
            subject=f"Просрочено заявок: {len(lines)}",
            message=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[site.email],
            fail_silently=False,
        )
        self.stdout.write(self.style.SUCCESS(f"Отправлено. Просрочено: {len(lines)}."))
