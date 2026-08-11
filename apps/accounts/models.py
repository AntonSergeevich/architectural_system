"""Пользователи и роли."""

import secrets

from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.utils import timezone

from apps.core.utils import normalize_phone


class Role(models.TextChoices):
    OWNER = "owner", "Дарья"
    CLIENT = "client", "Заказчик"


class UserManager(BaseUserManager):
    """Логин — email или телефон, поэтому username здесь не используется."""

    use_in_migrations = True

    def _create(self, email, password, phone="", **extra):
        if not email:
            raise ValueError("Нужен email")
        user = self.model(
            email=self.normalize_email(email).lower(),
            phone=normalize_phone(phone) if phone else "",
            **extra,
        )
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email=None, password=None, phone="", **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create(email, password, phone, **extra)

    def create_superuser(self, email=None, password=None, phone="", **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("role", Role.OWNER)
        return self._create(email, password, phone, **extra)


class User(AbstractUser):
    """Заказчик или Дарья.

    Третьей роли пока нет, но она предвидится: 3D-визуализатор работает
    по техзаданию и однажды попросит доступ к своему куску проекта.
    Поэтому роль — отдельное поле, а не флаг is_staff.
    """

    username = None
    first_name = None
    last_name = None

    email = models.EmailField("Email", unique=True)
    phone = models.CharField("Телефон", max_length=20, blank=True)
    full_name = models.CharField("Имя", max_length=150, blank=True)
    role = models.CharField("Роль", max_length=16, choices=Role.choices, default=Role.CLIENT)

    # Логин по email — он же USERNAME_FIELD. Вход по телефону тоже работает,
    # но это забота бэкенда аутентификации: заказчики стабильно помнят
    # что-то одно, и заранее неизвестно, что именно.
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    class Meta:
        verbose_name = "Пользователь"
        verbose_name_plural = "Пользователи"
        constraints = [
            models.UniqueConstraint(
                fields=["phone"], condition=~models.Q(phone=""), name="uniq_user_phone"
            ),
        ]

    def __str__(self):
        return self.full_name or self.email or self.phone or f"#{self.pk}"

    def save(self, *args, **kwargs):
        self.phone = normalize_phone(self.phone)
        self.email = self.email.strip().lower()
        super().save(*args, **kwargs)

    @property
    def is_owner(self):
        return self.role == Role.OWNER

    def get_short_name(self):
        return self.full_name.split(" ")[0] if self.full_name else str(self)


class TelegramAccount(models.Model):
    """Привязка Telegram к аккаунту кабинета.

    Уведомления — дело добровольное. Заказчик, которому важно знать
    о каждом шаге, нажимает кнопку и получает сообщения в мессенджер,
    которым и так пользуется каждый день. Тому, кому это не нужно,
    ничего не приходит — и это тоже осознанный выбор, а не забытая
    настройка.

    Привязка идёт через код: кабинет выдаёт ссылку `t.me/бот?start=КОД`,
    бот присылает нам этот код вместе с chat_id. Так мы узнаём chat_id,
    не спрашивая его у человека — спрашивать бесполезно, никто не знает
    своего chat_id.
    """

    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="telegram", verbose_name="Пользователь"
    )
    chat_id = models.CharField("Chat ID", max_length=32, blank=True, db_index=True)
    username = models.CharField("Ник в Telegram", max_length=64, blank=True)
    link_code = models.CharField("Код привязки", max_length=24, unique=True)
    linked_at = models.DateTimeField("Привязан", null=True, blank=True)

    # Что присылать. Разное по смыслу: «этап поменялся» — это раз в неделю,
    # «новое сообщение» — это может быть десять раз за вечер.
    notify_stages = models.BooleanField("Смена этапа", default=True)
    notify_tasks = models.BooleanField("Новые задачи для меня", default=True)
    notify_messages = models.BooleanField("Сообщения", default=True)
    notify_money = models.BooleanField("Деньги и договоры", default=True)

    class Meta:
        verbose_name = "Telegram"
        verbose_name_plural = "Telegram"

    def __str__(self):
        return f"{self.user} → {self.username or self.chat_id or 'не привязан'}"

    @property
    def is_linked(self):
        return bool(self.chat_id)

    def wants(self, kind):
        return {
            "stage": self.notify_stages,
            "task": self.notify_tasks,
            "message": self.notify_messages,
            "money": self.notify_money,
        }.get(kind, True)

    @classmethod
    def for_user(cls, user):
        """Привязка пользователя; код заводится сразу, до всякой привязки."""
        account, _ = cls.objects.get_or_create(
            user=user, defaults={"link_code": secrets.token_urlsafe(9)}
        )
        return account

    def unlink(self):
        self.chat_id = ""
        self.username = ""
        self.linked_at = None
        # Код меняем: старая ссылка не должна работать после отвязки.
        self.link_code = secrets.token_urlsafe(9)
        self.save(update_fields=["chat_id", "username", "linked_at", "link_code"])


class LoginCode(models.Model):
    """Одноразовый код входа.

    Заказчиков в системе единицы, и заводить им пароли — лишний барьер:
    пароль от кабинета, куда заходят раз в неделю, всё равно будет забыт.
    """

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="login_codes")
    code = models.CharField("Код", max_length=8)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField("Действует до")
    used_at = models.DateTimeField("Использован", null=True, blank=True)

    class Meta:
        verbose_name = "Код входа"
        verbose_name_plural = "Коды входа"
        indexes = [models.Index(fields=["user", "code"])]

    def is_valid(self):
        return self.used_at is None and self.expires_at > timezone.now()
