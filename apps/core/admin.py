from django.contrib import admin

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
        ("О себе", {"fields": ("owner_name", "owner_title", "owner_photo", "owner_about")}),
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
    model = PortfolioPhoto
    extra = 3
    fields = ("image", "caption", "is_cover", "is_wide", "is_before", "order")


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
    list_display = ("outlet", "title", "date", "is_published", "order")
    list_editable = ("is_published", "order")
    list_filter = ("outlet",)


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
