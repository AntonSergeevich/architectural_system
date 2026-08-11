"""Сверка незакрытых счетов с GetPlatinum.

Коллбэк приходит ровно один раз и повторов у него нет: если он не дошёл —
упала сеть, перезагружался сервер, — платёж останется неучтённым, а Дарья
будет считать заказчика должником. Раз в час проходим по счетам, где
оплата начиналась, но не завершилась, и спрашиваем статус напрямую.
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.billing import getplatinum
from apps.billing.models import Invoice, Payment


class Command(BaseCommand):
    help = "Сверяет незакрытые счета со статусом платежа в GetPlatinum"

    def add_arguments(self, parser):
        parser.add_argument(
            "--hours", type=int, default=72,
            help="Насколько старые счета проверять (по умолчанию 72 часа)",
        )

    def handle(self, *args, **options):
        if not getplatinum.is_enabled():
            self.stdout.write("Приём оплат не настроен — сверять нечего.")
            return

        since = timezone.now() - timezone.timedelta(hours=options["hours"])
        invoices = (
            Invoice.objects.filter(
                status__in=[Invoice.Status.ISSUED, Invoice.Status.PARTIAL],
                payments__provider=Payment.Provider.GETPLATINUM,
                payments__status=Payment.Status.PENDING,
                payments__created_at__gte=since,
            )
            .select_related("client")
            .distinct()
        )

        updated = 0
        for invoice in invoices:
            try:
                status = getplatinum.fetch_status(invoice)
            except getplatinum.PaymentError as exc:
                self.stderr.write(f"Счёт №{invoice.pk}: {exc}")
                continue

            if not status["is_success"]:
                continue

            from apps.billing.views import _apply_payment

            _apply_payment(
                invoice,
                {
                    "payment_id": status["payment_id"],
                    "amount": status["amount"],
                    "is_success": True,
                },
                status["raw"],
                verified_by="sync",
            )
            updated += 1
            self.stdout.write(f"Счёт №{invoice.pk} закрыт по сверке.")

        self.stdout.write(self.style.SUCCESS(f"Проверено: {len(invoices)}, закрыто: {updated}."))
