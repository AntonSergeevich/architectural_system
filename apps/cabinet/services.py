"""Действия кабинета, общие для обоих кабинетов.

Дарья и заказчик делают в проекте разное, но часть операций у них одна
и та же — переписка, отметки о прочтении, раскладка этапов. Держать их
в двух местах значит однажды получить две разные истории одного проекта.
"""

from django.db.models import Q
from django.utils import timezone

from apps.core.models import StageNorm
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

    Сообщения не редактируются и не удаляются: переписка нужна как
    доказательная база, а редактируемая переписка ничего не доказывает.
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


def project_queryset():
    """Проект со всем, что показывает кабинет, — одним заходом в базу."""
    return Project.objects.select_related("client", "estate").prefetch_related(
        "stages__tasks",
        "stages__files",
        "stages__revisions",
        "payments",
        "budget_changes",
        "contracts__template",
        "messages__files",
    )
