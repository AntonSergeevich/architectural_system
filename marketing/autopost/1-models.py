# ── Вставить в landing/models.py ───────────────────────────────────────────
# Рядом с остальными моделями. TimeStamped уже есть в этом файле.

class Post(TimeStamped):
    """Пост в телеграм-канал: написали заранее, ушёл по расписанию.

    Автоматизируется не сочинение текста, а дисциплина публикации. Текст
    пишет человек и кладёт в очередь; дальше система следит, чтобы он вышел
    вовремя и ровно один раз. Это ровно то, что мы продаём клиентам: система
    не работает вместо человека, она не даёт ему забыть.
    """

    class Status(models.TextChoices):
        DRAFT = 'draft', 'Черновик'
        QUEUED = 'queued', 'В очереди'
        SENDING = 'sending', 'Отправляется'
        SENT = 'sent', 'Опубликован'
        CANCELLED = 'cancelled', 'Отменён'
        FAILED = 'failed', 'Не ушёл'

    MAX_ATTEMPTS = 3

    title = models.CharField(
        'Название', max_length=200,
        help_text='Только для этого списка, в канал не уходит')
    body = models.TextField(
        'Текст', help_text='HTML: <b>, <i>, <a href>, <code>. Остальное Telegram не поймёт')
    image = models.ImageField('Картинка', upload_to='posts/', blank=True)
    publish_at = models.DateTimeField('Когда публиковать')
    status = models.CharField('Статус', max_length=10,
                              choices=Status.choices, default=Status.DRAFT)

    # Служебное: заполняет система, руками не трогаем.
    sent_at = models.DateTimeField('Ушёл', null=True, blank=True)
    message_id = models.BigIntegerField(
        'ID сообщения', null=True, blank=True,
        help_text='Чтобы потом можно было найти и отредактировать пост в канале')
    attempts = models.PositiveSmallIntegerField('Попыток отправки', default=0)
    last_error = models.CharField('Последняя ошибка', max_length=300, blank=True)
    announced_at = models.DateTimeField(
        'Предупреждение отправлено', null=True, blank=True,
        help_text='Чтобы не напоминать об одном и том же посте каждый час')

    class Meta:
        verbose_name = 'Пост'
        verbose_name_plural = 'Посты'
        ordering = ('-publish_at',)
        indexes = [models.Index(fields=('status', 'publish_at'))]

    def __str__(self):
        return f'{self.title} — {self.get_status_display()}'

    @property
    def is_due(self):
        return self.status == self.Status.QUEUED and self.publish_at <= timezone.now()
