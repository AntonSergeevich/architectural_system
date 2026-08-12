"""Кабинет Дарьи: воронка, заказчики, проекты, цены, договоры, счета."""

from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Count, Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.billing.models import Invoice
from apps.catalog.models import ComplexityFactor, PriceHistory, PricingSettings, ServiceModule
from apps.contracts.models import Contract, ContractClause, ContractTemplate
from apps.core import notify
from apps.core.models import SiteSettings
from apps.crm.models import Client, Lead
from apps.projects.models import (
    BudgetChange,
    Project,
    ProjectPayment,
    Stage,
    StageFile,
    StageTask,
    TaskPreset,
)

from . import services
from .forms import (
    AccessForm,
    BudgetChangeForm,
    ClientForm,
    ClientNotesForm,
    ContractUploadForm,
    MessageForm,
    PaymentForm,
    ProjectForm,
    PropertyForm,
    TaskForm,
)

owner_only = user_passes_test(lambda u: u.is_authenticated and u.is_owner)


@login_required
@owner_only
def leads(request):
    """Воронка.

    Просроченные касания идут первыми: заявка без сделанного следующего
    шага — это и есть «потерянная заявка».
    """
    qs = list(Lead.objects.select_related("client", "estate").order_by("next_action_at"))
    # Колонки готовим здесь, а не в шаблоне: словарь по ключу-переменной
    # шаблонный язык не умеет, и обход этого превращается в самодельные фильтры.
    columns = [
        (label, [lead for lead in qs if lead.status == status])
        for status, label in Lead.Status.choices
    ]
    return render(
        request,
        "cabinet/leads.html",
        {
            "section": "leads",
            "overdue": [lead for lead in qs if lead.is_overdue],
            "columns": columns,
            "leads": qs,
        },
    )


@login_required
@owner_only
def lead_detail(request, pk):
    lead = get_object_or_404(Lead.objects.select_related("client", "estate"), pk=pk)
    if request.method == "POST":
        lead.status = request.POST.get("status", lead.status)
        lead.next_action = request.POST.get("next_action", lead.next_action)
        when = request.POST.get("next_action_at")
        if when:
            lead.next_action_at = timezone.make_aware(
                timezone.datetime.fromisoformat(when), timezone.get_current_timezone()
            )
        lead.lost_reason = request.POST.get("lost_reason", "")
        lead.last_touch_at = timezone.now()
        lead.save()
        messages.success(request, "Заявка обновлена.")
        return redirect("cabinet:lead_detail", pk=pk)
    return render(
        request,
        "cabinet/lead_detail.html",
        {"lead": lead, "statuses": Lead.Status.choices, "section": "leads"},
    )


@login_required
@owner_only
def dashboard(request):
    """Первый экран кабинета: что требует Дарью сегодня.

    Не список всего подряд, а короткий ответ на вопрос «за что взяться».
    Список всего подряд человек всё равно не читает — он его пролистывает
    и закрывает.
    """
    leads_qs = list(Lead.objects.select_related("client").order_by("next_action_at"))
    projects_qs = list(
        Project.objects.select_related("client", "estate")
        .exclude(status=Project.Status.DONE)
        .prefetch_related("stages__tasks", "messages", "budget_changes")
    )

    waiting = []
    for project in projects_qs:
        unread = services.unread_count(project, request.user)
        stage = project.current_stage
        my_tasks = [
            task
            for st in project.stages.all()
            for task in st.tasks.all()
            if not task.is_done and task.who in {StageTask.Owner.OWNER, StageTask.Owner.BOTH}
        ]
        waiting.append(
            {
                "project": project,
                "stage": stage,
                "unread": unread,
                "tasks": my_tasks[:3],
                "tasks_total": len(my_tasks),
            }
        )

    site = SiteSettings.get()
    active = sum(1 for p in projects_qs if p.status == Project.Status.ACTIVE)
    return render(
        request,
        "cabinet/dashboard.html",
        {
            "section": "dashboard",
            "overdue": [lead for lead in leads_qs if lead.is_overdue],
            "new_leads": [lead for lead in leads_qs if lead.status == Lead.Status.NEW],
            "rows": waiting,
            "unsigned": Contract.objects.filter(
                status__in=[Contract.Status.SENT, Contract.Status.REVIEWED], signed_file=""
            ).select_related("client", "template")[:10],
            "wip_used": active,
            "wip_limit": site.wip_limit,
            "wip_exceeded": active > site.wip_limit,
            "is_owner_view": True,
            **services.telegram_context(request.user),
        },
    )


@login_required
@owner_only
def clients(request):
    """Заказчики. Отсюда заводится карточка и выдаётся доступ."""
    form = ClientForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        client = form.save()
        messages.success(request, f"Заказчик «{client.name}» заведён.")
        return redirect("cabinet:client_detail", pk=client.pk)

    qs = (
        Client.objects.select_related("user")
        .prefetch_related("projects", "properties")
        .order_by("-created_at")
    )
    return render(request, "cabinet/clients.html", {"clients": qs, "form": form, "section": "clients"})


@login_required
@owner_only
def client_detail(request, pk):
    client = get_object_or_404(
        Client.objects.select_related("user").prefetch_related("properties", "projects"), pk=pk
    )
    return render(
        request,
        "cabinet/client_detail.html",
        {
            "section": "clients",
            "client": client,
            "form": ClientForm(instance=client),
            "notes_form": ClientNotesForm(instance=client),
            "estate_form": PropertyForm(),
            "access_form": AccessForm(initial={"email": client.email, "full_name": client.name}),
            "project_form": ProjectForm(client=client),
            # Пароль показывается ровно один раз, сразу после выдачи:
            # в базе он хранится только хешем, и достать его потом нельзя.
            "issued_password": request.session.pop("issued_password", None),
        },
    )


@login_required
@owner_only
@require_POST
def client_edit(request, pk):
    client = get_object_or_404(Client, pk=pk)
    form = ClientForm(request.POST, instance=client)
    if form.is_valid():
        form.save()
        messages.success(request, "Карточка сохранена.")
    else:
        messages.error(request, "Проверьте поля карточки.")
    return redirect("cabinet:client_detail", pk=pk)


@login_required
@owner_only
@require_POST
def client_notes(request, pk):
    """Заметки — только для Дарьи, и сохраняются отдельно от карточки.

    Отдельно, потому что дописывают их на ходу, между звонком и выездом,
    и в этот момент не должно быть ни одного лишнего поля рядом.
    """
    client = get_object_or_404(Client, pk=pk)
    form = ClientNotesForm(request.POST, instance=client)
    if form.is_valid():
        form.save()
        messages.success(request, "Заметка сохранена.")
    return redirect(reverse("cabinet:client_detail", args=[pk]) + "#zametki")


@login_required
@owner_only
@require_POST
def client_estate(request, pk):
    """Объект заказчика: без него проект завести не на чем."""
    client = get_object_or_404(Client, pk=pk)
    form = PropertyForm(request.POST)
    if form.is_valid():
        estate = form.save(commit=False)
        estate.client = client
        estate.save()
        messages.success(request, "Объект добавлен.")
    else:
        messages.error(request, "Проверьте данные объекта.")
    return redirect("cabinet:client_detail", pk=pk)


@login_required
@owner_only
@require_POST
def client_access(request, pk):
    """Выдать заказчику доступ в кабинет.

    Логин — почта, пароль показывается один раз. Заказчиков единицы,
    и по опыту Дарьи доступ она диктует голосом или пересылает
    в мессенджер — значит, пароль должен быть произносимым.
    """
    client = get_object_or_404(Client, pk=pk)
    form = AccessForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Проверьте почту заказчика.")
        return redirect("cabinet:client_detail", pk=pk)

    user, password = form.save(client)

    # Готовое сообщение, а не три поля для переписывания. Дарья отправляет
    # доступ в мессенджер, и собирать текст руками — это лишняя минута
    # и шанс перепутать символ в пароле.
    login_url = request.build_absolute_uri(reverse("accounts:login"))
    name = (user.full_name or client.name).split(" ")[0]
    request.session["issued_password"] = {
        "email": user.email,
        "password": password,
        "url": login_url,
        "text": (
            f"{name}, здравствуйте! Открыла вам личный кабинет по проекту.\n\n"
            f"Вход: {login_url}\n"
            f"Логин: {user.email}\n"
            f"Пароль: {password}\n\n"
            "В кабинете видно, на каком этапе проект, что нужно от вас, "
            "договоры и вся переписка. Пароль можно поменять в любой момент — "
            "на странице входа есть «Забыли пароль?»."
        ),
    }
    return redirect("cabinet:client_detail", pk=pk)


@login_required
@owner_only
@require_POST
def client_project(request, pk):
    """Завести проект заказчику. Этапы раскладываются сами."""
    client = get_object_or_404(Client, pk=pk)
    form = ProjectForm(request.POST, client=client)
    if not form.is_valid():
        messages.error(request, "Проверьте поля проекта: нужен объект.")
        return redirect("cabinet:client_detail", pk=pk)

    project = form.save(commit=False)
    project.client = client
    project.save()
    created = services.create_stages(project)
    messages.success(request, f"Проект заведён, этапов разложено: {created}.")
    return redirect("cabinet:project_detail", pk=project.pk)


@login_required
@owner_only
def projects(request):
    """Канбан проектов по этапам."""
    site = SiteSettings.get()
    active = Project.objects.filter(status=Project.Status.ACTIVE).count()
    qs = (
        Project.objects.select_related("client", "estate")
        .prefetch_related("stages")
        .annotate(open_revisions=Count("stages__revisions", filter=Q(stages__revisions__status="new")))
    )
    return render(
        request,
        "cabinet/projects.html",
        {
            "section": "projects",
            "projects": qs,
            "wip_limit": site.wip_limit,
            "wip_used": active,
            "wip_exceeded": active > site.wip_limit,
        },
    )


@login_required
@owner_only
def project_detail(request, pk):
    """Рабочее место проекта: шкала этапов, задачи, деньги, договоры, чат.

    Всё на одном экране намеренно. Проект — это один объект внимания,
    и раскладывать его по пяти вкладкам значит заставить человека
    держать состояние в голове.
    """
    project = get_object_or_404(services.project_queryset(), pk=pk)
    services.mark_messages_read(project, request.user)

    stages = list(project.stages.order_by("number"))
    current = project.current_stage
    presets = TaskPreset.objects.filter(is_active=True).filter(
        Q(stage_number__isnull=True) | Q(stage_number=current.number if current else 0)
    )

    return render(
        request,
        "cabinet/project.html",
        {
            "section": "projects",
            "project": project,
            "stages": stages,
            "current": current,
            "presets": presets,
            "task_form": TaskForm(),
            "payment_form": PaymentForm(project=project),
            "budget_form": BudgetChangeForm(project=project),
            "contract_form": ContractUploadForm(project=project),
            "message_form": MessageForm(),
            "messages_list": project.messages.all(),
            "signed_contracts": [c for c in project.contracts.all() if c.is_signed],
            "open_contracts": [c for c in project.contracts.all() if not c.is_signed],
            "is_owner_view": True,
            **services.telegram_context(request.user),
        },
    )


# --- Действия внутри проекта ------------------------------------------------


def _project_or_404(pk):
    return get_object_or_404(services.project_queryset(), pk=pk)


def _tell_about_task(task):
    """О задаче сообщаем только тому, кому её поставили.

    Уведомление «Дарья поставила себе задачу» заказчику не нужно —
    это шум, из-за которого перестают читать и нужное.
    """
    if task.who in {StageTask.Owner.CLIENT, StageTask.Owner.BOTH}:
        notify.safe(notify.task_for_client, task)


@login_required
@owner_only
@require_POST
def task_add(request, pk):
    """Добавить задачу этапа — своими словами или готовой формулировкой."""
    project = _project_or_404(pk)
    stage = get_object_or_404(Stage, pk=request.POST.get("stage"), project=project)

    preset_id = request.POST.get("preset")
    if preset_id:
        preset = get_object_or_404(TaskPreset, pk=preset_id)
        task = StageTask.objects.create(stage=stage, title=preset.title, who=preset.who)
        _tell_about_task(task)
        messages.success(request, "Задача добавлена.")
        return redirect("cabinet:project_detail", pk=pk)

    form = TaskForm(request.POST)
    if form.is_valid():
        task = form.save(commit=False)
        task.stage = stage
        task.save()
        _tell_about_task(task)
        messages.success(request, "Задача добавлена.")
    else:
        messages.error(request, "Напишите, что нужно сделать.")
    return redirect("cabinet:project_detail", pk=pk)


@login_required
@require_POST
def task_toggle(request, pk):
    """Отметить задачу сделанной. Доступно обеим сторонам.

    Заказчик отмечает то, что должен он: «прислал фото розеток» —
    это его строка, и ждать, пока её закроет Дарья, значит опять
    завести переписку «а вы получили?».
    """
    project = _visible_project(request, pk)
    task = get_object_or_404(StageTask, pk=request.POST.get("task"), stage__project=project)

    if not request.user.is_owner and task.who == StageTask.Owner.OWNER:
        return JsonResponse({"ok": False, "error": "это задача Дарьи"}, status=403)

    task.toggle(not task.is_done)

    # Без JavaScript сюда приходит обычная форма — и ей нужен не JSON,
    # а страница обратно. Обещание «кабинет работает без JS» стоит
    # ровно столько, сколько таких мелочей учтено.
    if request.headers.get("X-Requested-With") != "XMLHttpRequest":
        target = (
            reverse("cabinet:project_detail", args=[project.pk])
            if request.user.is_owner
            else reverse("cabinet:my_project")
        )
        return redirect(f"{target}#stage-{task.stage_id}")

    return JsonResponse({"ok": True, "done": task.is_done, "progress": project.progress})


@login_required
@owner_only
@require_POST
def task_delete(request, pk):
    project = _project_or_404(pk)
    task = get_object_or_404(StageTask, pk=request.POST.get("task"), stage__project=project)
    task.delete()
    return redirect("cabinet:project_detail", pk=pk)


@login_required
@owner_only
@require_POST
def stage_update(request, pk):
    """Этап целиком: статус, заметка и файлы — одной кнопкой.

    Раньше здесь было две формы и две кнопки, «Сохранить» и «Приложить».
    Человек меняет статус, прикладывает файл и жмёт одну из них — вторая
    половина сделанного пропадает. Это не экономия клика, это потерянная
    работа.
    """
    project = _project_or_404(pk)
    stage = get_object_or_404(Stage, pk=request.POST.get("stage"), project=project)

    status = request.POST.get("status")
    changed_status = status in dict(Stage.Status.choices) and status != stage.status
    if status in dict(Stage.Status.choices):
        stage.status = status
        if status == Stage.Status.IN_PROGRESS and not stage.started_at:
            stage.started_at = timezone.localdate()
            stage.waiting_on = Stage.WaitingOn.OWNER
        if status == Stage.Status.REVIEW:
            stage.waiting_on = Stage.WaitingOn.CLIENT
        if status == Stage.Status.DONE:
            stage.finished_at = timezone.localdate()
            stage.waiting_on = Stage.WaitingOn.NOBODY
    if "note" in request.POST:
        stage.note = request.POST["note"]
    stage.save()

    uploaded = request.FILES.getlist("files")
    for item in uploaded:
        StageFile.objects.create(stage=stage, file=item, title=item.name[:200])

    if changed_status:
        notify.safe(notify.stage_changed, stage)

    parts = []
    if changed_status:
        parts.append(f"этап «{stage.title}» — {stage.get_status_display().lower()}")
    if uploaded:
        parts.append(f"файлов добавлено: {len(uploaded)}")
    messages.success(request, ("Сохранено: " + ", ".join(parts)) if parts else "Сохранено.")
    return redirect(f"{reverse('cabinet:project_detail', args=[pk])}#stage-{stage.pk}")


@login_required
@owner_only
@require_POST
def stage_file_delete(request, pk):
    """Убрать файл этапа.

    Не то же самое, что файл в переписке: там доказательная база и удалять
    нельзя, а здесь рабочие материалы — перепутанный файл должен убираться,
    а не оставаться висеть у заказчика.
    """
    project = _project_or_404(pk)
    item = get_object_or_404(StageFile, pk=request.POST.get("file"), stage__project=project)
    stage_id = item.stage_id
    item.file.delete(save=False)
    item.delete()
    messages.success(request, "Файл убран.")
    return redirect(f"{reverse('cabinet:project_detail', args=[pk])}#stage-{stage_id}")


@login_required
@owner_only
@require_POST
def payment_add(request, pk):
    project = _project_or_404(pk)
    form = PaymentForm(request.POST, project=project)
    if form.is_valid():
        payment = form.save(commit=False)
        payment.project = project
        payment.save()
        messages.success(request, "Оплата записана.")
    else:
        messages.error(request, "Проверьте сумму и дату оплаты.")
    return redirect("cabinet:project_detail", pk=pk)


@login_required
@owner_only
@require_POST
def payment_delete(request, pk):
    project = _project_or_404(pk)
    payment = get_object_or_404(ProjectPayment, pk=request.POST.get("payment"), project=project)
    payment.delete()
    messages.success(request, "Оплата удалена.")
    return redirect("cabinet:project_detail", pk=pk)


@login_required
@owner_only
@require_POST
def budget_add(request, pk):
    """Выход за рамки бюджета — с обоснованием, на согласование заказчику."""
    project = _project_or_404(pk)
    form = BudgetChangeForm(request.POST, project=project)
    if form.is_valid():
        change = form.save(commit=False)
        change.project = project
        change.save()
        notify.safe(notify.budget_change, change)
        messages.success(
            request, "Изменение отправлено заказчику. В сумму проекта оно войдёт после согласования."
        )
    else:
        messages.error(request, "Нужны и сумма, и обоснование.")
    return redirect("cabinet:project_detail", pk=pk)


@login_required
@owner_only
@require_POST
def contract_add(request, pk):
    """Договор для заказчика: файл, который он скачает и подпишет."""
    project = _project_or_404(pk)
    form = ContractUploadForm(request.POST, request.FILES, project=project)
    if not form.is_valid():
        messages.error(request, "Выберите шаблон договора.")
        return redirect("cabinet:project_detail", pk=pk)

    contract = Contract.objects.create(
        template=form.cleaned_data["template"],
        project=project,
        client=project.client,
        stage=form.cleaned_data.get("stage"),
        number=form.cleaned_data.get("number", ""),
        amount=form.cleaned_data.get("amount") or Decimal("0"),
        file=request.FILES.get("file"),
        status=Contract.Status.SENT,
        sent_at=timezone.now(),
    )
    notify.safe(notify.contract_sent, contract)
    messages.success(request, f"Договор «{contract}» отправлен заказчику в кабинет.")
    return redirect("cabinet:project_detail", pk=pk)


@login_required
@require_POST
def message_send(request, pk):
    """Сообщение в переписке. Общее действие для обеих сторон."""
    project = _visible_project(request, pk)
    files = request.FILES.getlist("files")
    form = MessageForm(request.POST, files_attached=bool(files))
    ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    if not form.is_valid():
        if ajax:
            return JsonResponse({"ok": False, "error": "Напишите сообщение или приложите файл."}, status=400)
        messages.error(request, "Напишите сообщение или приложите файл.")
    else:
        stage = None
        if request.POST.get("stage"):
            stage = Stage.objects.filter(pk=request.POST["stage"], project=project).first()
        message = services.post_message(project, request.user, form.cleaned_data["text"], files, stage)
        notify.safe(notify.new_message, message)
        if ajax:
            return JsonResponse(
                {"ok": True, "messages": [services.message_json(message, request.user.is_owner)]}
            )

    if request.user.is_owner:
        return redirect(reverse("cabinet:project_detail", args=[project.pk]) + "#chat")
    return redirect(reverse("cabinet:my_project") + "#chat")


@login_required
def messages_since(request, pk):
    """Что написали, пока страница была открыта.

    Заказчик и Дарья сидят в кабинете и ждут ответа — обновлять страницу
    ради этого не должен никто. Опрос простой, раз в несколько секунд:
    держать ради двух собеседников постоянное соединение — это отдельный
    процесс, который надо запускать, сторожить и перезапускать.
    """
    project = _visible_project(request, pk)
    after = request.GET.get("after")

    qs = project.messages.prefetch_related("files").order_by("created_at")
    if after and after.isdigit():
        qs = qs.filter(pk__gt=int(after))
    else:
        qs = qs.none()

    fresh = list(qs[:50])
    if fresh:
        services.mark_messages_read(project, request.user)

    return JsonResponse(
        {
            "ok": True,
            "messages": [services.message_json(m, request.user.is_owner) for m in fresh],
        }
    )


@login_required
@require_POST
def telegram_prefs(request):
    """Настройки уведомлений. Общие для обеих сторон.

    Отключение — такое же право, как подключение: бот, от которого
    нельзя отписаться, перестаёт быть помощником.
    """
    from apps.accounts.models import TelegramAccount

    account = TelegramAccount.for_user(request.user)

    if request.POST.get("unlink"):
        account.unlink()
        messages.success(request, "Telegram отключён. Всё то же самое видно в кабинете.")
    else:
        account.notify_stages = "notify_stages" in request.POST
        account.notify_tasks = "notify_tasks" in request.POST
        account.notify_messages = "notify_messages" in request.POST
        account.notify_money = "notify_money" in request.POST
        account.save(
            update_fields=["notify_stages", "notify_tasks", "notify_messages", "notify_money"]
        )
        messages.success(request, "Настройки уведомлений сохранены.")

    back = request.POST.get("back") or (
        reverse("cabinet:dashboard") if request.user.is_owner else reverse("cabinet:my_project")
    )
    return redirect(f"{back}#telegram")


def _visible_project(request, pk):
    """Проект, к которому у пользователя вообще есть доступ.

    Дарья видит любой, заказчик — только свой. Проверка одна на все
    общие действия: забыть её в одном обработчике означает открыть
    чужую переписку.
    """
    project = _project_or_404(pk)
    if request.user.is_owner:
        return project
    client = getattr(request.user, "client", None)
    if client is None or project.client_id != client.pk:
        raise Http404("Проект не найден")
    return project


@login_required
@owner_only
@require_POST
def move_stage(request, pk):
    """Перетаскивание карточки этапа. Здесь мышь есть всегда."""
    project = get_object_or_404(Project, pk=pk)
    stage = get_object_or_404(Stage, pk=request.POST.get("stage"), project=project)
    status = request.POST.get("status")
    if status not in dict(Stage.Status.choices):
        return JsonResponse({"ok": False, "error": "неизвестный статус"}, status=400)

    stage.status = status
    if status == Stage.Status.IN_PROGRESS and not stage.started_at:
        stage.started_at = timezone.localdate()
        stage.waiting_on = Stage.WaitingOn.OWNER
    if status == Stage.Status.REVIEW:
        stage.waiting_on = Stage.WaitingOn.CLIENT
    if status == Stage.Status.DONE:
        stage.finished_at = timezone.localdate()
        stage.waiting_on = Stage.WaitingOn.NOBODY
    stage.save()
    return JsonResponse({"ok": True, "progress": project.progress})


@login_required
@owner_only
def prices(request):
    """Правка прайса.

    Цены живут в базе, а не в вёрстке: поднять цены — значит поменять числа
    здесь, а не звать разработчика. Выставленные КП при этом не меняются,
    они хранят свои цифры.
    """
    modules = ServiceModule.objects.order_by("block", "order")
    pricing = PricingSettings.get()

    if request.method == "POST":
        # Правила расчёта — те же переключатели, что и цены: включить
        # коэффициент сложности через месяц должно быть одной галочкой,
        # а не задачей разработчику.
        pricing.complexity_enabled = "complexity_enabled" in request.POST
        pricing.small_area_enabled = "small_area_enabled" in request.POST
        pricing.show_grand_total = "show_grand_total" in request.POST
        for field in ("small_area_threshold", "small_area_price", "months_per_100_sqm"):
            raw = request.POST.get(field)
            if not raw:
                continue
            try:
                value = Decimal(raw.replace(",", ".").replace(" ", ""))
            except (ArithmeticError, ValueError):
                continue
            setattr(pricing, field, int(value) if field == "months_per_100_sqm" else value)
        pricing.save()

        changed = 0
        for module in modules:
            raw = request.POST.get(f"price_{module.pk}")
            if raw is None:
                continue
            try:
                new_price = Decimal(raw.replace(",", ".").replace(" ", ""))
            except (ArithmeticError, ValueError):
                continue
            if new_price != module.price:
                PriceHistory.objects.create(
                    module=module,
                    price=new_price,
                    unit=module.unit,
                    comment=request.POST.get("comment", ""),
                )
                module.price = new_price
                module.save(update_fields=["price", "updated_at"])
                changed += 1

            active = f"active_{module.pk}" in request.POST
            if active != module.is_active:
                module.is_active = active
                module.save(update_fields=["is_active", "updated_at"])
        messages.success(request, f"Сохранено. Изменено цен: {changed}.")
        return redirect("cabinet:prices")

    return render(
        request,
        "cabinet/prices.html",
        {
            "section": "prices",
            "modules": modules,
            "complexities": ComplexityFactor.objects.all(),
            "pricing": pricing,
        },
    )


@login_required
@owner_only
def contracts(request):
    return render(
        request,
        "cabinet/contracts.html",
        {
            "section": "contracts",
            "templates": ContractTemplate.objects.prefetch_related("clauses"),
            "issued": Contract.objects.select_related("client", "template")[:50],
        },
    )


@login_required
@owner_only
def contract_edit(request, pk):
    """Правка шаблона договора и расшифровок «на человеческом языке»."""
    template = get_object_or_404(ContractTemplate.objects.prefetch_related("clauses"), pk=pk)
    if request.method == "POST":
        template.intro = request.POST.get("intro", template.intro)
        template.outro = request.POST.get("outro", template.outro)
        template.version = request.POST.get("version", template.version)
        template.save()
        for clause in template.clauses.all():
            clause.text = request.POST.get(f"text_{clause.pk}", clause.text)
            clause.plain_text = request.POST.get(f"plain_{clause.pk}", clause.plain_text)
            clause.is_important = f"important_{clause.pk}" in request.POST
            clause.save(update_fields=["text", "plain_text", "is_important"])
        messages.success(request, "Договор сохранён.")
        return redirect("cabinet:contract_edit", pk=pk)

    return render(request, "cabinet/contract_edit.html", {"template": template, "section": "contracts"})


@login_required
@owner_only
def invoices(request):
    if request.method == "POST":
        invoice = get_object_or_404(Invoice, pk=request.POST.get("invoice"))
        action = request.POST.get("action")
        if action == "issue":
            invoice.status = Invoice.Status.ISSUED
            invoice.issued_at = timezone.now()
            invoice.save(update_fields=["status", "issued_at"])
        elif action == "paid":
            # Ручная отметка: самозанятая принимает переводы и без эквайринга,
            # и система обязана уметь это учесть.
            from apps.billing.models import Payment

            Payment.objects.create(
                invoice=invoice,
                provider=Payment.Provider.MANUAL,
                amount=invoice.left_to_pay,
                status=Payment.Status.SUCCEEDED,
            )
            invoice.refresh_status()
        messages.success(request, "Счёт обновлён.")
        return redirect("cabinet:invoices")

    return render(
        request,
        "cabinet/invoices.html",
        {
            "invoices": Invoice.objects.select_related("client", "project").prefetch_related("payments"),
            "section": "invoices",
        },
    )
