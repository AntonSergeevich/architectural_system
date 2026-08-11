from django.contrib import admin

from .models import Invoice, Payment


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0
    readonly_fields = ("provider_payment_id", "raw", "created_at")


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ("__str__", "client", "amount", "status", "due_date", "paid_at")
    list_filter = ("status",)
    readonly_fields = ("token",)
    inlines = [PaymentInline]


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("invoice", "provider", "amount", "status", "created_at")
    list_filter = ("provider", "status")
    readonly_fields = ("raw",)
