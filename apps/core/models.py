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

    # Два текста, а не один: на главной нужен короткий, на странице
    # «Обо мне» — подробный. Раньше подробный дописывался к зашитому
    # в шаблон абзацу, и правка в админке не заменяла текст, а удлиняла
    # его. Теперь в шаблонах нет ни одного слова о Дарье: всё, что
    # написано на сайте о ней, правится отсюда.
    owner_intro = models.TextField(
        "Коротко о себе (главная)",
        blank=True,
        help_text="Два-три предложения в блоке «Обо мне» на главной странице",
    )
    owner_about = models.TextField(
        "Текст о себе (страница «Обо мне»)",
        blank=True,
        help_text="Полный рассказ. Заменяет текст на странице целиком",
    )
    owner_intro_title = models.CharField(
        "Заголовок блока на главной", max_length=120, blank=True, default="Я не робот"
    )

    phone = models.CharField("Телефон", max_length=32, default="+7 (913) 032-29-08")
    email = models.EmailField("Email", blank=True, default="dark-ost@ya.ru")
    telegram = models.CharField("Telegram", max_length=64, blank=True)
    whatsapp = models.CharField("WhatsApp", max_length=64, blank=True)
    city = models.CharField("Город", max_length=80, default="Красноярск")

    # --- Соцсети -----------------------------------------------------------
    # Интерьер смотрят глазами, и половина заказчиков приходит из ленты,
    # а не с сайта. Ссылка на Instagram публикуется с обязательной
    # пометкой: Meta признана в России экстремистской организацией,
    # и упоминание без пометки — нарушение.
    instagram = models.URLField("Instagram", blank=True)
    vk = models.URLField("ВКонтакте", blank=True)
    pinterest = models.URLField("Pinterest", blank=True)
    dzen = models.URLField("Дзен", blank=True)

    legal_name = models.CharField(
        "Юридическое имя", max_length=200, default="Самозанятый"
    )
    inn = models.CharField("ИНН", max_length=12, default="246315111806")

    # Как оплатить, когда карт на сайте нет. Эквайринг берёт процент
    # с каждого счёта, и Дарья решила его не платить: счетов единицы,
    # а перевод по номеру телефона занимает у заказчика столько же
    # времени, сколько ввод карты. Но «онлайн-оплата недоступна» без
    # продолжения — это тупик: человек уже собрался платить и остаётся
    # ни с чем. Поэтому здесь лежит то, что он увидит вместо кнопки.
    payment_note = models.TextField(
        "Как оплатить переводом",
        blank=True,
        help_text="Показывается на счёте вместо кнопки оплаты картой: "
        "номер для перевода по СБП, банк, назначение платежа",
    )

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

    # Две даты, а не одна. Проект и стройка разнесены во времени сильно:
    # альбом сдан в январе, интерьер снят через два года — и это не изъян,
    # а норма отрасли, которую заказчик обычно не знает. Написанные рядом,
    # они честно объясняют, почему «свежих» объектов у любого дизайнера
    # мало. Текстом, а не датой: «зима 2023» — законный ответ, а требовать
    # выбрать день ради подписи «январь 2023» незачем.
    designed_on = models.CharField(
        "Проект", max_length=60, blank=True, help_text="Как в подписи: «январь 2023»"
    )
    built_on = models.CharField(
        "Реализация", max_length=60, blank=True, help_text="Когда объект сдан: «март 2025»"
    )

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

    # Видеоотзыв снять труднее, чем взять текстом, но стоит он несопоставимо
    # больше: живой голос заказчика в кадре закрывает вопрос «а это точно
    # не выдумано» целиком.
    client_video = models.FileField(
        "Видеоотзыв",
        upload_to="portfolio/video/",
        blank=True,
        help_text="Файл MP4. Показывается только при согласии заказчика",
    )
    client_consent = models.BooleanField(
        "Заказчик разрешил публикацию",
        default=False,
        help_text="Без галочки имя, фото, видео и слова заказчика на сайт не выводятся",
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
        return self.client_consent and (self.client_name or self.client_quote or self.client_video)

    @property
    def cover(self):
        """Главный кадр объекта.

        Первым по порядку почти никогда не оказывается тот, которым объект
        стоит показывать: порядок задаётся под рассказ, а обложка — под
        первый взгляд. Поэтому обложка отмечается галочкой, и только если
        её нет, берётся первый кадр.
        """
        photos = list(self.photos.all())
        for photo in photos:
            if photo.is_cover:
                return photo
        return photos[0] if photos else None

    @property
    def gallery(self):
        """Кадры мозаики: обложка первой, остальные в своём порядке."""
        photos = list(self.photos.all())
        cover = self.cover
        return ([cover] if cover else []) + [p for p in photos if p != cover]


class PortfolioPhoto(models.Model):
    project = models.ForeignKey(
        PortfolioProject, on_delete=models.CASCADE, related_name="photos", verbose_name="Объект"
    )
    image = models.ImageField("Фото", upload_to="portfolio/")
    caption = models.CharField("Подпись", max_length=200, blank=True)
    is_before = models.BooleanField("Кадр «до»", default=False)
    is_cover = models.BooleanField(
        "Главное фото", default=False, help_text="Показывается в списке работ и первым на странице"
    )
    # Мозаика не должна резать панорамы до квадрата: широкий кадр занимает
    # два столбца и остаётся собой.
    is_wide = models.BooleanField(
        "Широкий кадр", default=False, help_text="Занимает в мозаике двойную ширину"
    )
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


class PressMention(models.Model):
    """Публикация о Дарье или её объектах.

    Чужой голос убеждает не так, как свой: «журнал написал» и «я о себе
    написала» — разные утверждения. Раздел живёт отдельно от отзывов
    именно поэтому, а не ради красоты.
    """

    outlet = models.CharField("Издание", max_length=150)
    issue = models.CharField(
        "Номер", max_length=80, blank=True, help_text="Как на обложке: «№273, август 2026»"
    )
    title = models.CharField("Заголовок публикации", max_length=250)
    url = models.URLField("Ссылка", blank=True)
    date = models.DateField("Дата", default=timezone.localdate)
    quote = models.TextField("Цитата", blank=True, help_text="Фрагмент, который стоит показать")
    logo = models.ImageField("Логотип издания", upload_to="press/", blank=True)
    # Обложка — главное здесь. Логотип издания говорит «нас упоминали»,
    # а обложка бумажного номера говорит «я это держала в руках»: это
    # разные по силе утверждения, и второе не подделаешь.
    cover = models.ImageField("Обложка номера", upload_to="press/", blank=True)
    spread = models.ImageField(
        "Разворот со статьёй",
        upload_to="press/",
        blank=True,
        help_text="Скан или снимок страницы: видно, что публикация настоящая",
    )
    file = models.FileField(
        "PDF статьи или номера",
        upload_to="press/pdf/",
        blank=True,
        help_text="Чтобы можно было прочитать целиком, не выходя с сайта",
    )
    is_published = models.BooleanField("Опубликовано", default=True)
    order = models.PositiveSmallIntegerField("Порядок", default=100)

    class Meta:
        verbose_name = "Публикация в прессе"
        verbose_name_plural = "Пресса"
        ordering = ["order", "-date"]

    def __str__(self):
        return f"{self.outlet}: {self.title}"

    def get_absolute_url(self):
        return reverse("public:publications")

    @property
    def read_url(self):
        """Куда ведёт «читать»: сначала свой файл, потом чужой сайт.

        Свой PDF надёжнее ссылки: издания переезжают, меняют адреса
        и закрывают архивы, а публикация должна пережить это.
        """
        if self.file:
            return self.file.url
        return self.url or ""


# --- Три блока работы -------------------------------------------------------
# Восемь этапов — это подробно, но неохватно: заказчик видит восемь шагов,
# считает их равными и после третьего решает, что мы стоим. Поэтому этапы
# собраны в три блока, и доли стоят на блоках, а не на этапах: 30, 40 и 30 —
# ровно так же, как в договоре разложены деньги.
#
# Доля отдельного этапа всегда усреднённая: подбор материалов бывает
# и на десять дней, и на месяц. Написанная где-либо, она превращается
# в обещание, которого никто не давал.
#
# Список лежит здесь, а не в кабинете: это норматив процесса, одинаковый
# для публичной страницы «Как я работаю» и для шкалы в кабинете. Две копии
# однажды разъедутся, и стороны увидят разное.
STAGE_BLOCKS = (
    ("Обмер, бриф, планировки", 30, (1, 2, 3)),
    ("Образ и материалы", 40, (4, 5, 6)),
    ("Чертежи и сдача", 30, (7, 8)),
)


def group_by_block(stages):
    """Разложить этапы по блокам.

    Этап с незнакомым номером попадает в последний блок, а не выпадает:
    на шкале скобки стоят над точками, и потерянный этап сдвинул бы всё.
    """
    rows = [
        {"title": title, "share": share, "numbers": numbers, "stages": []}
        for title, share, numbers in STAGE_BLOCKS
    ]
    for stage in stages:
        row = next((r for r in rows if stage.number in r["numbers"]), rows[-1])
        row["stages"].append(stage)
    return [row for row in rows if row["stages"]]


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
