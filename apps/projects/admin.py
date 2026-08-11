from django.contrib import admin

from .models import (
    Approval,
    ProcurementItem,
    ProcurementStage,
    Project,
    Revision,
    Stage,
    StageFile,
    SupervisionVisit,
)


class StageInline(admin.TabularInline):
    model = Stage
    extra = 0
    fields = ("number", "title", "status", "waiting_on", "planned_days", "started_at", "finished_at")


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("__str__", "status", "starts_at", "progress")
    list_filter = ("status",)
    filter_horizontal = ("modules",)
    inlines = [StageInline]


@admin.register(Stage)
class StageAdmin(admin.ModelAdmin):
    list_display = ("project", "number", "title", "status", "waiting_on")
    list_filter = ("status", "waiting_on")


@admin.register(Revision)
class RevisionAdmin(admin.ModelAdmin):
    list_display = ("__str__", "room", "status", "created_at", "reply_due_at")
    list_filter = ("status",)


admin.site.register([Approval, StageFile, SupervisionVisit, ProcurementStage, ProcurementItem])
