"""Заказчики, объекты, заявки и коммерческие предложения."""

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone

from apps.core.utils import normalize_phone, public_token


class Client(models.Model):
    name = models.CharField("Имя", max_length=150)
    phone = models.CharField("Телефон", max_length=20, blank=True)
    email = models.EmailField("Email", blank=True)
    messenger = models.CharField("Мессенджер", max_length=100, blank=True)
    source = models.CharField(
        "Откуда пришёл",
        max_length=120,
        blank=True,
        help_text="Сарафан, сайт, соцсети. Основной канал — сарафан, "
        "и его надо считать, а не заменять",
    )
    referred_by = models.ForeignKey(
        "self",
        verbose_name="Кто порекомендовал",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="referrals",
    )
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        verbose_name="Аккаунт",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="client",
    )
    notes = models.TextField("Заметки", blank=True, help_text="Видит только Дарья")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Заказчик"
        verbose_name_plural = "Заказчики"
        ordering = ["-created_at"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.phone = normalize_phone(self.phone)
        super().save(*args, **kwargs)


class Property(models.Model):
    class Kind(models.TextChoices):
        NEW = "new", "Новостройка"
        SECONDARY = "secondary", "Вторичка"
        HOUSE = "house", "Дом"
        COMMERCIAL = "commercial", "Коммерческое помещение"

    client = models.ForeignKey(
        Client, on_delete=models.CASCADE, related_name="properties", verbose_name="Заказчик"
    )
    city = models.CharField("Город", max_length=80, default="Красноярск")
    address = models.CharField("Адрес", max_length=250, blank=True)
    kind = models.CharField("Тип", max_length=16, choices=Kind.choices, default=Kind.NEW)
    area = models.DecimalField("Площадь по документам, м²", max_digits=7, decimal_places=1, default=Decimal("0"))
    measured_area = models.DecimalField(
        "Площадь по обмеру, м²",
        max_digits=7,
        decimal_places=1,
        null=True,
        blank=True,
        help_text="Расхождение с БТИ до 3–4 м² — норма. По ней идёт перерасчёт",
    )
    rooms = models.PositiveSmallIntegerField("Помещений", default=1)
    keys_received = models.BooleanField("Ключи получены", default=False)
    has_builders = models.BooleanField("Свои строители", default=False)
    desired_move_in = models.CharField("Когда хотят заехать", max_length=100, blank=True)

    class Meta:
        verbose_name = "Объект"
        verbose_name_plural = "Объекты"

    def __str__(self):
        return f"{self.address or self.get_kind_display()}, {self.area} м²"

    @property
    def billable_area(self):
        """Площадь, по которой считаем. После обмера — фактическая."""
        return self.measured_area or self.area


class Lead(models.Model):
    """Заявка.

    Ключевое поле — `next_action_at`. Заявка без даты следующего шага и есть
    «потерянная заявка»; система такого состояния не допускает.
    """

    class Status(models.TextChoices):
        NEW = "new", "Новая"
        QUALIFIED = "qualified", "Квалифицирована"
        CALL = "call", "Созвон назначен"
        QUOTE_SENT = "quote_sent", "КП отправлено"
        CONTRACT = "contract", "Договор"
        WON = "won", "В работе"
        LOST = "lost", "Отказ"

    client = models.ForeignKey(
        Client, on_delete=models.CASCADE, related_name="leads", verbose_name="Заказчик"
    )
    # Не `property`: это имя занято встроенным декоратором, а он нужен
    # прямо здесь, в этом же классе.
    estate = models.ForeignKey(
        Property,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="leads",
        verbose_name="Объект",
    )
    status = models.CharField("Статус", max_length=16, choices=Status.choices, default=Status.NEW)
    source = models.CharField("Источник", max_length=120, blank=True)
    message = models.TextField("Сообщение", blank=True)

    # Ответы квалификационной анкеты: набор вопросов меняется, заводить под
    # каждый по колонке — значит мигрировать базу ради текста на сайте.
    answers = models.JSONField("Анкета", default=dict, blank=True)

    next_action = models.CharField("Следующий шаг", max_length=200, default="Связаться")
    next_action_at = models.DateTimeField("Когда", default=timezone.now)
    last_touch_at = models.DateTimeField("Последнее касание", null=True, blank=True)
    lost_reason = models.CharField("Причина отказа", max_length=250, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Заявка"
        verbose_name_plural = "Заявки"
        ordering = ["next_action_at"]
        indexes = [models.Index(fields=["status", "next_action_at"])]

    def __str__(self):
        return f"{self.client.name} · {self.get_status_display()}"

    @property
    def is_overdue(self):
        return self.status not in {self.Status.WON, self.Status.LOST} and (
            self.next_action_at < timezone.now()
        )


class Quote(models.Model):
    """Коммерческое предложение — то, что открывается по ссылке.

    Не PDF. Одна ссылка, всё внутри, открывается на телефоне и всегда
    актуальна: разные предложения в разных файлах теряются и забываются.
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "Черновик"
        SENT = "sent", "Отправлено"
        OPENED = "opened", "Открыто"
        ACCEPTED = "accepted", "Принято"
        EXPIRED = "expired", "Просрочено"

    client = models.ForeignKey(
        Client, on_delete=models.CASCADE, related_name="quotes", verbose_name="Заказчик", null=True, blank=True
    )
    lead = models.ForeignKey(
        Lead, on_delete=models.SET_NULL, null=True, blank=True, related_name="quotes", verbose_name="Заявка"
    )
    token = models.CharField("Ссылка", max_length=32, unique=True, default=public_token)

    area = models.DecimalField("Площадь, м²", max_digits=7, decimal_places=1, default=Decimal("0"))
    rooms = models.PositiveSmallIntegerField("Помещений", default=1)
    complexity = models.ForeignKey(
        "catalog.ComplexityFactor",
        verbose_name="Характер интерьера",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    preset = models.ForeignKey(
        "catalog.Preset",
        verbose_name="Пресет",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    supervision_months = models.PositiveSmallIntegerField("Месяцев надзора", default=6)
    procurement_stages = models.PositiveSmallIntegerField("Этапов комплектации", default=3)

    design_total = models.DecimalField("Проектирование", max_digits=12, decimal_places=2, default=Decimal("0"))
    realization_total = models.DecimalField("Реализация", max_digits=12, decimal_places=2, default=Decimal("0"))
    extra_total = models.DecimalField("Разовое", max_digits=12, decimal_places=2, default=Decimal("0"))

    status = models.CharField("Статус", max_length=16, choices=Status.choices, default=Status.DRAFT)
    valid_until = models.DateField("Действует до", null=True, blank=True)
    comment = models.TextField("Комментарий Дарьи", blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField("Отправлено", null=True, blank=True)
    opened_at = models.DateTimeField("Впервые открыто", null=True, blank=True)

    class Meta:
        verbose_name = "Коммерческое предложение"
        verbose_name_plural = "Коммерческие предложения"
        ordering = ["-created_at"]

    def __str__(self):
        who = self.client.name if self.client else "без заказчика"
        return f"КП №{self.pk} · {who}"

    def get_absolute_url(self):
        return reverse("public:quote", args=[self.token])

    @property
    def is_expired(self):
        return bool(self.valid_until and self.valid_until < timezone.localdate())

    def mark_opened(self):
        """Первое открытие — сигнал позвонить, а не просто метка."""
        if self.opened_at:
            return False
        self.opened_at = timezone.now()
        if self.status == self.Status.SENT:
            self.status = self.Status.OPENED
        self.save(update_fields=["opened_at", "status"])
        return True


class QuoteItem(models.Model):
    """Позиция КП.

    Цена копируется сюда в момент выставления: изменение прайса не должно
    задним числом менять то, что клиент уже видел.
    """

    quote = models.ForeignKey(Quote, on_delete=models.CASCADE, related_name="items")
    module = models.ForeignKey(
        "catalog.ServiceModule", on_delete=models.PROTECT, verbose_name="Модуль"
    )
    title = models.CharField("Название", max_length=200)
    unit = models.CharField("Единица", max_length=10)
    unit_price = models.DecimalField("Цена за единицу", max_digits=10, decimal_places=2)
    quantity = models.DecimalField("Количество", max_digits=10, decimal_places=2, default=Decimal("1"))
    amount = models.DecimalField(
        "Сумма", max_digits=12, decimal_places=2, null=True, blank=True,
        help_text="Пусто — индивидуальный расчёт",
    )

    class Meta:
        verbose_name = "Позиция КП"
        verbose_name_plural = "Позиции КП"
        ordering = ["module__block", "module__order"]

    def __str__(self):
        return self.title
