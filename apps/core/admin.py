from django.contrib import admin
from django.utils.html import format_html

from .models import (
    Article,
    CookieConsent,
    LegalDocument,
    Objection,
    PersonalDataConsent,
    PortfolioPhoto,
    PortfolioProject,
    PressMention,
    SiteSettings,
    StageNorm,
)


@admin.register(SiteSettings)
class SiteSettingsAdmin(admin.ModelAdmin):
    fieldsets = (
        (
            "О себе",
            {
                "fields": (
                    "owner_name",
                    "owner_title",
                    "owner_photo",
                    "owner_intro_title",
                    "owner_intro",
                    "owner_about",
                ),
                "description": "Всё, что написано о вас на сайте, живёт здесь. "
                "«Коротко» показывается на главной, «Текст о себе» — на странице "
                "«Обо мне». Пустое поле означает, что блока на сайте не будет",
            },
        ),
        ("Контакты", {"fields": ("phone", "email", "telegram", "whatsapp", "city")}),
        (
            "Соцсети",
            {
                "fields": ("instagram", "vk", "pinterest", "dzen"),
                "description": "Ссылка на Instagram публикуется с пометкой о том, "
                "что Meta признана в России экстремистской организацией",
            },
        ),
        ("Реквизиты", {"fields": ("legal_name", "inn")}),
        (
            "Регламент",
            {
                "fields": ("workday_start", "workday_end", "reply_hours", "regulations"),
                "description": "Публикуется на сайте дословно и подтверждается в договоре",
            },
        ),
        (
            "Загрузка",
            {
                "fields": ("wip_limit",),
                "description": "Сверх этого числа проекты встают в очередь. "
                "Именно этот предел защищает от выгорания",
            },
        ),
    )

    def has_add_permission(self, request):
        return not SiteSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(LegalDocument)
class LegalDocumentAdmin(admin.ModelAdmin):
    list_display = ("title", "kind", "version", "published_at", "is_published")
    list_filter = ("kind", "is_published")


class PortfolioPhotoInline(admin.TabularInline):
    """Фотографии объекта.

    Порядок задаётся перетаскиванием строк за ручку слева: номерами
    его задавать можно, но нельзя *смотреть*. Человек раскладывает кадры
    глазами — «этот после того», — а не считает десятки в голове.
    Поля с номером остаются на месте: без JavaScript и для точной правки.
    """

    model = PortfolioPhoto
    extra = 3
    fields = ("preview", "image", "caption", "is_cover", "is_wide", "is_before", "order")
    readonly_fields = ("preview",)

    class Media:
        js = ("js/admin_sort.js",)
        css = {"all": ("css/admin_sort.css",)}

    @admin.display(description="Кадр")
    def preview(self, obj):
        """Миниатюра в строке.

        Без неё перетаскивание бессмысленно: в списке видно имя файла
        вроде «IMG_4417.jpg», а раскладывают всё-таки картинки.
        """
        if not obj.pk or not obj.image:
            return "—"
        return format_html('<img src="{}" alt="" class="photo-thumb">', obj.image.url)


@admin.register(PortfolioProject)
class PortfolioProjectAdmin(admin.ModelAdmin):
    list_display = ("title", "city", "year", "area", "is_published", "is_featured")
    list_editable = ("is_published", "is_featured")
    list_filter = ("is_published", "is_featured", "city")
    prepopulated_fields = {"slug": ("title",)}
    filter_horizontal = ("modules",)
    inlines = [PortfolioPhotoInline]
    fieldsets = (
        (None, {"fields": ("title", "slug", "city", "year", "area", "style", "summary")}),
        ("Кейс", {"fields": ("task", "solution", "result", "modules")}),
        (
            "Заказчик",
            {
                "fields": (
                    "client_name",
                    "client_quote",
                    "client_photo",
                    "client_video",
                    "client_consent",
                ),
                "description": "Без галочки согласия ничего из этого на сайт не выводится",
            },
        ),
        ("Публикация", {"fields": ("is_published", "is_featured", "order")}),
    )


@admin.register(PressMention)
class PressMentionAdmin(admin.ModelAdmin):
    list_display = ("outlet", "issue", "title", "date", "is_published", "order")
    list_editable = ("is_published", "order")
    list_filter = ("outlet",)
    fieldsets = (
        ("Публикация", {"fields": ("outlet", "issue", "title", "date", "quote")}),
        (
            "Что показать",
            {
                "fields": ("cover", "spread", "file", "url", "logo"),
                "description": "Обложка номера — главное здесь. Логотип издания говорит "
                "«нас упоминали», обложка — «я держала это в руках». Свой PDF надёжнее "
                "ссылки: издания переезжают и закрывают архивы",
            },
        ),
        ("Показ", {"fields": ("is_published", "order")}),
    )


@admin.register(Objection)
class ObjectionAdmin(admin.ModelAdmin):
    list_display = ("question", "is_published", "order")
    list_editable = ("is_published", "order")


@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = ("title", "published_at", "is_published")
    list_editable = ("is_published",)
    prepopulated_fields = {"slug": ("title",)}


@admin.register(StageNorm)
class StageNormAdmin(admin.ModelAdmin):
    list_display = ("number", "title", "working_days", "client_days")
    list_editable = ("working_days", "client_days")


@admin.register(CookieConsent)
class CookieConsentAdmin(admin.ModelAdmin):
    list_display = ("created_at", "choice", "analytics", "policy_version")
    list_filter = ("choice",)
    readonly_fields = [f.name for f in CookieConsent._meta.fields]

    def has_add_permission(self, request):
        return False


@admin.register(PersonalDataConsent)
class PersonalDataConsentAdmin(admin.ModelAdmin):
    list_display = ("created_at", "name", "contact", "source", "document_version")
    readonly_fields = [f.name for f in PersonalDataConsent._meta.fields]

    def has_add_permission(self, request):
        return False
