from django.contrib import admin

from .models import Client, Lead, Property, Quote, QuoteItem


class PropertyInline(admin.TabularInline):
    model = Property
    extra = 0


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ("name", "phone", "email", "source", "created_at")
    search_fields = ("name", "phone", "email")
    inlines = [PropertyInline]


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ("client", "status", "is_spam", "next_action", "next_action_at", "created_at")
    list_filter = ("status", "is_spam")
    actions = ["mark_spam"]

    @admin.action(description="Пометить спамом")
    def mark_spam(self, request, queryset):
        queryset.update(is_spam=True)
    search_fields = ("client__name", "client__phone")
    date_hierarchy = "next_action_at"


class QuoteItemInline(admin.TabularInline):
    model = QuoteItem
    extra = 0
    readonly_fields = ("unit_price", "quantity", "amount")


@admin.register(Quote)
class QuoteAdmin(admin.ModelAdmin):
    list_display = ("id", "client", "area", "design_total", "status", "valid_until", "opened_at")
    list_filter = ("status",)
    readonly_fields = ("token", "opened_at")
    inlines = [QuoteItemInline]


@admin.register(Property)
class PropertyAdmin(admin.ModelAdmin):
    list_display = ("client", "address", "kind", "area", "measured_area", "rooms")
    list_filter = ("kind", "city")
