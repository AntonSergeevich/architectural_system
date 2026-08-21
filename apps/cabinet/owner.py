"""Кабинет Дарьи: воронка, заказчики, проекты, цены, договоры, счета."""

from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Count, ProtectedError, Q
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
    Message,
    Room,
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
    ServiceForm,
    ProjectForm,
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
    qs = list(
        Lead.objects.real().select_related("client", "estate").order_by("next_action_at")
    )
    # Колонки готовим здесь, а не в шаблоне: словарь по ключу-переменной
    # шаблонный язык не умеет, и обход этого превращается в самодельные фильтры.
    columns = [
        {
            "status": status,
            "label": label,
            "items": [lead for lead in qs if lead.status == status],
        }
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
            # Спам стоит внизу отдельным списком, а не исчезает молча:
            # молчаливое удаление однажды съест живую заявку, и узнать
            # об этом будет неоткуда.
            "spam": list(
                Lead.objects.spam().select_related("client").order_by("-created_at")[:50]
            ),
        },
    )


@login_required
@owner_only
@require_POST
def lead_move(request, pk):
    """Перенести заявку в другой столбец воронки.

    Перетаскивание вместо выпадающего списка не про красоту. Воронку
    разбирают пачкой — пять заявок подряд, — и каждый переход внутрь
    карточки ради одного поля стоит трёх нажатий и потери места в списке.
    Перенос рукой делает то же самое одним движением.

    Дата следующего шага при этом не трогается: она про «когда», а столбец
    про «где», и молча сдвигать срок из-за переноса нельзя.
    """
    lead = get_object_or_404(Lead.objects.select_related("client"), pk=pk)
    status = request.POST.get("status", "")
    if status not in dict(Lead.Status.choices):
        return JsonResponse({"ok": False, "error": "Неизвестный столбец"}, status=400)

    lead.status = status
    lead.last_touch_at = timezone.now()
    lead.save(update_fields=["status", "last_touch_at"])

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({"ok": True, "status": status, "title": lead.get_status_display()})
    messages.success(request, f"«{lead.client.name}» — {lead.get_status_display().lower()}.")
    return redirect("cabinet:leads")


@login_required
@owner_only
@require_POST
def lead_delete(request, pk):
    """Удалить заявку.

    Здесь именно удаление, а не архив, как у заказчика: у рассылки нет
    истории, которую можно потерять. Вместе с заявкой уходит и карточка
    заказчика, если она была заведена этой же заявкой и больше ни с чем
    не связана — иначе спам оседает в списке заказчиков, и там его уже
    никто не разбирает.
    """
    lead = get_object_or_404(Lead.objects.select_related("client"), pk=pk)
    client = lead.client
    lead.delete()

    empty = (
        not client.leads.exists()
        and not client.projects.exists()
        and not client.quotes.exists()
        and client.user_id is None
    )
    if empty:
        client.delete()
        messages.success(request, "Заявка и карточка удалены.")
    else:
        messages.success(request, "Заявка удалена.")
    return redirect("cabinet:leads")


@login_required
@owner_only
@require_POST
def lead_spam(request, pk):
    """Пометить заявку спамом или вернуть её в воронку.

    Система ошибается в обе стороны, и обе поправимы одним нажатием —
    поэтому решение и остаётся за человеком.
    """
    lead = get_object_or_404(Lead, pk=pk)
    lead.is_spam = request.POST.get("restore") != "1"
    if not lead.is_spam:
        lead.spam_reason = ""
    lead.save(update_fields=["is_spam", "spam_reason"])
    if lead.is_spam:
        messages.success(request, "Заявка убрана в спам.")
        return redirect("cabinet:leads")
    messages.success(request, "Заявка вернулась в воронку.")
    return redirect("cabinet:lead_detail", pk=lead.pk)


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
    leads_qs = list(Lead.objects.real().select_related("client").order_by("next_action_at"))
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
    return render(
        request,
        "cabinet/clients.html",
        {
            "clients": [c for c in qs if not c.is_archived],
            "archived": [c for c in qs if c.is_archived],
            "form": form,
            "section": "clients",
        },
    )


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
def client_archive(request, pk):
    """Убрать карточку в архив — или вернуть обратно.

    Настоящего удаления здесь нет намеренно. За карточкой стоят проекты,
    договоры, переписка и оплаты: это доказательная база, и стереть её
    одним нажатием нельзя. Месяц карточка лежит в архиве целиком
    и возвращается одной кнопкой.

    Подтверждение — именем заказчика. Не «вы уверены?», на которое жмут
    не глядя, а действие, которое невозможно совершить случайно: чтобы
    напечатать имя, надо посмотреть, чьё оно.
    """
    client = get_object_or_404(Client, pk=pk)

    if request.POST.get("restore"):
        client.restore()
        messages.success(request, f"Заказчик «{client.name}» вернулся из архива.")
        return redirect("cabinet:client_detail", pk=pk)

    typed = (request.POST.get("confirm") or "").strip().casefold()
    if typed != client.name.strip().casefold():
        messages.error(request, "Имя не совпало — карточка осталась на месте.")
        return redirect("cabinet:client_detail", pk=pk)

    client.archive()
    messages.success(
        request,
        f"«{client.name}» в архиве. Вернуть можно в течение {Client.ARCHIVE_DAYS} дней.",
    )
    return redirect("cabinet:clients")


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

    partner = bool(request.POST.get("partner"))
    user, password = form.save(client, partner=partner)

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
    """Завести проект заказчику. Объект и этапы появляются вместе с ним.

    Объект создаётся здесь же, если его вписали руками: раньше это был
    отдельный шаг, и на новом заказчике он превращался в тупик — список
    объектов пуст, а форма нового пряталась ниже кнопки.
    """
    client = get_object_or_404(Client, pk=pk)
    form = ProjectForm(request.POST, client=client)
    if not form.is_valid():
        # Говорим, что именно не так: «проверьте поля» без указания
        # поля заставляет угадывать.
        problems = "; ".join(
            str(error) for errors in form.errors.values() for error in errors
        )
        messages.error(request, problems or "Проверьте поля проекта.")
        return redirect("cabinet:client_detail", pk=pk)

    project = form.save()
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

    stages = services.stage_shares(project.stages.order_by("number"))
    current = project.current_stage
    presets = TaskPreset.for_stage(current) if current else TaskPreset.objects.none()

    return render(
        request,
        "cabinet/project.html",
        {
            "section": "projects",
            "project": project,
            "stages": stages,
            "blocks": services.stage_blocks(stages),
            "current": current,
            "presets": presets,
            "task_form": TaskForm(),
            "payment_form": PaymentForm(project=project),
            "budget_form": BudgetChangeForm(project=project),
            "contract_form": ContractUploadForm(project=project),
            "message_form": MessageForm(),
            "messages_list": project.messages.all(),
            # Решения — то, о чём договорились. Отдельным списком наверху
            # переписки: в длинной ленте договорённость тонет между
            # «спасибо» и фотографиями, а искать её приходится через полгода.
            "decisions": [m for m in project.messages.all() if m.is_decision],
            "signed_contracts": [c for c in project.contracts.all() if c.is_signed],
            # Договоры этапов живут на самих этапах: там их и ищут. В боковой
            # панели остаётся то, что ни к какому этапу не привязано.
            "open_contracts": [
                c for c in project.contracts.all() if not c.is_signed and c.stage_id is None
            ],
            "stage_contracts": [
                c for c in project.contracts.all() if not c.is_signed and c.stage_id
            ],
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


def _room_from(request, project):
    """Помещение из формы: выбранное из списка или названное на ходу.

    Заранее список не спросить: состав помещений выясняется на обмере,
    а половина проектов частичные — две комнаты из пяти. Поэтому новая
    комната заводится тем же действием, что и загрузка файла в неё.
    """
    typed = (request.POST.get("room_new") or "").strip()
    if typed:
        room, _ = Room.objects.get_or_create(
            project=project, title=typed[:100], defaults={"order": project.rooms.count() + 1}
        )
        return room

    chosen = request.POST.get("room")
    if chosen and chosen.isdigit():
        return project.rooms.filter(pk=int(chosen)).first()
    return None


def _stage_back(request, project, stage, message="", error=""):
    """Ответ на действие внутри этапа.

    С JavaScript возвращается перерисованная карточка — страница не
    перезагружается и не прыгает к началу. Без него всё работает по-старому,
    обычной отправкой формы: кабинетом пользуются с телефона на объекте,
    где связь рвётся, и терять там работоспособность нельзя.
    """
    if services.is_ajax(request):
        return services.stage_response(request, project, stage, message, error)
    if error:
        messages.error(request, error)
    elif message:
        messages.success(request, message)
    return redirect(f"{reverse('cabinet:project_detail', args=[project.pk])}#stage-{stage.pk}")


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
        return _stage_back(request, project, stage, "Задача добавлена.")

    form = TaskForm(request.POST)
    if not form.is_valid():
        return _stage_back(request, project, stage, error="Напишите, что нужно сделать.")

    task = form.save(commit=False)
    task.stage = stage
    task.save()
    _tell_about_task(task)
    return _stage_back(request, project, stage, "Задача добавлена.")


@login_required
@owner_only
@require_POST
def task_edit(request, pk):
    """Поправить задачу: формулировку, исполнителя, срок.

    Задача — живая строка, а не запись в журнале: «прислать фото розеток»
    превращается в «прислать фото розеток и вывода под бра», и заводить
    ради этого вторую строку значит копить мусор.
    """
    project = _project_or_404(pk)
    task = get_object_or_404(StageTask, pk=request.POST.get("task"), stage__project=project)

    form = TaskForm(request.POST, instance=task)
    if not form.is_valid():
        return _stage_back(request, project, task.stage, error="Напишите, что нужно сделать.")

    form.save()
    return _stage_back(request, project, task.stage, "Задача поправлена.")


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
def preset_add(request, pk):
    """Своя заготовка задачи.

    Заготовки — это то, что Дарья печатает по десять раз за проект.
    Список из коробки закрывает половину случаев, вторую половину она
    должна дописывать сама, не заходя в админку.
    """
    project = _project_or_404(pk)
    stage = get_object_or_404(Stage, pk=request.POST.get("stage"), project=project)

    title = " ".join((request.POST.get("title") or "").split())
    if not title:
        return _stage_back(request, project, stage, error="Напишите, что это за задача.")

    TaskPreset.objects.create(
        title=title[:250],
        who=request.POST.get("who") or StageTask.Owner.OWNER,
        stage_number=stage.number,
        # Проектная заготовка не должна светить в чужих проектах:
        # «согласовать снос перегородки с УК» нужна ровно здесь.
        project=project if request.POST.get("scope") == "project" else None,
    )
    return _stage_back(request, project, stage, "Заготовка добавлена.")


@login_required
@owner_only
@require_POST
def preset_edit(request, pk):
    """Поправить заготовку или убрать её.

    Убирать — обязательно: половиной готовых формулировок Дарья
    не пользуется, а список, в котором лишнее нельзя вычеркнуть,
    перестают читать целиком.
    """
    project = _project_or_404(pk)
    stage = get_object_or_404(Stage, pk=request.POST.get("stage"), project=project)
    preset = get_object_or_404(TaskPreset, pk=request.POST.get("preset"))

    if request.POST.get("remove"):
        # Универсальную заготовку прячем, а не удаляем: она общая, и её
        # можно вернуть галочкой в админке. Проектную удаляем совсем —
        # она заводилась под один проект и больше нигде не нужна.
        if preset.project_id:
            preset.delete()
        else:
            preset.is_active = False
            preset.save(update_fields=["is_active"])
        return _stage_back(request, project, stage, "Заготовка убрана.")

    title = " ".join((request.POST.get("title") or "").split())
    if not title:
        return _stage_back(request, project, stage, error="Напишите, что это за задача.")

    preset.title = title[:250]
    preset.who = request.POST.get("who") or preset.who
    preset.project = project if request.POST.get("scope") == "project" else None
    preset.save(update_fields=["title", "who", "project"])
    return _stage_back(request, project, stage, "Заготовка поправлена.")


@login_required
@owner_only
@require_POST
def task_delete(request, pk):
    project = _project_or_404(pk)
    task = get_object_or_404(StageTask, pk=request.POST.get("task"), stage__project=project)
    stage = task.stage
    task.delete()
    return _stage_back(request, project, stage, "Задача убрана.")


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

    room = _room_from(request, project)
    caption = (request.POST.get("caption") or "").strip()

    uploaded = request.FILES.getlist("files")
    for item in uploaded:
        # Подпись одна на всю партию: Дарья выкладывает не «файл», а мысль —
        # «обои в гостиную, вот три варианта». Разбирать их по одному потом
        # можно, но начинать с этого значит не выложить ничего.
        StageFile.objects.create(stage=stage, file=item, title=caption[:200], room=room)

    if changed_status:
        notify.safe(notify.stage_changed, stage)

    parts = []
    if changed_status:
        parts.append(f"этап «{stage.title}» — {stage.get_status_display().lower()}")
    if uploaded:
        parts.append(f"файлов добавлено: {len(uploaded)}")
    return _stage_back(
        request, project, stage, ("Сохранено: " + ", ".join(parts)) if parts else "Сохранено."
    )


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
    stage = item.stage
    item.file.delete(save=False)
    item.delete()
    return _stage_back(request, project, stage, "Файл убран.")


@login_required
@owner_only
@require_POST
def stage_file_edit(request, pk):
    """Подпись и помещение конкретного файла.

    Подпись — не украшение: через полгода «438.JPG» не говорит ничего,
    а «обои Loymina в гостиную» говорит всё. Правится на месте, потому
    что подписывают файлы уже после загрузки, когда смотрят на них.
    """
    project = _project_or_404(pk)
    item = get_object_or_404(StageFile, pk=request.POST.get("file"), stage__project=project)

    item.title = (request.POST.get("title") or "").strip()[:200]
    room = _room_from(request, project)
    if room or request.POST.get("room") == "":
        item.room = room
    item.save(update_fields=["title", "room"])
    return _stage_back(request, project, item.stage, "Подпись сохранена.")


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
                {"ok": True, "messages": [services.message_json(message, request.user)]}
            )

    if request.user.is_owner:
        return redirect(reverse("cabinet:project_detail", args=[project.pk]) + "#chat")
    return redirect(reverse("cabinet:my_project") + "#chat")


@login_required
@require_POST
def message_edit(request, pk):
    """Поправить своё сообщение — минуту после отправки.

    Единственный честный случай — «отправил не ту цифру». Всё, что позже,
    это уже переписывание истории: переписка нужна как доказательная база,
    и правка задним числом обесценивает её целиком. Поэтому окно короткое,
    правка помечается, а время отправки остаётся прежним.

    Файлы правка не трогает: иначе «поправлю опечатку» превращается
    в способ убрать документ.
    """
    project = _visible_project(request, pk)
    message = get_object_or_404(Message, pk=request.POST.get("message"), project=project)

    if not message.can_edit(request.user):
        error = "Поправить можно только своё сообщение и только минуту после отправки."
        if services.is_ajax(request):
            return JsonResponse({"ok": False, "error": error}, status=403)
        messages.error(request, error)
        return redirect(services.chat_url(request.user, project))

    text = (request.POST.get("text") or "").strip()
    if not text and not message.files.exists():
        error = "Пустое сообщение не сохранить. Если оно лишнее — так и напишите."
        if services.is_ajax(request):
            return JsonResponse({"ok": False, "error": error}, status=400)
        messages.error(request, error)
        return redirect(services.chat_url(request.user, project))

    message.text = text
    message.edited_at = timezone.now()
    message.save(update_fields=["text", "edited_at"])

    if services.is_ajax(request):
        return JsonResponse(
            {"ok": True, "message": services.message_json(message, request.user)}
        )
    return redirect(services.chat_url(request.user, project))


@login_required
@require_POST
def message_decision(request, pk):
    """Пометить сообщение решением — или снять метку.

    Договорённости тонут в переписке между «спасибо» и фотографиями,
    а искать их приходится через полгода. Помеченные собираются отдельным
    списком наверху — это дешевле второго чата: два места для разговора
    значат два места, где надо искать.

    Метку ставит любая сторона: решение — это то, о чём договорились,
    и подтвердить это может каждый участник.
    """
    project = _visible_project(request, pk)
    message = get_object_or_404(Message, pk=request.POST.get("message"), project=project)

    message.is_decision = not message.is_decision
    message.save(update_fields=["is_decision"])

    if services.is_ajax(request):
        return JsonResponse(
            {"ok": True, "message": services.message_json(message, request.user)}
        )
    return redirect(services.chat_url(request.user, project))


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
            "messages": [services.message_json(m, request.user) for m in fresh],
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
    # Со стороны заказчика бывает двое: сам заказчик и второй аккаунт пары.
    # Проект у них один, и проверка обязана знать про обоих.
    client = getattr(request.user, "client", None) or getattr(
        request.user, "client_as_partner", None
    )
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
            "service_form": ServiceForm(),
        },
    )


@login_required
@owner_only
@require_POST
def price_add(request):
    """Завести свою услугу.

    Отдельным адресом, а не внутри общей формы цен: там форма правит
    десятки чисел разом, и подмешивать к ней создание новой строки
    значит однажды создать услугу, нажав «сохранить» после правки цен.
    """
    form = ServiceForm(request.POST)
    if not form.is_valid():
        problems = "; ".join(str(e) for errors in form.errors.values() for e in errors)
        messages.error(request, problems or "Проверьте поля услуги.")
        return redirect("cabinet:prices")

    module = form.save()
    messages.success(
        request,
        f"Услуга «{module.title}» заведена. Она уже на сайте — "
        "снимите галочку «На сайте», если показывать пока рано.",
    )
    return redirect("cabinet:prices")


@login_required
@owner_only
def service_edit(request, pk):
    """Правка услуги целиком: название, описание, единица, срок.

    Отдельной страницей, а не строкой в общей таблице: там правятся
    цены разом, и вкладывать форму в форму нельзя — браузер такую
    разметку молча ломает.
    """
    module = get_object_or_404(ServiceModule, pk=pk)

    if request.method == "POST":
        if request.POST.get("remove"):
            return _service_remove(request, module)

        form = ServiceForm(request.POST, instance=module)
        if form.is_valid():
            form.save()
            messages.success(request, f"Услуга «{module.title}» сохранена.")
            return redirect("cabinet:prices")
        messages.error(request, "Проверьте поля услуги.")
    else:
        form = ServiceForm(instance=module)

    return render(
        request,
        "cabinet/service_edit.html",
        {"section": "prices", "module": module, "form": form},
    )


def _service_remove(request, module):
    """Удалить услугу — если она никуда не вросла.

    Услуга может стоять в уже выставленном КП, а КП хранит то, что видел
    заказчик. Удалять её оттуда задним числом нельзя: пропадёт строка
    из документа, который человек читал и на который согласился.
    """
    title = module.title
    try:
        module.delete()
    except ProtectedError:
        messages.error(
            request,
            f"«{title}» стоит в уже выставленных предложениях, удалить нельзя: "
            "иначе из них пропадёт строка, которую заказчик видел. "
            "Снимите галочку «На сайте» — услуга исчезнет из конструктора "
            "и прайса, а старые документы останутся целыми.",
        )
        return redirect("cabinet:service_edit", pk=module.pk)

    messages.success(request, f"Услуга «{title}» удалена.")
    return redirect("cabinet:prices")


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
    """Правка шаблона договора: тексты, расшифровки и сами пункты.

    Пункт можно переименовать, перенумеровать, добавить и убрать.
    Раньше правились только тексты, и это упиралось в живой случай:
    юрист говорит «назовите пункт иначе» — а назвать иначе нельзя.
    """
    template = get_object_or_404(ContractTemplate.objects.prefetch_related("clauses"), pk=pk)
    if request.method == "POST":
        template.intro = request.POST.get("intro", template.intro)
        template.outro = request.POST.get("outro", template.outro)
        template.version = request.POST.get("version", template.version)
        template.save()

        removed = 0
        for clause in template.clauses.all():
            if f"remove_{clause.pk}" in request.POST:
                clause.delete()
                removed += 1
                continue
            clause.number = request.POST.get(f"number_{clause.pk}", clause.number).strip()
            clause.title = request.POST.get(f"title_{clause.pk}", clause.title).strip()
            clause.text = request.POST.get(f"text_{clause.pk}", clause.text)
            clause.plain_text = request.POST.get(f"plain_{clause.pk}", clause.plain_text)
            clause.is_important = f"important_{clause.pk}" in request.POST
            clause.save()

        # Новый пункт добавляется этой же формой: отдельная страница ради
        # трёх полей — это лишний переход посреди работы с текстом.
        new_text = (request.POST.get("new_text") or "").strip()
        if new_text:
            last = template.clauses.order_by("-order").first()
            ContractClause.objects.create(
                template=template,
                number=(request.POST.get("new_number") or "").strip() or "—",
                title=(request.POST.get("new_title") or "").strip(),
                text=new_text,
                plain_text=(request.POST.get("new_plain") or "").strip(),
                is_important="new_important" in request.POST,
                order=(last.order + 10) if last else 100,
            )

        note = "Договор сохранён."
        if removed:
            note += f" Убрано пунктов: {removed}."
        messages.success(request, note)
        return redirect("cabinet:contract_edit", pk=pk)

    return render(request, "cabinet/contract_edit.html", {"template": template, "section": "contracts"})


@login_required
@owner_only
def contract_print(request, pk):
    """Договор одним листом — для печати и для юриста.

    Своего генератора PDF здесь нет намеренно: любой браузер умеет
    «Сохранить как PDF» из окна печати, и это тот же файл, только без
    лишней библиотеки в проекте и без второй вёрстки, которая
    разъезжается с первой.
    """
    template = get_object_or_404(ContractTemplate.objects.prefetch_related("clauses"), pk=pk)
    return render(
        request,
        "cabinet/contract_print.html",
        {"template": template, "site": SiteSettings.get()},
    )


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
