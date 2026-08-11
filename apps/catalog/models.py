"""Каталог услуг — единственный источник правды о составе работ и ценах.

Из него питаются конструктор, коммерческие предложения, состав договора
и чек-листы этапов. Дублировать состав услуг где-то ещё нельзя: разъедется
ровно так же, как сейчас расходятся устные пересказы.
"""

from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models


class Unit(models.TextChoices):
    SQM = "sqm", "за м²"
    FIXED = "fixed", "фиксированно"
    STAGE = "stage", "за этап"
    MONTH = "month", "в месяц"
    VISIT = "visit", "за выезд"
    CUSTOM = "custom", "индивидуальный расчёт"


class Block(models.TextChoices):
    DESIGN = "design", "Проектирование"
    REALIZATION = "realization", "Реализация"
    EXTRA = "extra", "Разовое"


class HousePart(models.TextChoices):
    """Элемент дома в конструкторе.

    Метафора работает вместо предупреждающего текста: снятый модуль
    оставляет в доме видимую дыру. Текст можно пролистать, дыру нельзя.
    """

    FOUNDATION = "foundation", "Фундамент"
    WALLS = "walls", "Стены"
    WINDOWS = "windows", "Окна"
    FACADE = "facade", "Фасад"
    FINISH = "finish", "Отделка"
    ROOF = "roof", "Крыша"
    LIGHT = "light", "Свет в окнах"
    GARDEN = "garden", "Сад у крыльца"


class ModuleGroup(models.Model):
    """Слот, куда кладётся ровно один блок из нескольких.

    Так устроены окна (эскизы / нейро / фотореализм) и стены (полный
    комплект чертежей / частичный).
    """

    code = models.CharField("Код", max_length=32, unique=True)
    title = models.CharField("Название", max_length=150)
    house_part = models.CharField(
        "Элемент дома", max_length=16, choices=HousePart.choices, blank=True
    )
    order = models.PositiveSmallIntegerField("Порядок", default=100)

    class Meta:
        verbose_name = "Группа выбора"
        verbose_name_plural = "Группы выбора"
        ordering = ["order"]

    def __str__(self):
        return self.title


class ServiceModule(models.Model):
    """Модуль услуги: строка каталога с ценой и единицей измерения."""

    code = models.CharField("Код", max_length=16, unique=True)
    title = models.CharField("Название", max_length=200)
    short_title = models.CharField("Коротко (для блока)", max_length=60, blank=True)
    block = models.CharField("Блок", max_length=16, choices=Block.choices, default=Block.DESIGN)
    group = models.ForeignKey(
        ModuleGroup,
        verbose_name="Группа выбора",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="modules",
    )
    house_part = models.CharField(
        "Элемент дома", max_length=16, choices=HousePart.choices, blank=True
    )

    unit = models.CharField("Единица", max_length=10, choices=Unit.choices, default=Unit.SQM)
    price = models.DecimalField(
        "Цена",
        max_digits=10,
        decimal_places=2,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
        help_text="Для «за м²» — цена одного квадратного метра",
    )

    is_required = models.BooleanField(
        "Обязательный",
        default=False,
        help_text="Входит всегда, снять в конструкторе нельзя",
    )
    is_active = models.BooleanField(
        "Показывать на сайте",
        default=True,
        help_text="Снимите галочку, если услуга ещё не отработана "
        "и обещать её рано",
    )
    affected_by_complexity = models.BooleanField(
        "Зависит от сложности",
        default=True,
        help_text="Умножается на коэффициент характера интерьера",
    )

    description = models.TextField("Что входит", blank=True)
    outcome = models.CharField("Что на выходе", max_length=300, blank=True)
    duration_days = models.PositiveSmallIntegerField("Рабочих дней", default=0)
    not_included = models.TextField("Что не входит", blank=True)
    warning = models.TextField(
        "Что вы берёте на себя",
        blank=True,
        help_text="Показывается, когда модуль снят. Не запугивание, а факт",
    )

    order = models.PositiveSmallIntegerField("Порядок", default=100)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Модуль услуги"
        verbose_name_plural = "Каталог услуг"
        ordering = ["block", "order", "code"]

    def __str__(self):
        return f"{self.code}. {self.title}"

    @property
    def label(self):
        return self.short_title or self.title

    @property
    def is_custom(self):
        return self.unit == Unit.CUSTOM

    def amount_for(self, area, complexity=Decimal("1"), quantity=1):
        """Стоимость модуля для конкретного объекта.

        Возвращает None для модулей с индивидуальным расчётом: показать
        выдуманное число хуже, чем честно позвать на разговор.
        """
        if self.unit == Unit.CUSTOM:
            return None
        if self.unit == Unit.SQM:
            base = self.price * Decimal(area or 0)
        else:
            base = self.price * Decimal(quantity or 1)
        if self.affected_by_complexity:
            base *= Decimal(complexity)
        return base.quantize(Decimal("1"))


class PriceHistory(models.Model):
    """История цен.

    Нужна ровно для одного: понять через год, почему в старом КП стояла
    другая цифра. Пишется автоматически при изменении цены модуля.
    """

    module = models.ForeignKey(
        ServiceModule, on_delete=models.CASCADE, related_name="price_history", verbose_name="Модуль"
    )
    price = models.DecimalField("Цена", max_digits=10, decimal_places=2)
    unit = models.CharField("Единица", max_length=10, choices=Unit.choices)
    changed_at = models.DateTimeField("Когда", auto_now_add=True)
    comment = models.CharField("Комментарий", max_length=200, blank=True)

    class Meta:
        verbose_name = "Изменение цены"
        verbose_name_plural = "История цен"
        ordering = ["-changed_at"]

    def __str__(self):
        return f"{self.module.code} → {self.price} ({self.changed_at:%d.%m.%Y})"


class ComplexityFactor(models.Model):
    """Характер интерьера → коэффициент.

    Две квартиры по 100 м² требуют разного времени, и зависит это не от
    площади: в лаконичном решении многое уже готово в голове, авторский
    интерьер каждый раз разрабатывается заново.
    """

    code = models.SlugField("Код", max_length=32, unique=True)
    title = models.CharField("Название", max_length=150)
    description = models.CharField("Пояснение", max_length=300, blank=True)
    factor = models.DecimalField("Коэффициент", max_digits=4, decimal_places=2, default=Decimal("1.00"))
    is_default = models.BooleanField("По умолчанию", default=False)
    order = models.PositiveSmallIntegerField("Порядок", default=100)

    class Meta:
        verbose_name = "Характер интерьера"
        verbose_name_plural = "Характер интерьера"
        ordering = ["order"]

    def __str__(self):
        return f"{self.title} (×{self.factor})"


class Preset(models.Model):
    """Пресет — заранее отмеченный набор модулей, а не отдельная сущность.

    Клиент может начать с пресета и снять любой блок; обратное тоже верно.
    """

    code = models.SlugField("Код", max_length=32, unique=True)
    title = models.CharField("Название", max_length=150)
    tagline = models.CharField("Одной строкой", max_length=250, blank=True)
    description = models.TextField("Кому подходит", blank=True)
    modules = models.ManyToManyField(
        ServiceModule, verbose_name="Состав", blank=True, related_name="presets"
    )
    is_default = models.BooleanField(
        "Выбран по умолчанию",
        default=False,
        help_text="Стартовое состояние конструктора. Клиент не собирает "
        "с нуля, а разбирает готовый дом",
    )
    is_active = models.BooleanField("Показывать", default=True)
    order = models.PositiveSmallIntegerField("Порядок", default=100)

    class Meta:
        verbose_name = "Пресет"
        verbose_name_plural = "Пресеты"
        ordering = ["order"]

    def __str__(self):
        return self.title
