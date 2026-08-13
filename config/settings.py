"""Настройки проекта: сайт и рабочая система архитектора-дизайнера."""

import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def env(name, default=None):
    return os.environ.get(name, default)


def env_bool(name, default=False):
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name, default=""):
    raw = os.environ.get(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


# Локальный .env читаем сами: лишняя зависимость ради пятнадцати строк
# кода не нужна, а на сервере переменные всё равно приходят из systemd.
_env_file = BASE_DIR / ".env"
if _env_file.exists():
    for _line in _env_file.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if not _line or _line.startswith("#") or "=" not in _line:
            continue
        _key, _value = _line.split("=", 1)
        _value = _value.strip()
        # Значение может быть записано в кавычках — так его пишут, когда
        # внутри есть пробелы или угловые скобки. Кавычки при этом
        # относятся к записи, а не к значению.
        if len(_value) >= 2 and _value[0] == _value[-1] and _value[0] in "\"'":
            _value = _value[1:-1]
        os.environ.setdefault(_key.strip(), _value)


SECRET_KEY = env("DJANGO_SECRET_KEY", "django-insecure-dev-only-change-me")
DEBUG = env_bool("DJANGO_DEBUG", True)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1],testserver")


def _trusted_origins():
    """Домены, которым разрешено отправлять формы.

    Список выводится из ALLOWED_HOSTS, а не пишется руками: забытый здесь
    домен даёт не понятную ошибку, а «Ошибка проверки CSRF, запрос
    отклонён» посреди работы — и найти причину без подсказки тяжело.
    Явная переменная окружения, если она задана, всё это перекрывает.
    """
    explicit = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")
    if explicit:
        return explicit

    origins = []
    for host in ALLOWED_HOSTS:
        if host in {"*", "localhost", "127.0.0.1", "[::1]", "testserver"}:
            continue
        # «.da-des.ru» в ALLOWED_HOSTS означает домен и все поддомены;
        # в списке origin это записывается через звёздочку.
        name = f"*{host}" if host.startswith(".") else host
        origins.append(f"https://{name}")
    return origins


CSRF_TRUSTED_ORIGINS = _trusted_origins()

# Страница вместо стандартной «Ошибка проверки CSRF». Токен устаревает,
# если вкладку с кабинетом открыли вчера, а сегодня зашли заново, — и это
# случается ровно на телефоне, где вкладки живут месяцами.
CSRF_FAILURE_VIEW = "apps.core.views.csrf_failure"

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "django.contrib.sitemaps",
    # проект
    "apps.accounts",
    "apps.core",
    "apps.catalog",
    "apps.crm",
    "apps.projects",
    "apps.contracts",
    "apps.billing",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.site",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"


def _postgres_settings():
    """PostgreSQL из отдельных переменных или из DATABASE_URL.

    Раздельные переменные — основной путь: пароль в них пишется как есть,
    без возни с URL-кодированием.
    """
    name = env("POSTGRES_DB")
    if name:
        return {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": name,
            "USER": env("POSTGRES_USER", "dades"),
            "PASSWORD": env("POSTGRES_PASSWORD", ""),
            "HOST": env("POSTGRES_HOST", "localhost"),
            "PORT": env("POSTGRES_PORT", "5432"),
            "CONN_MAX_AGE": 60,
        }

    url = env("DATABASE_URL", "")
    if not url.startswith("postgres"):
        return None

    from urllib.parse import unquote, urlparse

    parsed = urlparse(url)
    # urlparse отдаёт логин и пароль как есть; пароль со спецсимволами
    # обязан быть процентно-закодирован, значит здесь его надо раскодировать.
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": unquote(parsed.path.lstrip("/")),
        "USER": unquote(parsed.username or ""),
        "PASSWORD": unquote(parsed.password or ""),
        "HOST": parsed.hostname or "localhost",
        "PORT": parsed.port or 5432,
        "CONN_MAX_AGE": 60,
    }


_pg = _postgres_settings()
DATABASES = {
    "default": _pg
    or {
        # SQLite — только для локальной разработки. На сервере PostgreSQL.
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
        "OPTIONS": {"timeout": 20},
    }
}

AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = ["apps.accounts.backends.EmailOrPhoneBackend"]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "cabinet:home"
LOGOUT_REDIRECT_URL = "public:home"

LANGUAGE_CODE = "ru-ru"
TIME_ZONE = "Asia/Krasnoyarsk"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        if DEBUG
        else "whitenoise.storage.CompressedManifestStaticFilesStorage"
    },
}

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Формы: заявка с анкетой — это заметно больше полей, чем в среднем по вебу.
DATA_UPLOAD_MAX_NUMBER_FIELDS = 2000

# --- Почта -----------------------------------------------------------------
EMAIL_BACKEND = env("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = env("EMAIL_HOST", "")
EMAIL_PORT = int(env("EMAIL_PORT", "465"))
EMAIL_HOST_USER = env("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", "")


def _email_security(port):
    """Режим шифрования SMTP выводим из порта.

    465 — SMTPS, канал шифруется сразу, STARTTLS там не работает.
    587 — открытый порт с апгрейдом до TLS. Перепутать легко, а симптом
    неинформативный: письма просто не уходят.
    """
    smtps = port == 465
    ssl = env_bool("EMAIL_USE_SSL", smtps)
    tls = env_bool("EMAIL_USE_TLS", not smtps)
    if ssl and tls:
        # Django не стартует при обоих включённых, а порт говорит о намерении
        # честнее, чем забытая в .env строка.
        tls = False
    return ssl, tls


EMAIL_USE_SSL, EMAIL_USE_TLS = _email_security(EMAIL_PORT)
EMAIL_TIMEOUT = int(env("EMAIL_TIMEOUT", "20"))
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", "Дарья <noreply@localhost>")
SERVER_EMAIL = env("SERVER_EMAIL", DEFAULT_FROM_EMAIL)

SITE_URL = env("SITE_URL", "http://127.0.0.1:8000")

# --- Оплата: GetPlatinum ---------------------------------------------------
# Базовый адрес API вида https://<аккаунт>.getplatinum.ru/api/public/pay —
# он свой у каждой организации. Ключ берётся в личном кабинете:
# Настройки → организация → API-ключ. Он же используется для проверки
# подписи коллбэков, отдельного секрета у них нет.
GETPLATINUM_API_URL = env("GETPLATINUM_API_URL", "")
GETPLATINUM_API_KEY = env("GETPLATINUM_API_KEY", "")
# Ставка НДС для кассового чека. Для самозанятого — «none»: НДС
# не применяется. Ошибка здесь means нарушение налогового учёта,
# поэтому значение вынесено в настройки, а не зашито в код.
GETPLATINUM_VAT = env("GETPLATINUM_VAT", "none")
# Пока адрес и ключ не заданы, приём оплат выключен: кнопка не
# показывается, счёт отмечается оплаченным вручную.
PAYMENTS_ENABLED = bool(GETPLATINUM_API_URL and GETPLATINUM_API_KEY)

# --- Уведомления: Telegram --------------------------------------------------
# Бот @daarch_bot пишет Дарье о новых заявках: почту она смотрит раз в день,
# а заявка без быстрого ответа уходит к тому, кто ответил первым.
#
# Токен — это пароль от бота: по нему можно писать от её имени. Поэтому он
# живёт только в переменных окружения (.env на сервере, права 600) и никогда
# в репозитории.
#
# TELEGRAM_CHAT_ID — адресат, а не бот. Узнать свой: написать боту любое
# сообщение и открыть https://api.telegram.org/bot<ТОКЕН>/getUpdates —
# в ответе будет message.chat.id. Пока поля пустые, уведомления не шлются.
TELEGRAM_BOT_TOKEN = env("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = env("TELEGRAM_CHAT_ID", "")
# Имя бота без «@» — из него собирается ссылка привязки в кабинете.
TELEGRAM_BOT_USERNAME = env("TELEGRAM_BOT_USERNAME", "daarch_bot")
# Секрет в адресе вебхука. Адрес знает только Telegram, но адрес
# без секрета — это открытая дверь: постучаться в неё может кто угодно
# и прислать что угодно от имени бота.
TELEGRAM_WEBHOOK_SECRET = env("TELEGRAM_WEBHOOK_SECRET", "")

# --- Регламент -------------------------------------------------------------
# Часы работы. Из них считается обещанный срок ответа: не календарные сутки,
# а сутки рабочего времени. Правится в настройках сайта, здесь — значения
# по умолчанию для первой установки.
WORKDAY_START_HOUR = int(env("WORKDAY_START_HOUR", "10"))
WORKDAY_END_HOUR = int(env("WORKDAY_END_HOUR", "19"))

# --- Безопасность (боевой режим) -------------------------------------------
if not DEBUG:
    SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = "DENY"

# Тесты не должны упираться в PBKDF2 — это там единственное узкое место.
if "test" in sys.argv:
    PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
    EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
}
