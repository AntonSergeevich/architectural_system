"""Договоры: шаблоны, пункты, расшифровки, подтверждения.

Коллеги Дарьи садятся с заказчиком и проходят маркером по каждому важному
пункту. На сайте это работает лучше: важное подсвечено, расшифровка
раскрывается кликом, непонятное отмечается галочкой — и разбирать нужно
только отмеченное, а не весь документ целиком.

Всё редактируется Дарьей: и шаблон, и текст пункта, и расшифровка.
"""

from decimal import Decimal

from django.db import models
from django.urls import reverse
from django.utils import timezone

from apps.core.utils import public_token


class ContractTemplate(models.Model):
    class Kind(models.TextChoices):
        DESIGN = "design", "Проектирование"
        SUPERVISION = "supervision", "Авторский надзор"
        PROCUREMENT = "procurement", "Комплектация"

    kind = models.CharField("Вид", max_length=16, choices=Kind.choices)
    title = models.CharField("Название", max_length=200)
    version = models.CharField("Версия", max_length=20, default="1.0")
    intro = models.TextField("Вводная часть", blank=True)
    outro = models.TextField("Заключительная часть", blank=True)
    is_active = models.BooleanField("Действующий", default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Шаблон договора"
        verbose_name_plural = "Шаблоны договоров"
        ordering = ["kind", "-version"]

    def __str__(self):
        return f"{self.title} (ред. {self.version})"


class ContractClause(models.Model):
    """Пункт договора.

    `plain_text` — то самое «на человеческом языке». Без него подсветка
    важного бессмысленна: человек увидит, что пункт важный, и всё равно
    не поймёт, о чём он.
    """

    template = models.ForeignKey(
        ContractTemplate, on_delete=models.CASCADE, related_name="clauses", verbose_name="Шаблон"
    )
    number = models.CharField("Номер", max_length=12)
    title = models.CharField("Заголовок", max_length=250, blank=True)
    text = models.TextField("Текст пункта")
    plain_text = models.TextField(
        "На человеческом языке",
        blank=True,
        help_text="Раскрывается кликом. Это и есть то, что коллеги "
        "проговаривают маркером",
    )
    is_important = models.BooleanField(
        "Важный",
        default=False,
        help_text="Подсвечивается. Именно эти пункты обычно и не читают",
    )
    order = models.PositiveSmallIntegerField("Порядок", default=100)

    class Meta:
        verbose_name = "Пункт договора"
        verbose_name_plural = "Пункты договора"
        ordering = ["order", "number"]

    def __str__(self):
        return f"{self.number} {self.title}".strip()


class Contract(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Черновик"
        SENT = "sent", "Отправлен"
        REVIEWED = "reviewed", "Прочитан"
        SIGNED = "signed", "Подписан"

    template = models.ForeignKey(
        ContractTemplate, on_delete=models.PROTECT, verbose_name="Шаблон", related_name="contracts"
    )
    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.CASCADE,
        related_name="contracts",
        verbose_name="Проект",
        null=True,
        blank=True,
    )
    client = models.ForeignKey(
        "crm.Client", on_delete=models.PROTECT, related_name="contracts", verbose_name="Заказчик"
    )
    number = models.CharField("Номер", max_length=40, blank=True)
    date = models.DateField("Дата", default=timezone.localdate)
    amount = models.DecimalField("Сумма", max_digits=12, decimal_places=2, default=Decimal("0"))
    token = models.CharField("Ссылка", max_length=32, unique=True, default=public_token)
    status = models.CharField("Статус", max_length=16, choices=Status.choices, default=Status.DRAFT)
    signed_at = models.DateTimeField("Подписан", null=True, blank=True)

    class Meta:
        verbose_name = "Договор"
        verbose_name_plural = "Договоры"
        ordering = ["-date"]

    def __str__(self):
        return f"{self.template.get_kind_display()} №{self.number or self.pk}"

    def get_absolute_url(self):
        return reverse("public:contract", args=[self.token])


class ClauseQuestion(models.Model):
    """Заказчик отметил пункт как непонятный.

    Экономит час созвона обоим: разбирается только отмеченное.
    """

    contract = models.ForeignKey(Contract, on_delete=models.CASCADE, related_name="questions")
    clause = models.ForeignKey(ContractClause, on_delete=models.CASCADE, related_name="questions")
    question = models.TextField("Вопрос", blank=True)
    answer = models.TextField("Ответ", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    answered_at = models.DateTimeField("Отвечено", null=True, blank=True)

    class Meta:
        verbose_name = "Вопрос по договору"
        verbose_name_plural = "Вопросы по договору"
        ordering = ["clause__order"]

    def __str__(self):
        return f"{self.clause} · {self.contract}"


class ContractAck(models.Model):
    """Подтверждение, что заказчик прочитал договор и регламент."""

    contract = models.OneToOneField(Contract, on_delete=models.CASCADE, related_name="ack")
    name = models.CharField("Кто подтвердил", max_length=150)
    template_version = models.CharField("Редакция шаблона", max_length=20, blank=True)
    ip = models.GenericIPAddressField("IP", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Подтверждение договора"
        verbose_name_plural = "Подтверждения договоров"

    def __str__(self):
        return f"{self.name} · {self.created_at:%d.%m.%Y}"
