"""Настройки сайта, юридические документы, согласия, портфолио, контент."""

from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify


class SiteSettings(models.Model):
    """Единственная строка с настройками. Правится Дарьей в кабинете."""

    owner_name = models.CharField("Имя", max_length=120, default="Дарья")
    owner_title = models.CharField(
        "Кто вы", max_length=200, default="архитектор, дизайнер интерьера"
    )
    owner_photo = models.ImageField("Фото", upload_to="site/", blank=True)
    owner_about = models.TextField("Текст о себе", blank=True)

    phone = models.CharField("Телефон", max_length=32, default="+7 (913) 032-29-08")
    email = models.EmailField("Email", blank=True)
    telegram = models.CharField("Telegram", max_length=64, blank=True)
    whatsapp = models.CharField("WhatsApp", max_length=64, blank=True)
    city = models.CharField("Город", max_length=80, default="Красноярск")

    legal_name = models.CharField(
        "Юридическое имя", max_length=200, default="Самозанятый"
    )
    inn = models.CharField("ИНН", max_length=12, default="246315111806")

    # --- Регламент. Публикуется дословно и подтверждается в договоре. ------
    workday_start = models.PositiveSmallIntegerField("Начало рабочего дня", default=10)
    workday_end = models.PositiveSmallIntegerField("Конец рабочего дня", default=19)
    reply_hours = models.PositiveSmallIntegerField(
        "Срок ответа, рабочих часов",
        default=24,
        help_text="Считается в рабочем времени, а не в календарном",
    )
    regulations = models.TextField(
        "Регламент",
        blank=True,
        help_text="Публикуется дословно на сайте и в договоре",
    )

    # --- Загрузка ----------------------------------------------------------
    wip_limit = models.PositiveSmallIntegerField(
        "Проектов одновременно",
        default=3,
        help_text="Сверх этого числа новые проекты встают в очередь. "
        "Именно этот предел защищает от выгорания",
    )

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Настройки сайта"
        verbose_name_plural = "Настройки сайта"

    def __str__(self):
        return "Настройки сайта"

    def save(self, *args, **kwargs):
        # Строка настроек всегда одна: вторая приводит к тому, что часть
        # сайта читает одну, часть — другую, и найти это потом тяжело.
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    @property
    def workdays(self):
        return (0, 1, 2, 3, 4)


class LegalDocument(models.Model):
    """Политика, согласие на обработку, оферта, правила куки.

    Тексты редактируются, у каждого своя версия и дата. Версия важна:
    согласие клиента фиксируется вместе с версией документа, который он
    в тот момент видел, иначе оно ничего не доказывает.
    """

    class Kind(models.TextChoices):
        PRIVACY = "privacy", "Политика конфиденциальности"
        CONSENT = "consent", "Согласие на обработку персональных данных"
        OFFER = "offer", "Публичная оферта"
        COOKIES = "cookies", "Политика в отношении файлов cookie"
        TERMS = "terms", "Пользовательское соглашение"

    kind = models.CharField("Вид", max_length=16, choices=Kind.choices, unique=True)
    title = models.CharField("Заголовок", max_length=200)
    body = models.TextField("Текст", help_text="Markdown-подобная разметка: ## заголовок, - список")
    version = models.CharField("Версия", max_length=20, default="1.0")
    published_at = models.DateField("Дата редакции", default=timezone.localdate)
    is_published = models.BooleanField("Опубликован", default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Юридический документ"
        verbose_name_plural = "Юридические документы"
        ordering = ["kind"]

    def __str__(self):
        return f"{self.title} (ред. {self.version})"

    def get_absolute_url(self):
        return reverse("public:legal", args=[self.kind])


class CookieConsent(models.Model):
    """Журнал согласий на куки.

    Хранится не для красоты: закон требует доказуемости согласия, а доказать
    можно только то, что записано — что именно человек выбрал, когда и какую
    редакцию документа при этом видел.
    """

    class Choice(models.TextChoices):
        ALL = "all", "Все"
        NECESSARY = "necessary", "Только необходимые"

    session_key = models.CharField("Сессия", max_length=64, db_index=True)
    choice = models.CharField("Выбор", max_length=16, choices=Choice.choices)
    analytics = models.BooleanField("Аналитика", default=False)
    policy_version = models.CharField("Редакция политики", max_length=20, blank=True)
    user_agent = models.CharField("Браузер", max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Согласие на куки"
        verbose_name_plural = "Согласия на куки"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_choice_display()} · {self.created_at:%d.%m.%Y}"


class PersonalDataConsent(models.Model):
    """Согласие на обработку персональных данных — при отправке любой формы.

    Отдельно от куки: это разные согласия с разными основаниями, и смешивать
    их в одну галочку нельзя.
    """

    name = models.CharField("Имя", max_length=150, blank=True)
    contact = models.CharField("Контакт", max_length=150, blank=True)
    document_version = models.CharField("Редакция документа", max_length=20, blank=True)
    source = models.CharField("Откуда", max_length=100, blank=True)
    ip = models.GenericIPAddressField("IP", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Согласие на обработку ПД"
        verbose_name_plural = "Согласия на обработку ПД"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name or self.contact} · {self.created_at:%d.%m.%Y %H:%M}"


class PortfolioProject(models.Model):
    """Объект в портфолио."""

    title = models.CharField("Название", max_length=200)
    slug = models.SlugField("Адрес", max_length=200, unique=True, blank=True)
    city = models.CharField("Город", max_length=80, blank=True)
    year = models.PositiveSmallIntegerField("Год", null=True, blank=True)
    area = models.DecimalField("Площадь, м²", max_digits=7, decimal_places=1, null=True, blank=True)
    style = models.CharField("Стиль", max_length=120, blank=True)

    summary = models.CharField("Коротко", max_length=300, blank=True)
    task = models.TextField("Задача", blank=True)
    solution = models.TextField("Решение", blank=True)
    result = models.TextField("Результат", blank=True)

    modules = models.ManyToManyField(
        "catalog.ServiceModule",
        verbose_name="Что было сделано",
        blank=True,
        related_name="portfolio_projects",
        help_text="Состав работ по объекту. Показывает разницу между "
        "«под ключ» и «только чертежи» лучше любого текста",
    )

    client_name = models.CharField("Имя заказчика", max_length=150, blank=True)
    client_quote = models.TextField("Слова заказчика", blank=True)
    client_photo = models.ImageField("Фото заказчика", upload_to="portfolio/clients/", blank=True)
    client_consent = models.BooleanField(
        "Заказчик разрешил публикацию",
        default=False,
        help_text="Без галочки имя, фото и слова заказчика на сайт не выводятся",
    )

    is_published = models.BooleanField("Опубликован", default=False)
    is_featured = models.BooleanField("На главную", default=False)
    order = models.PositiveSmallIntegerField("Порядок", default=100)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Объект портфолио"
        verbose_name_plural = "Портфолио"
        ordering = ["order", "-year", "-created_at"]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.title, allow_unicode=False) or "obekt"
            slug, n = base, 2
            while PortfolioProject.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug, n = f"{base}-{n}", n + 1
            self.slug = slug
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("public:portfolio_detail", args=[self.slug])

    @property
    def show_client(self):
        return self.client_consent and (self.client_name or self.client_quote)

    @property
    def cover(self):
        return self.photos.first()


class PortfolioPhoto(models.Model):
    project = models.ForeignKey(
        PortfolioProject, on_delete=models.CASCADE, related_name="photos", verbose_name="Объект"
    )
    image = models.ImageField("Фото", upload_to="portfolio/")
    caption = models.CharField("Подпись", max_length=200, blank=True)
    is_before = models.BooleanField("Кадр «до»", default=False)
    order = models.PositiveSmallIntegerField("Порядок", default=100)

    class Meta:
        verbose_name = "Фотография"
        verbose_name_plural = "Фотографии"
        ordering = ["order", "id"]

    def __str__(self):
        return self.caption or f"Фото #{self.pk}"


class Objection(models.Model):
    """Возражение и ответ на него.

    Это главный текст сайта: здесь Дарья один раз говорит то, что сейчас
    повторяет голосом на каждом первом созвоне.
    """

    question = models.CharField("Вопрос", max_length=300)
    answer = models.TextField("Ответ")
    is_published = models.BooleanField("Опубликован", default=True)
    order = models.PositiveSmallIntegerField("Порядок", default=100)

    class Meta:
        verbose_name = "Вопрос и возражение"
        verbose_name_plural = "Вопросы и возражения"
        ordering = ["order", "id"]

    def __str__(self):
        return self.question


class Article(models.Model):
    """Материал для тех, у кого ремонт не завтра."""

    title = models.CharField("Заголовок", max_length=250)
    slug = models.SlugField("Адрес", max_length=250, unique=True)
    lead = models.CharField("Анонс", max_length=400, blank=True)
    body = models.TextField("Текст")
    is_published = models.BooleanField("Опубликован", default=False)
    published_at = models.DateField("Дата", default=timezone.localdate)

    class Meta:
        verbose_name = "Материал"
        verbose_name_plural = "Полезное"
        ordering = ["-published_at"]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("public:article", args=[self.slug])


class StageNorm(models.Model):
    """Нормативная длительность этапа проектирования.

    Из них складывается ответ на «сколько это займёт»: не дата въезда,
    а длительность этапов плюс отдельно показанное время на согласования
    заказчика.
    """

    number = models.PositiveSmallIntegerField("Номер этапа", unique=True)
    title = models.CharField("Этап", max_length=200)
    description = models.TextField("Что происходит", blank=True)
    what_client_does = models.CharField("Что делает заказчик", max_length=300, blank=True)
    working_days = models.PositiveSmallIntegerField("Рабочих дней", default=5)
    client_days = models.PositiveSmallIntegerField("Дней на согласование", default=2)

    class Meta:
        verbose_name = "Этап работы"
        verbose_name_plural = "Этапы работы"
        ordering = ["number"]

    def __str__(self):
        return f"{self.number}. {self.title}"

    def clean(self):
        if self.working_days == 0 and self.client_days == 0:
            raise ValidationError("Этап не может занимать ноль дней целиком")
