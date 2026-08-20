"""Действия кабинета, общие для обоих кабинетов.

Дарья и заказчик делают в проекте разное, но часть операций у них одна
и та же — переписка, отметки о прочтении, раскладка этапов. Держать их
в двух местах значит однажды получить две разные истории одного проекта.
"""

from decimal import Decimal

from django.conf import settings
from django.db.models import Q
from django.http import JsonResponse
from django.template.loader import render_to_string
from django.utils import timezone

from apps.core.models import STAGE_BLOCKS, StageNorm, group_by_block
from apps.projects.models import Message, MessageFile, Project, Stage

MAX_FILE_SIZE = 25 * 1024 * 1024  # 25 МБ: планировка в PDF влезает, видео — нет


def create_stages(project):
    """Разложить этапы по нормативам из «Как я работаю».

    Этапы не спрашиваются при заведении проекта: список известен заранее
    и одинаков, а форма на восемь строк — верный способ завести проект
    вообще без этапов.
    """
    if project.stages.exists():
        return 0

    norms = list(StageNorm.objects.order_by("number"))
    if not norms:
        return 0

    Stage.objects.bulk_create(
        [
            Stage(
                project=project,
                number=norm.number,
                title=norm.title,
                planned_days=norm.working_days,
            )
            for norm in norms
        ]
    )
    return len(norms)


def post_message(project, user, text, files=(), stage=None):
    """Записать сообщение в переписку по проекту.

    Сообщения не удаляются, а поправить их можно только минуту после
    отправки и только автору: переписка нужна как доказательная база,
    а переписанная задним числом ничего не доказывает.
    """
    message = Message.objects.create(
        project=project,
        author=user,
        author_name=getattr(user, "full_name", "") or str(user),
        author_is_owner=bool(getattr(user, "is_owner", False)),
        stage=stage,
        text=(text or "").strip(),
    )

    for uploaded in files:
        if uploaded.size > MAX_FILE_SIZE:
            continue
        MessageFile.objects.create(
            message=message,
            file=uploaded,
            name=uploaded.name[:250],
            size=uploaded.size,
        )
    return message


def chat_url(user, project):
    """Куда вернуть человека после действия в переписке."""
    from django.urls import reverse

    if getattr(user, "is_owner", False):
        return reverse("cabinet:project_detail", args=[project.pk]) + "#chat"
    return reverse("cabinet:my_project") + "#chat"


def message_json(message, viewer):
    """Сообщение для дорисовки в переписке без перезагрузки страницы.

    `mine` и `own` считаются на сервере, а не в браузере. «Своё справа»
    зависит от того, кто смотрит, и решать это в двух местах — верный
    способ однажды показать заказчику его собственные сообщения слева.
    А `own` — это ещё и право на правку: «моё» и «с моей стороны» здесь
    разные вещи, потому что со стороны заказчика бывает двое.
    """
    viewer_is_owner = bool(getattr(viewer, "is_owner", False))
    return {
        "id": message.pk,
        "author": message.author_name,
        "mine": message.author_is_owner == viewer_is_owner,
        "own": message.author_id == getattr(viewer, "pk", None),
        "text": message.text,
        "at": timezone.localtime(message.created_at).strftime("%d.%m.%Y %H:%M"),
        "edited": bool(message.edited_at),
        "decision": message.is_decision,
        # Секунды до конца окна правки: кнопка должна исчезнуть сама,
        # а не оставаться до перезагрузки и жаловаться на отказ сервера.
        "edit_left": max(int((message.edit_deadline - timezone.now()).total_seconds()), 0),
        "stage": message.stage.title if message.stage else "",
        "files": [
            {
                "url": file.file.url,
                "name": file.name,
                "size": file.human_size,
                "image": file.is_image,
            }
            for file in message.files.all()
        ],
    }


def mark_messages_read(project, user):
    """Отметить прочитанным то, что написала другая сторона."""
    is_owner = bool(getattr(user, "is_owner", False))
    (
        Message.objects.filter(project=project, read_at__isnull=True)
        .filter(~Q(author_is_owner=is_owner))
        .update(read_at=timezone.now())
    )


def unread_count(project, user):
    is_owner = bool(getattr(user, "is_owner", False))
    return (
        Message.objects.filter(project=project, read_at__isnull=True)
        .filter(~Q(author_is_owner=is_owner))
        .count()
    )


def telegram_context(user):
    """Данные панели «Уведомления».

    Код привязки заводится заранее, до всякого нажатия: ссылка должна
    существовать в момент, когда человек решил её нажать, а не после
    отдельного «сгенерировать код».
    """
    from apps.accounts.models import TelegramAccount

    account = TelegramAccount.for_user(user)
    bot = getattr(settings, "TELEGRAM_BOT_USERNAME", "")
    return {
        "telegram": account,
        "telegram_bot": f"@{bot}" if bot else "",
        "telegram_link": (
            f"https://t.me/{bot}?start={account.link_code}"
            if bot and settings.TELEGRAM_BOT_TOKEN and not account.is_linked
            else ""
        ),
    }


def project_queryset():
    """Проект со всем, что показывает кабинет, — одним заходом в базу."""
    return Project.objects.select_related("client", "estate").prefetch_related(
        "stages__tasks",
        "stages__files__room",
        "rooms",
        "stages__revisions",
        "stages__contracts__template",
        "stages__payments",
        "payments",
        "budget_changes",
        "contracts__template",
        "messages__files",
    )


def is_ajax(request):
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


def stage_payload(request, project, stage, message="", error=""):
    """Перерисованная карточка этапа и шкала — ответ на действие в кабинете.

    Кусок разметки собирает сервер, а не браузер: шаблон один, и второй
    его копии на JavaScript не появляется. Иначе две версии одного этапа
    рано или поздно разойдутся, и стороны увидят разное.

    Шкала возвращается вместе с карточкой: смена статуса меняет текущий
    этап, а договор — метку на точке. Обновить одно и забыть другое
    значит показать человеку рассинхронизированный экран.
    """
    from apps.projects.models import TaskPreset

    stages = stage_shares(project.stages.order_by("number"))
    fresh = next((s for s in stages if s.pk == stage.pk), stage)
    current = project.current_stage

    context = {
        "project": project,
        "stages": stages,
        "blocks": stage_blocks(stages),
        "stage": fresh,
        "current": current,
        "is_owner_view": bool(getattr(request.user, "is_owner", False)),
        "presets": TaskPreset.for_stage(fresh),
    }
    return {
        "ok": not error,
        "error": error,
        "message": message,
        "stage_id": f"stage-{fresh.pk}",
        "stage": render_to_string("cabinet/_stage.html", context, request=request),
        "rail": render_to_string("cabinet/_rail.html", context, request=request),
        "progress": project.progress,
    }


def stage_response(request, project, stage, message="", error=""):
    return JsonResponse(stage_payload(request, project, stage, message, error))


# Три блока работы — 30 / 40 / 30. Разбивка лежит в core вместе
# с нормативом этапов: она же показывается на публичной странице
# «Как я работаю», и двух копий у неё быть не должно.
def stage_blocks(stages):
    """Блоки для шкалы: подпись, доля, сколько этапов накрывает скобка
    и в каком блок состоянии."""
    rows = group_by_block(stages)
    for row in rows:
        row["span"] = len(row["stages"])
        # Блок пройден, когда пройдены все его этапы; идёт — если хотя бы
        # один в работе. Это то же, что человек видит по точкам, только
        # одним словом.
        row["is_done"] = all(s.status == "done" for s in row["stages"])
        row["is_current"] = not row["is_done"] and any(s.status != "waiting" for s in row["stages"])
    return rows


def stage_shares(stages):
    """Сколько времени занимает каждый этап — в долях от всего срока.

    «Обмеры» и «рабочая документация» стоят на шкале одинаковыми точками,
    хотя первый занимает день, а второй — месяц. Отсюда и берётся ощущение
    «мы застряли»: заказчик видит восемь равных шагов и считает, что после
    третьего должно пройти три восьмых времени. Доля возвращает шкале
    честный масштаб, не ломая её вида.

    На саму шкалу доля этапа больше не выводится — там стоят блоки. Она
    осталась внутри карточки этапа: там это ответ на вопрос «а это надолго»,
    заданный про один конкретный этап, а не обещание всему проекту.
    """
    stages = list(stages)
    total = sum(stage.planned_days for stage in stages) or 1
    blocks = {
        number: (title, share)
        for title, share, numbers in STAGE_BLOCKS
        for number in numbers
    }
    for stage in stages:
        stage.share = round(stage.planned_days * 100 / total)
        stage.block, stage.block_share = blocks.get(
            stage.number, (STAGE_BLOCKS[-1][0], STAGE_BLOCKS[-1][1])
        )
        # Договор и деньги этапа — рядом с самим этапом, а не в общем
        # списке где-то сбоку: вопрос «за что я плачу» задаётся именно
        # в тот момент, когда смотришь, что на этапе делается.
        stage.waiting_contract = [c for c in stage.contracts.all() if not c.is_signed]
        stage.paid = sum((p.amount for p in stage.payments.all()), Decimal("0"))
        stage.file_groups = _by_room(stage.files.all())
    return stages


def _by_room(files):
    """Файлы этапа, разложенные по помещениям.

    На одном этапе подбираются обои в спальню и плитка в санузел. В общей
    куче миниатюр через месяц не разобрать, где что, а работа почти всегда
    идёт сразу по нескольким помещениям — Дарья перескакивает между ними
    по ходу дела.

    Без помещения файлы идут первыми: это «про проект целиком», и прятать
    их в конец за комнатами неправильно.
    """
    groups = {}
    for item in files:
        groups.setdefault(item.room, []).append(item)

    ordered = []
    if None in groups:
        ordered.append((None, groups.pop(None)))
    ordered += sorted(groups.items(), key=lambda pair: (pair[0].order, pair[0].title))
    return ordered
