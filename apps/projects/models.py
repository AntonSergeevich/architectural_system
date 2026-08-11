"""Проекты, этапы, правки, согласования, выезды и комплектация."""

from decimal import Decimal

from django.db import models
from django.utils import timezone


class Project(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued", "В очереди"
        ACTIVE = "active", "В работе"
        PAUSED = "paused", "Пауза"
        DONE = "done", "Завершён"

    client = models.ForeignKey(
        "crm.Client", on_delete=models.PROTECT, related_name="projects", verbose_name="Заказчик"
    )
    estate = models.ForeignKey(
        "crm.Property", on_delete=models.PROTECT, related_name="projects", verbose_name="Объект"
    )
    quote = models.ForeignKey(
        "crm.Quote", on_delete=models.SET_NULL, null=True, blank=True, verbose_name="КП"
    )
    title = models.CharField("Название", max_length=200, blank=True)
    modules = models.ManyToManyField(
        "catalog.ServiceModule", verbose_name="Состав работ", blank=True, related_name="projects"
    )

    status = models.CharField("Статус", max_length=16, choices=Status.choices, default=Status.QUEUED)
    starts_at = models.DateField(
        "Дата старта",
        null=True,
        blank=True,
        help_text="Обещаем дату старта и длительность этапов, а не дату въезда: "
        "второе зависит от бригады и поставок",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateField("Завершён", null=True, blank=True)

    class Meta:
        verbose_name = "Проект"
        verbose_name_plural = "Проекты"
        ordering = ["-created_at"]

    def __str__(self):
        return self.title or f"{self.client.name} · {self.estate}"

    @property
    def current_stage(self):
        return self.stages.exclude(status=Stage.Status.DONE).order_by("number").first()

    @property
    def progress(self):
        total = self.stages.count()
        if not total:
            return 0
        done = self.stages.filter(status=Stage.Status.DONE).count()
        return int(done * 100 / total)


class Stage(models.Model):
    class Status(models.TextChoices):
        WAITING = "waiting", "Не начат"
        IN_PROGRESS = "in_progress", "В работе"
        REVIEW = "review", "На согласовании"
        DONE = "done", "Утверждён"

    class WaitingOn(models.TextChoices):
        NOBODY = "", "—"
        OWNER = "owner", "Дарья"
        CLIENT = "client", "Заказчик"

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="stages")
    number = models.PositiveSmallIntegerField("Номер")
    title = models.CharField("Этап", max_length=200)
    status = models.CharField("Статус", max_length=16, choices=Status.choices, default=Status.WAITING)

    # Разделяет «я не успела» и «жду ответа заказчика». Из этого поля
    # собирается честная строка «ваши согласования: NN дней».
    waiting_on = models.CharField(
        "Кого ждём", max_length=8, choices=WaitingOn.choices, blank=True, default=""
    )

    planned_days = models.PositiveSmallIntegerField("План, рабочих дней", default=5)
    started_at = models.DateField("Начат", null=True, blank=True)
    finished_at = models.DateField("Завершён", null=True, blank=True)
    client_wait_days = models.PositiveSmallIntegerField("Дней ждали заказчика", default=0)
    note = models.TextField("Заметка", blank=True, help_text="Видит только Дарья")

    class Meta:
        verbose_name = "Этап проекта"
        verbose_name_plural = "Этапы проекта"
        ordering = ["project", "number"]
        constraints = [
            models.UniqueConstraint(fields=["project", "number"], name="uniq_stage_number")
        ]

    def __str__(self):
        return f"{self.number}. {self.title}"


class StageFile(models.Model):
    stage = models.ForeignKey(Stage, on_delete=models.CASCADE, related_name="files")
    file = models.FileField("Файл", upload_to="projects/%Y/%m/")
    title = models.CharField("Название", max_length=200, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Файл этапа"
        verbose_name_plural = "Файлы этапа"
        ordering = ["-uploaded_at"]

    def __str__(self):
        return self.title or self.file.name


class Approval(models.Model):
    """Согласование этапа заказчиком.

    Зафиксированное действие с датой — то, чего сейчас нет и из-за чего
    правки, обсуждённые голосом, юридически не существуют.
    """

    stage = models.OneToOneField(Stage, on_delete=models.CASCADE, related_name="approval")
    approved_at = models.DateTimeField("Когда", default=timezone.now)
    approved_by = models.CharField("Кто", max_length=150, blank=True)
    comment = models.TextField("Комментарий", blank=True)

    class Meta:
        verbose_name = "Согласование"
        verbose_name_plural = "Согласования"

    def __str__(self):
        return f"{self.stage} · {self.approved_at:%d.%m.%Y}"


class Revision(models.Model):
    """Правка.

    Живёт в системе, а не в мессенджере. Тогда её не нужно переписывать
    второй раз ради договора, и она видна обоим со статусом.
    """

    class Status(models.TextChoices):
        NEW = "new", "Новая"
        ACCEPTED = "accepted", "В работе"
        DONE = "done", "Выполнена"
        DECLINED = "declined", "Отклонена"

    stage = models.ForeignKey(Stage, on_delete=models.CASCADE, related_name="revisions")
    room = models.CharField("Помещение", max_length=120, blank=True)
    text = models.TextField("Что поменять")
    author_is_client = models.BooleanField("От заказчика", default=True)
    status = models.CharField("Статус", max_length=16, choices=Status.choices, default=Status.NEW)
    answer = models.TextField("Ответ", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    reply_due_at = models.DateTimeField(
        "Ответить до",
        null=True,
        blank=True,
        help_text="Считается по регламенту в рабочих часах",
    )
    done_at = models.DateTimeField("Выполнена", null=True, blank=True)

    class Meta:
        verbose_name = "Правка"
        verbose_name_plural = "Правки"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Правка #{self.pk} · {self.stage.title}"


class SupervisionVisit(models.Model):
    """Выезд по авторскому надзору.

    Фактическая длительность пишется не для отчётности перед заказчиком:
    через несколько объектов появится статистика вместо «закладываю час,
    выходит три», и цена выезда начнёт считаться от фактов.
    """

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="visits")
    date = models.DateField("Дата")
    planned_hours = models.DecimalField("План, часов", max_digits=4, decimal_places=1, default=Decimal("1"))
    actual_hours = models.DecimalField("Факт, часов", max_digits=4, decimal_places=1, null=True, blank=True)
    is_remote = models.BooleanField("Созвон вместо выезда", default=False)
    report = models.TextField("Отчёт", blank=True)
    issues = models.TextField("Расхождения с проектом", blank=True)

    class Meta:
        verbose_name = "Выезд по надзору"
        verbose_name_plural = "Выезды по надзору"
        ordering = ["-date"]

    def __str__(self):
        return f"{self.date:%d.%m.%Y} · {self.project}"


class ProcurementStage(models.Model):
    """Этап комплектации.

    Бьётся по плану ремонтно-строительных работ: черновые материалы нужны
    раньше мебели, и оплачивать всё сразу незачем.
    """

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="procurement_stages")
    number = models.PositiveSmallIntegerField("Номер")
    title = models.CharField("Название", max_length=200)
    budget = models.DecimalField("Бюджет", max_digits=12, decimal_places=2, default=Decimal("0"))
    is_closed = models.BooleanField("Закрыт", default=False)

    class Meta:
        verbose_name = "Этап комплектации"
        verbose_name_plural = "Этапы комплектации"
        ordering = ["project", "number"]

    def __str__(self):
        return f"{self.number}. {self.title}"


class ProcurementItem(models.Model):
    class Status(models.TextChoices):
        PICKED = "picked", "Подобрано"
        QUOTED = "quoted", "Запрошено КП"
        COMPARED = "compared", "Сравнено"
        ORDERED = "ordered", "Заказано"
        PAID = "paid", "Оплачено"
        SHIPPING = "shipping", "В пути"
        ARRIVED = "arrived", "На объекте"
        ACCEPTED = "accepted", "Принято"

    stage = models.ForeignKey(ProcurementStage, on_delete=models.CASCADE, related_name="items")
    title = models.CharField("Позиция", max_length=250)
    article = models.CharField("Артикул", max_length=120, blank=True)
    supplier = models.CharField("Поставщик", max_length=200, blank=True)
    price = models.DecimalField("Цена", max_digits=12, decimal_places=2, default=Decimal("0"))
    reserve_percent = models.DecimalField(
        "Технический запас, %",
        max_digits=5,
        decimal_places=2,
        default=Decimal("0"),
        help_text="Считается по каждому материалу с учётом его особенностей",
    )
    lead_time_days = models.PositiveSmallIntegerField("Срок поставки, дней", default=0)
    status = models.CharField("Статус", max_length=16, choices=Status.choices, default=Status.PICKED)
    is_replacement = models.BooleanField(
        "Замена проектной позиции",
        default=False,
        help_text="Замена до 15 % от проектной ведомости — рыночная норма",
    )
    note = models.TextField("Заметка", blank=True)

    class Meta:
        verbose_name = "Позиция комплектации"
        verbose_name_plural = "Позиции комплектации"
        ordering = ["stage", "title"]

    def __str__(self):
        return self.title
