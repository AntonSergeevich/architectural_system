from django.contrib import admin

from .models import (
    ComplexityFactor,
    ModuleGroup,
    Preset,
    PriceHistory,
    PricingSettings,
    ServiceModule,
)


@admin.register(ServiceModule)
class ServiceModuleAdmin(admin.ModelAdmin):
    list_display = ("code", "title", "block", "unit", "price", "is_required", "is_active")
    list_editable = ("price", "is_active")
    list_filter = ("block", "unit", "is_active", "is_required")
    search_fields = ("code", "title")
    ordering = ("block", "order")
    fieldsets = (
        (None, {"fields": ("code", "title", "short_title", "block", "group", "house_part", "order")}),
        (
            "Цена",
            {"fields": ("unit", "price", "included_units", "extra_unit_price", "affected_by_complexity")},
        ),
        ("Поведение", {"fields": ("is_required", "is_active", "duration_days")}),
        ("Тексты", {"fields": ("description", "outcome", "not_included", "warning")}),
    )

    def save_model(self, request, obj, form, change):
        # История цен пишется сама: иначе через год не понять, почему
        # в старом КП стояла другая цифра.
        if change and "price" in form.changed_data:
            PriceHistory.objects.create(
                module=obj, price=obj.price, unit=obj.unit, comment="изменено в админке"
            )
        super().save_model(request, obj, form, change)


@admin.register(ModuleGroup)
class ModuleGroupAdmin(admin.ModelAdmin):
    list_display = ("code", "title", "house_part", "order")


@admin.register(ComplexityFactor)
class ComplexityFactorAdmin(admin.ModelAdmin):
    list_display = ("title", "factor", "is_default", "order")
    list_editable = ("factor", "is_default")


@admin.register(Preset)
class PresetAdmin(admin.ModelAdmin):
    list_display = ("title", "code", "is_default", "is_active", "order")
    list_editable = ("is_default", "is_active", "order")
    filter_horizontal = ("modules",)


@admin.register(PriceHistory)
class PriceHistoryAdmin(admin.ModelAdmin):
    list_display = ("module", "price", "unit", "changed_at", "comment")
    list_filter = ("module",)
    readonly_fields = ("changed_at",)


@admin.register(PricingSettings)
class PricingSettingsAdmin(admin.ModelAdmin):
    fieldsets = (
        (
            "Сложность интерьера",
            {
                "fields": ("complexity_enabled",),
                "description": "Пока выключено, вопрос про характер интерьера "
                "на сайте не показывается и цена одна для всех. "
                "Коэффициенты заведены и ждут — включение занимает одну галочку",
            },
        ),
        (
            "Маленькие помещения",
            {"fields": ("small_area_enabled", "small_area_threshold", "small_area_price")},
        ),
        ("Сроки и итог", {"fields": ("months_per_100_sqm", "show_grand_total")}),
    )

    def has_add_permission(self, request):
        return not PricingSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
