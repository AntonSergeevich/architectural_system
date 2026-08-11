"""Кабинет заказчика.

Отвечает на вопрос, с которого начинается тревога: что происходит с моим
проектом прямо сейчас. Каждый вопрос «а что там у нас», заданный
в мессенджер, — это дефект интерфейса, а не назойливость заказчика.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.forms import RevisionForm
from apps.core.models import SiteSettings
from apps.core.utils import working_deadline
from apps.projects.models import Approval, Project, Revision, Stage


def _project_for(user):
    client = getattr(user, "client", None)
    if client is None:
        raise Http404("Проект не найден")
    project = (
        Project.objects.filter(client=client)
        .exclude(status=Project.Status.DONE)
        .order_by("-created_at")
        .first()
        or Project.objects.filter(client=client).order_by("-created_at").first()
    )
    if project is None:
        raise Http404("Проект не найден")
    return project


@login_required
def project(request):
    obj = _project_for(request.user)
    stages = obj.stages.prefetch_related("revisions", "files").order_by("number")
    return render(
        request,
        "cabinet/my_project.html",
        {
            "project": obj,
            "stages": stages,
            "current": obj.current_stage,
            "form": RevisionForm(),
            "invoices": obj.invoices.all(),
            "contracts": obj.contracts.all(),
        },
    )


@login_required
@require_POST
def add_revision(request):
    """Правка приходит сюда, а не в мессенджер.

    Тогда её не нужно переписывать второй раз ради договора, объём правок
    виден обоим, а история согласований существует.
    """
    obj = _project_for(request.user)
    form = RevisionForm(request.POST)
    stage = get_object_or_404(Stage, pk=request.POST.get("stage"), project=obj)

    if not form.is_valid():
        messages.error(request, "Опишите, что нужно поменять.")
        return redirect("cabinet:my_project")

    site = SiteSettings.get()
    Revision.objects.create(
        stage=stage,
        room=form.cleaned_data["room"],
        text=form.cleaned_data["text"],
        author_is_client=True,
        reply_due_at=working_deadline(
            timezone.now(),
            hours=site.reply_hours,
            day_start=site.workday_start,
            day_end=site.workday_end,
            workdays=site.workdays,
        ),
    )
    messages.success(request, "Правка записана. Отвечу по регламенту.")
    return redirect("cabinet:my_project")


@login_required
@require_POST
def approve_stage(request, stage_id):
    """Согласование этапа — зафиксированное действие с датой."""
    obj = _project_for(request.user)
    stage = get_object_or_404(Stage, pk=stage_id, project=obj)
    if hasattr(stage, "approval"):
        messages.info(request, "Этот этап уже согласован.")
        return redirect("cabinet:my_project")

    Approval.objects.create(
        stage=stage,
        approved_by=request.user.full_name or str(request.user),
        comment=request.POST.get("comment", ""),
    )
    stage.status = Stage.Status.DONE
    stage.finished_at = timezone.localdate()
    stage.waiting_on = Stage.WaitingOn.NOBODY
    stage.save(update_fields=["status", "finished_at", "waiting_on"])
    messages.success(request, "Этап согласован, двигаемся дальше.")
    return redirect("cabinet:my_project")
