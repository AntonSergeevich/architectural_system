"""Счета и платежи."""

from decimal import Decimal

from django.db import models
from django.urls import reverse
from django.utils import timezone

from apps.core.utils import public_token


class Invoice(models.Model):
    """Счёт на оплату этапа.

    Оплата идёт по этапам, а не одной суммой: проектирование, надзор
    и комплектация живут в разных договорах и в разное время.
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "Черновик"
        ISSUED = "issued", "Выставлен"
        PAID = "paid", "Оплачен"
        PARTIAL = "partial", "Оплачен частично"
        CANCELLED = "cancelled", "Отменён"

    client = models.ForeignKey(
        "crm.Client", on_delete=models.PROTECT, related_name="invoices", verbose_name="Заказчик"
    )
    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invoices",
        verbose_name="Проект",
    )
    contract = models.ForeignKey(
        "contracts.Contract",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invoices",
        verbose_name="Договор",
    )
    number = models.CharField("Номер", max_length=40, blank=True)
    title = models.CharField("За что", max_length=250)
    amount = models.DecimalField("Сумма", max_digits=12, decimal_places=2)
    status = models.CharField("Статус", max_length=16, choices=Status.choices, default=Status.DRAFT)
    token = models.CharField("Ссылка", max_length=32, unique=True, default=public_token)
    due_date = models.DateField("Оплатить до", null=True, blank=True)
    issued_at = models.DateTimeField("Выставлен", null=True, blank=True)
    paid_at = models.DateTimeField("Оплачен", null=True, blank=True)
    comment = models.TextField("Комментарий", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Счёт"
        verbose_name_plural = "Счета"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Счёт №{self.number or self.pk} · {self.title}"

    def get_absolute_url(self):
        return reverse("billing:invoice", args=[self.token])

    @property
    def paid_amount(self):
        return sum(
            (p.amount for p in self.payments.all() if p.status == Payment.Status.SUCCEEDED),
            Decimal("0"),
        )

    @property
    def left_to_pay(self):
        return max(self.amount - self.paid_amount, Decimal("0"))

    @property
    def is_payable(self):
        return self.status in {self.Status.ISSUED, self.Status.PARTIAL} and self.left_to_pay > 0

    def refresh_status(self):
        """Пересчитать статус по фактически прошедшим платежам."""
        paid = self.paid_amount
        if paid >= self.amount:
            new_status = self.Status.PAID
        elif paid > 0:
            new_status = self.Status.PARTIAL
        elif self.status in {self.Status.PAID, self.Status.PARTIAL}:
            # Оплата отменилась или вернулась — счёт снова ждёт оплаты.
            new_status = self.Status.ISSUED
        else:
            # Статус не понижаем. Неудачный платёж не должен превращать
            # выставленный счёт обратно в черновик.
            new_status = self.status

        fields = []
        if new_status != self.status:
            self.status = new_status
            fields.append("status")
        if new_status == self.Status.PAID and not self.paid_at:
            self.paid_at = timezone.now()
            fields.append("paid_at")
        if fields:
            self.save(update_fields=fields)


class Payment(models.Model):
    """Платёж.

    Хранится и то, что пришло от платёжного сервиса (`raw`): при разборе
    спорной оплаты это единственное, на что можно опереться.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Ожидает"
        SUCCEEDED = "succeeded", "Прошёл"
        FAILED = "failed", "Не прошёл"
        REFUNDED = "refunded", "Возвращён"

    class Provider(models.TextChoices):
        GETPLATINUM = "getplatinum", "GetPlatinum"
        MANUAL = "manual", "Вручную"

    invoice = models.ForeignKey(
        Invoice, on_delete=models.CASCADE, related_name="payments", verbose_name="Счёт"
    )
    provider = models.CharField(
        "Способ", max_length=20, choices=Provider.choices, default=Provider.GETPLATINUM
    )
    provider_payment_id = models.CharField("ID у провайдера", max_length=120, blank=True)
    amount = models.DecimalField("Сумма", max_digits=12, decimal_places=2)
    status = models.CharField("Статус", max_length=16, choices=Status.choices, default=Status.PENDING)
    raw = models.JSONField("Ответ провайдера", default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Платёж"
        verbose_name_plural = "Платежи"
        ordering = ["-created_at"]
        constraints = [
            # Провайдер присылает уведомление о платеже не один раз — это
            # норма, так устроены вебхуки. Задвоение гасим на уровне базы,
            # а не надеждой на то, что сеть не подведёт.
            models.UniqueConstraint(
                fields=["provider", "provider_payment_id"],
                condition=~models.Q(provider_payment_id=""),
                name="uniq_provider_payment",
            )
        ]

    def __str__(self):
        return f"{self.amount} ₽ · {self.get_status_display()}"
