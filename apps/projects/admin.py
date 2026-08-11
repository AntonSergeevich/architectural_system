from django.contrib import admin

from .models import (
    Approval,
    BudgetChange,
    Message,
    MessageFile,
    ProcurementItem,
    ProcurementStage,
    Project,
    ProjectPayment,
    Revision,
    Stage,
    StageFile,
    StageTask,
    SupervisionVisit,
    TaskPreset,
)


class StageInline(admin.TabularInline):
    model = Stage
    extra = 0
    fields = ("number", "title", "status", "waiting_on", "planned_days", "started_at", "finished_at")


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("__str__", "status", "starts_at", "agreed_amount", "progress")
    list_filter = ("status",)
    filter_horizontal = ("modules",)
    inlines = [StageInline]


@admin.register(Stage)
class StageAdmin(admin.ModelAdmin):
    list_display = ("project", "number", "title", "status", "waiting_on")
    list_filter = ("status", "waiting_on")


@admin.register(StageTask)
class StageTaskAdmin(admin.ModelAdmin):
    list_display = ("title", "stage", "who", "is_done", "due_date")
    list_filter = ("who", "is_done")


@admin.register(TaskPreset)
class TaskPresetAdmin(admin.ModelAdmin):
    """Готовые формулировки задач: Дарья правит их сама.

    Список намеренно открыт для правки — он про её работу, а не про
    структуру данных, и меняться будет чаще всего остального.
    """

    list_display = ("title", "stage_number", "who", "order", "is_active")
    list_filter = ("stage_number", "who", "is_active")
    list_editable = ("order", "is_active")


@admin.register(ProjectPayment)
class ProjectPaymentAdmin(admin.ModelAdmin):
    list_display = ("project", "kind", "amount", "paid_on", "stage")
    list_filter = ("kind",)
    date_hierarchy = "paid_on"


@admin.register(BudgetChange)
class BudgetChangeAdmin(admin.ModelAdmin):
    list_display = ("title", "project", "amount", "status", "created_at", "decided_at")
    list_filter = ("status",)


class MessageFileInline(admin.TabularInline):
    model = MessageFile
    extra = 0


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    """Переписка — доказательная база, поэтому только чтение.

    Возможность отредактировать сообщение задним числом обесценивает
    весь архив: доказывать им становится нечего.
    """

    list_display = ("project", "author_name", "created_at", "read_at")
    list_filter = ("author_is_owner",)
    inlines = [MessageFileInline]

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Revision)
class RevisionAdmin(admin.ModelAdmin):
    list_display = ("__str__", "room", "status", "created_at", "reply_due_at")
    list_filter = ("status",)


admin.site.register([Approval, StageFile, SupervisionVisit, ProcurementStage, ProcurementItem])
