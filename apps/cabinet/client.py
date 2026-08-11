"""Кабинет заказчика.

Отвечает на вопрос, с которого начинается тревога: что происходит с моим
проектом прямо сейчас и ждут ли чего-то от меня. Каждый вопрос «а что там
у нас», заданный в мессенджер, — это дефект интерфейса, а не назойливость
заказчика.

Кабинет заказчика — не урезанная копия кабинета Дарьи. У них разные
вопросы: она спрашивает «за что взяться», он — «когда и что от меня».
Поэтому и экраны разные, а данные под ними одни и те же.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.contracts.models import Contract
from apps.core import notify
from apps.core.forms import RevisionForm
from apps.core.models import SiteSettings
from apps.core.utils import working_deadline
from apps.projects.models import Approval, BudgetChange, Project, Revision, Stage

from . import services
from .forms import MessageForm


def _project_for(user):
    client = getattr(user, "client", None)
    if client is None:
        raise Http404("Проект не найден")
    project = (
        services.project_queryset()
        .filter(client=client)
        .exclude(status=Project.Status.DONE)
        .order_by("-created_at")
        .first()
        or services.project_queryset().filter(client=client).order_by("-created_at").first()
    )
    if project is None:
        raise Http404("Проект не найден")
    return project


@login_required
def project(request):
    obj = _project_for(request.user)
    services.mark_messages_read(obj, request.user)

    stages = list(obj.stages.order_by("number"))
    current = obj.current_stage

    # «Что от меня ждут» — первое, что человек должен увидеть. Всё
    # остальное он посмотрит, только если этот вопрос закрыт.
    my_tasks = [
        task
        for stage in stages
        for task in stage.tasks.all()
        if not task.is_done and task.who in {"client", "both"}
    ]

    contracts = list(obj.contracts.all())
    return render(
        request,
        "cabinet/my_project.html",
        {
            "project": obj,
            "stages": stages,
            "current": current,
            "my_tasks": my_tasks,
            "form": RevisionForm(),
            "message_form": MessageForm(),
            "messages_list": obj.messages.all(),
            "open_contracts": [c for c in contracts if not c.is_signed],
            "signed_contracts": [c for c in contracts if c.is_signed],
            "pending_changes": obj.pending_budget_changes,
            "decided_changes": [c for c in obj.budget_changes.all() if not c.is_pending],
            "invoices": obj.invoices.all(),
            "is_owner_view": False,
            "section": "my_project",
            **services.telegram_context(request.user),
        },
    )


@login_required
@require_POST
def contract_sign(request, pk):
    """Заказчик возвращает подписанный экземпляр.

    Файл ложится рядом с договором и переводит его в «подписанные».
    Дальше он никуда не денется: это и есть то, ради чего договор
    вообще подписывают.
    """
    obj = _project_for(request.user)
    contract = get_object_or_404(Contract, pk=pk, project=obj)
    uploaded = request.FILES.get("signed_file")
    if not uploaded:
        messages.error(request, "Приложите файл с подписанным договором.")
        return redirect("cabinet:my_project")

    contract.signed_file = uploaded
    contract.status = Contract.Status.SIGNED
    contract.signed_at = timezone.now()
    contract.signed_by = request.user.full_name or str(request.user)
    contract.save(update_fields=["signed_file", "status", "signed_at", "signed_by"])

    services.post_message(
        obj,
        request.user,
        f"Подписанный договор «{contract}» загружен.",
        stage=contract.stage,
    )
    notify.safe(notify.contract_signed, contract)
    messages.success(request, "Договор подписан и сохранён. Спасибо.")
    return redirect("cabinet:my_project")


@login_required
@require_POST
def budget_decide(request, pk):
    """Согласовать или отклонить изменение сметы.

    Решение фиксируется с датой и именем — иначе разговор «мы же
    договаривались» опять становится словом против слова.
    """
    obj = _project_for(request.user)
    change = get_object_or_404(BudgetChange, pk=pk, project=obj)
    if not change.is_pending:
        messages.info(request, "Решение по этому изменению уже принято.")
        return redirect("cabinet:my_project")

    accepted = request.POST.get("decision") == "accept"
    change.decide(
        accepted,
        by=request.user.full_name or str(request.user),
        comment=request.POST.get("comment", ""),
    )

    services.post_message(
        obj,
        request.user,
        ("Согласовано: " if accepted else "Отклонено: ") + change.title,
        stage=change.stage,
    )
    notify.safe(notify.budget_decided, change)
    messages.success(
        request,
        "Изменение согласовано, сумма проекта обновлена."
        if accepted
        else "Изменение отклонено. Работаем в прежних рамках.",
    )
    return redirect("cabinet:my_project")


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
