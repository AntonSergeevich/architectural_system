"""Проекты, этапы, задачи, деньги и переписка.

Здесь живёт всё, что заказчик видит в своём кабинете, и всё, чем Дарья
ведёт проект. Главное правило: происходящее с проектом видно обоим
одинаково. Вопрос «а что там у нас», заданный в мессенджер, — это дефект
интерфейса, а не назойливость заказчика.
"""

from decimal import Decimal

from django.conf import settings
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

    # Сумма, о которой договорились на старте. Она не берётся из счетов
    # и не пересчитывается сама: это точка отсчёта, относительно которой
    # видно и оплаченное, и любой выход за рамки.
    agreed_amount = models.DecimalField(
        "Договорились на сумму",
        max_digits=12,
        decimal_places=2,
        default=Decimal("0"),
        help_text="Стоимость проекта на старте. Всё, что сверх неё, "
        "оформляется отдельно и с обоснованием",
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

    # --- Деньги ------------------------------------------------------------
    # Считаются здесь, а не в шаблоне: цифра «сколько осталось» должна быть
    # одна и та же в обоих кабинетах. Две реализации однажды разойдутся,
    # и это будет ровно тот разговор, ради которого система и строится.

    @property
    def approved_extra(self):
        """Согласованные доплаты сверх договорённости."""
        return sum(
            (c.amount for c in self.budget_changes.all() if c.status == BudgetChange.Status.ACCEPTED),
            Decimal("0"),
        )

    @property
    def total_amount(self):
        return self.agreed_amount + self.approved_extra

    @property
    def paid_amount(self):
        return sum((p.amount for p in self.payments.all()), Decimal("0"))

    @property
    def left_to_pay(self):
        return max(self.total_amount - self.paid_amount, Decimal("0"))

    @property
    def paid_percent(self):
        if self.total_amount <= 0:
            return 0
        return min(int(self.paid_amount * 100 / self.total_amount), 100)

    @property
    def pending_budget_changes(self):
        return [c for c in self.budget_changes.all() if c.status == BudgetChange.Status.PROPOSED]


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


class StageTask(models.Model):
    """Что конкретно должно быть сделано на этапе прямо сейчас.

    Статус этапа отвечает на вопрос «где мы», а задача — на вопрос
    «чего ждём». Это разные вопросы, и заказчик задаёт второй.

    У задачи есть исполнитель, и он тоже виден заказчику. Половина
    тревожных сообщений — это «я не понимаю, ждут ли чего-то от меня».
    """

    class Owner(models.TextChoices):
        OWNER = "owner", "Дарья"
        CLIENT = "client", "Заказчик"
        BOTH = "both", "Вместе"

    stage = models.ForeignKey("Stage", on_delete=models.CASCADE, related_name="tasks")
    title = models.CharField("Что сделать", max_length=250)
    who = models.CharField("Кто делает", max_length=8, choices=Owner.choices, default=Owner.OWNER)
    is_done = models.BooleanField("Сделано", default=False)
    done_at = models.DateTimeField("Когда сделано", null=True, blank=True)
    due_date = models.DateField("Срок", null=True, blank=True)
    comment = models.TextField("Пояснение", blank=True)
    order = models.PositiveSmallIntegerField("Порядок", default=100)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Задача этапа"
        verbose_name_plural = "Задачи этапа"
        ordering = ["is_done", "order", "pk"]

    def __str__(self):
        return self.title

    def toggle(self, done):
        self.is_done = done
        self.done_at = timezone.now() if done else None
        self.save(update_fields=["is_done", "done_at"])


class TaskPreset(models.Model):
    """Готовая формулировка задачи — ставится одним нажатием.

    Дарья ведёт восемь этапов подряд у каждого проекта, и на каждом
    повторяются одни и те же пункты. Печатать их заново — гарантия того,
    что однажды перестанут печатать вовсе. Но список закрытым быть
    не может: свою задачу всегда можно дописать руками.
    """

    stage_number = models.PositiveSmallIntegerField(
        "Номер этапа",
        null=True,
        blank=True,
        help_text="Пусто — подсказка появляется на любом этапе",
    )
    title = models.CharField("Что сделать", max_length=250)
    who = models.CharField(
        "Кто делает", max_length=8, choices=StageTask.Owner.choices, default=StageTask.Owner.OWNER
    )
    order = models.PositiveSmallIntegerField("Порядок", default=100)
    is_active = models.BooleanField("Показывать", default=True)

    class Meta:
        verbose_name = "Готовая задача"
        verbose_name_plural = "Готовые задачи"
        ordering = ["stage_number", "order", "pk"]

    def __str__(self):
        return self.title


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

    @property
    def label(self):
        """Имя файла, а не путь вида projects/2026/08/438.JPG."""
        return self.title or self.file.name.rsplit("/", 1)[-1]

    @property
    def is_image(self):
        return self.file.name.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".gif"))

    @property
    def is_pdf(self):
        return self.file.name.lower().endswith(".pdf")


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


class ProjectPayment(models.Model):
    """Оплата по проекту, внесённая руками.

    Дарья принимает переводы на карту и по счёту, и система обязана это
    учитывать. Эквайринг (`billing`) — отдельная история: он про оплату
    кнопкой на сайте, а здесь про факт «деньги пришли».

    Платёж привязан к этапу, если это оплата этапа: тогда в кабинете
    видно не «оплачено 180 000», а за что именно.
    """

    class Kind(models.TextChoices):
        PREPAY = "prepay", "Предоплата"
        STAGE = "stage", "Оплата этапа"
        EXTRA = "extra", "Доплата"
        FINAL = "final", "Окончательный расчёт"

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="payments")
    stage = models.ForeignKey(
        "Stage", on_delete=models.SET_NULL, null=True, blank=True, related_name="payments",
        verbose_name="Этап",
    )
    kind = models.CharField("За что", max_length=12, choices=Kind.choices, default=Kind.STAGE)
    title = models.CharField("Назначение", max_length=200, blank=True)
    amount = models.DecimalField("Сумма", max_digits=12, decimal_places=2)
    paid_on = models.DateField("Дата", default=timezone.localdate)
    comment = models.TextField("Комментарий", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Оплата по проекту"
        verbose_name_plural = "Оплаты по проекту"
        ordering = ["-paid_on", "-pk"]

    def __str__(self):
        return f"{self.amount} ₽ · {self.get_kind_display()}"

    @property
    def label(self):
        if self.title:
            return self.title
        if self.stage:
            return f"{self.get_kind_display()}: {self.stage.title}"
        return self.get_kind_display()


class BudgetChange(models.Model):
    """Выход за рамки договорённости — с обоснованием и согласием.

    Это самое опасное место в отношениях с заказчиком, и решается оно
    не силой воли, а порядком: сумма не может вырасти молча. Дарья
    оформляет изменение, обязательно пишет причину и что будет,
    если не делать. Заказчик видит это в своём кабинете и принимает
    или отклоняет — нажатием, с датой.

    Пока изменение не принято, оно не входит в сумму проекта. Принятое
    входит и больше не редактируется: это уже документ, а не черновик.
    """

    class Status(models.TextChoices):
        PROPOSED = "proposed", "На согласовании"
        ACCEPTED = "accepted", "Согласовано"
        DECLINED = "declined", "Отклонено"

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="budget_changes")
    stage = models.ForeignKey(
        "Stage", on_delete=models.SET_NULL, null=True, blank=True, related_name="budget_changes",
        verbose_name="Этап",
    )
    title = models.CharField("Что меняется", max_length=250)
    amount = models.DecimalField(
        "На сколько",
        max_digits=12,
        decimal_places=2,
        help_text="Со знаком: 30000 — подорожало, -30000 — подешевело",
    )
    reason = models.TextField(
        "Почему", help_text="Обоснование обязательно. Без него это не изменение сметы, а просьба"
    )
    consequence = models.TextField(
        "Что будет, если не делать",
        blank=True,
        help_text="Заказчик имеет право отказаться, зная последствия",
    )
    status = models.CharField("Статус", max_length=12, choices=Status.choices, default=Status.PROPOSED)
    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField("Решение принято", null=True, blank=True)
    decided_by = models.CharField("Кто решил", max_length=150, blank=True)
    client_comment = models.TextField("Комментарий заказчика", blank=True)

    class Meta:
        verbose_name = "Изменение сметы"
        verbose_name_plural = "Изменения сметы"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} ({self.amount:+} ₽)"

    @property
    def is_pending(self):
        return self.status == self.Status.PROPOSED

    def decide(self, accepted, by="", comment=""):
        self.status = self.Status.ACCEPTED if accepted else self.Status.DECLINED
        self.decided_at = timezone.now()
        self.decided_by = by
        self.client_comment = comment
        self.save(update_fields=["status", "decided_at", "decided_by", "client_comment"])


class Message(models.Model):
    """Сообщение в переписке по проекту.

    Переписка живёт здесь, а не в мессенджере, по двум причинам. Первая:
    в мессенджере она перемешана с личным и теряется. Вторая, более
    важная: при разбирательстве нужна доказательная база — кто, что
    и когда сказал. Поэтому сообщения не редактируются и не удаляются
    ни одной из сторон.
    """

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="messages")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="project_messages",
        verbose_name="Автор",
    )
    # Имя копируется в момент отправки: аккаунт можно переименовать или
    # удалить, а переписка обязана остаться читаемой и годной как
    # доказательство.
    author_name = models.CharField("Имя автора", max_length=150, blank=True)
    author_is_owner = models.BooleanField("От Дарьи", default=False)
    stage = models.ForeignKey(
        "Stage", on_delete=models.SET_NULL, null=True, blank=True, related_name="messages",
        verbose_name="Этап",
    )
    text = models.TextField("Сообщение", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField("Прочитано другой стороной", null=True, blank=True)

    class Meta:
        verbose_name = "Сообщение по проекту"
        verbose_name_plural = "Переписка по проекту"
        ordering = ["created_at"]
        indexes = [models.Index(fields=["project", "created_at"])]

    def __str__(self):
        return f"{self.author_name}: {self.text[:40]}"


class MessageFile(models.Model):
    """Файл в переписке.

    Хранится вместе с сообщением: «я вам присылала» без даты и файла
    ничего не значит.
    """

    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name="files")
    file = models.FileField("Файл", upload_to="chat/%Y/%m/")
    name = models.CharField("Имя файла", max_length=250, blank=True)
    size = models.PositiveIntegerField("Размер, байт", default=0)

    class Meta:
        verbose_name = "Файл переписки"
        verbose_name_plural = "Файлы переписки"

    def __str__(self):
        return self.name or self.file.name

    @property
    def is_image(self):
        return self.name.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".gif"))

    @property
    def human_size(self):
        size = self.size
        for unit in ("Б", "КБ", "МБ", "ГБ"):
            if size < 1024:
                return f"{size:.0f} {unit}" if unit == "Б" else f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} ТБ"


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
