from django.contrib import admin

from .models import ClauseQuestion, Contract, ContractAck, ContractClause, ContractTemplate


class ContractClauseInline(admin.StackedInline):
    model = ContractClause
    extra = 0
    fields = ("number", "title", "text", "plain_text", "is_important", "order")


@admin.register(ContractTemplate)
class ContractTemplateAdmin(admin.ModelAdmin):
    list_display = ("title", "kind", "version", "is_active", "updated_at")
    list_filter = ("kind", "is_active")
    inlines = [ContractClauseInline]


@admin.register(Contract)
class ContractAdmin(admin.ModelAdmin):
    list_display = ("__str__", "client", "date", "amount", "status")
    list_filter = ("status", "template__kind")
    readonly_fields = ("token",)


admin.site.register([ClauseQuestion, ContractAck])
