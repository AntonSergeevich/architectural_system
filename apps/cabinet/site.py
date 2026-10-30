"""Раздел «Сайт»: всё, что видно на сайте, правится отсюда, а не в админке.

Дарья сказала прямо: в админке она чувствует себя программистом, и на
каждую правку уходят силы сверх самой правки. Поэтому здесь те же данные,
что и в админке, но на языке сайта: заголовки полей — те, что видит
посетитель, порядок — тот, в каком он читает.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils import timezone

from apps.core.context_processors import is_new_year, season_of
from apps.core.models import SiteSettings

from .owner import owner_only

SEASON_NAMES = {
    "autumn": "осень", "winter": "зима", "spring": "весна", "summer": "лето",
}

# Что именно появится на рисунке — словами, под каждой карточкой.
SEASON_CARDS = [
    ("auto", "По календарю", "Сайт сам меняет время года по дате"),
    ("autumn", "Осень", "Листопад, жёлтая ветка в знаке"),
    ("winter", "Зима", "Идёт снег"),
    ("newyear", "Новый год", "Снег, ёлка с гирляндой, кот в шапке"),
    ("spring", "Весна", "Цветение, птицы, зелёная ветка в знаке"),
    ("summer", "Лето", "Лучи солнца и бабочка"),
    ("off", "Без украшений", "Рисунок как есть, круглый год"),
]


@login_required
@owner_only
def hub(request):
    """Оглавление раздела: крупные карточки вместо списка ссылок."""
    site = SiteSettings.get()
    return render(
        request,
        "cabinet/site/hub.html",
        {"section": "site", "season_label": dict((c[0], c[1]) for c in SEASON_CARDS)[site.season_mode]},
    )


@login_required
@owner_only
def season(request):
    """Время года на сайте — одним нажатием на большую карточку."""
    site = SiteSettings.get()
    if request.method == "POST":
        mode = request.POST.get("season_mode", "")
        if mode in SiteSettings.SeasonMode.values:
            site.season_mode = mode
            site.save(update_fields=["season_mode", "updated_at"])
            label = dict((c[0], c[1]) for c in SEASON_CARDS)[mode]
            messages.success(request, f"Время года на сайте: {label.lower()}. Уже видно на главной.")
        return redirect("cabinet:site_season")

    today = timezone.localdate()
    mode = site.season_mode
    # Что показывает рисунок прямо сейчас — для живого примера справа.
    if mode == "auto":
        preview, holiday = season_of(today), is_new_year(today)
    elif mode == "newyear":
        preview, holiday = "winter", True
    elif mode == "off":
        preview, holiday = "", False
    else:
        preview, holiday = mode, False

    return render(
        request,
        "cabinet/site/season.html",
        {
            "section": "site",
            "mode": mode,
            "cards": SEASON_CARDS,
            "preview_season": preview,
            "preview_new_year": holiday,
            "calendar_now": SEASON_NAMES[season_of(today)] + (", праздники" if is_new_year(today) else ""),
        },
    )


# --- Общий редактор: список → карточка → сохранить / удалить --------------
#
# Вопросы, статьи, публикации и этапы устроены одинаково: список записей
# и форма одной записи. Один редактор на всех, а не четыре копии: копии
# однажды разошлись бы, и в одном разделе удаление спрашивало бы
# подтверждение, а в другом — нет.

from dataclasses import dataclass, field as dc_field

from django import forms
from django.db.models import ProtectedError
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils.text import slugify

from apps.core.models import Article, Objection, PressMention, StageNorm, translit

TEXTAREA = {"rows": 4}


@dataclass
class Editor:
    model: type
    title: str            # заголовок раздела: «Вопросы»
    one: str              # одна запись в винительном: «вопрос»
    hint: str             # что это на сайте
    fields: list
    row: callable         # запись → (заголовок, пояснение)
    public: str = ""      # где это на сайте: имя адреса
    can_add: bool = True
    widgets: dict = dc_field(default_factory=dict)
    labels: dict = dc_field(default_factory=dict)
    help: dict = dc_field(default_factory=dict)

    def form_class(self):
        return forms.modelform_factory(
            self.model, fields=self.fields, widgets=self.widgets,
            labels=self.labels, help_texts=self.help,
        )


def _shown(flag):
    return "на сайте" if flag else "скрыто"


EDITORS = {
    "voprosy": Editor(
        model=Objection, title="Вопросы", one="вопрос",
        hint="«Вопросы, которые задают чаще всего» на главной и страница «Вопросы»",
        fields=["question", "answer", "is_published", "order"],
        row=lambda o: (o.question, _shown(o.is_published)),
        public="public:objections",
        widgets={"answer": forms.Textarea(attrs={"rows": 8})},
        labels={"is_published": "Показывать на сайте", "order": "Порядок"},
        help={"order": "Меньше — выше. Первые три видны на главной",
              "answer": "Пустая строка — новый абзац"},
    ),
    "stati": Editor(
        model=Article, title="Статьи", one="статью",
        hint="Раздел «Полезное»: материалы для тех, у кого ремонт не завтра",
        fields=["title", "lead", "body", "published_at", "is_published"],
        row=lambda a: (a.title, f"{a.published_at:%d.%m.%Y} · {_shown(a.is_published)}"),
        public="public:articles",
        widgets={"body": forms.Textarea(attrs={"rows": 16}), "lead": forms.Textarea(attrs={"rows": 2}),
                 "published_at": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")},
        labels={"is_published": "Показывать на сайте"},
        help={"lead": "Одна-две фразы под заголовком в списке статей",
              "body": "Пустая строка — новый абзац; строка с «## » — подзаголовок; «- » — пункт списка"},
    ),
    "publikacii": Editor(
        model=PressMention, title="Публикации", one="публикацию",
        hint="Журналы и статьи о вас: строка на первом экране и страница «Публикации»",
        fields=["outlet", "issue", "title", "date", "quote", "cover", "spread", "file", "url", "logo",
                "is_published", "order"],
        row=lambda p: (f"«{p.outlet}»" + (f", {p.issue}" if p.issue else ""), f"{p.title} · {_shown(p.is_published)}"),
        public="public:publications",
        widgets={"quote": forms.Textarea(attrs=TEXTAREA),
                 "date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")},
        labels={"is_published": "Показывать на сайте", "url": "Ссылка на публикацию в интернете"},
        help={"order": "Меньше — выше. Первая видна на главной"},
    ),
    "etapy": Editor(
        model=StageNorm, title="Этапы работы", one="этап",
        hint="Страница «Как я работаю»: восемь этапов, их сроки и что делает заказчик",
        fields=["title", "description", "what_client_does", "working_days", "client_days"],
        row=lambda s: (f"{s.number}. {s.title}", f"{s.working_days} раб. дн. · согласование {s.client_days} дн."),
        public="public:how", can_add=False,
        widgets={"description": forms.Textarea(attrs=TEXTAREA)},
        help={"working_days": "Сколько рабочих дней этап занимает у вас",
              "client_days": "Сколько дней нужно заказчику, чтобы посмотреть и ответить"},
    ),
}


def _editor(kind):
    editor = EDITORS.get(kind)
    if not editor:
        raise Http404
    return editor


@login_required
@owner_only
def editor_list(request, kind):
    editor = _editor(kind)
    return render(
        request,
        "cabinet/site/list.html",
        {
            "section": "site", "kind": kind, "editor": editor,
            "rows": [(obj, *editor.row(obj)) for obj in editor.model.objects.all()],
        },
    )


@login_required
@owner_only
def editor_edit(request, kind, pk=None):
    editor = _editor(kind)
    obj = get_object_or_404(editor.model, pk=pk) if pk else None
    if obj is None and not editor.can_add:
        raise Http404
    Form = editor.form_class()

    if request.method == "POST":
        if obj and request.POST.get("remove") and editor.can_add:
            try:
                obj.delete()
                messages.success(request, f"Удалено: {editor.row(obj)[0]}.")
            except ProtectedError:
                messages.error(request, "Удалить нельзя — на запись ссылаются. Снимите «Показывать на сайте».")
            return redirect("cabinet:site_list", kind=kind)

        form = Form(request.POST, request.FILES, instance=obj)
        if form.is_valid():
            saved = form.save(commit=False)
            if isinstance(saved, Article) and not saved.slug:
                saved.slug = _free_slug(Article, saved.title)
            saved.save()
            form.save_m2m()
            messages.success(request, f"Сохранено: {editor.row(saved)[0]}. Уже на сайте.")
            return redirect("cabinet:site_list", kind=kind)
        messages.error(request, "Проверьте отмеченные поля.")
    else:
        form = Form(instance=obj)

    return render(
        request,
        "cabinet/site/edit.html",
        {"section": "site", "kind": kind, "editor": editor, "obj": obj, "form": form},
    )


def _free_slug(model, title):
    """Адрес из названия транслитом, свободный: «kak-vybrat-plitku-2»."""
    base = slugify(translit(title))[:200] or "material"
    slug, n = base, 2
    while model.objects.filter(slug=slug).exists():
        slug, n = f"{base}-{n}", n + 1
    return slug


# --- О себе и контакты ------------------------------------------------------

ABOUT_GROUPS = [
    ("О себе", "Имя и подпись стоят в шапке; «Коротко» — блок на главной, «Текст о себе» — страница «Обо мне»",
     ["owner_name", "owner_title", "owner_photo", "owner_intro_title", "owner_intro", "owner_about"]),
    ("Контакты", "В подвале каждой страницы и на странице «Контакты»",
     ["phone", "email", "telegram", "whatsapp", "city"]),
    ("Соцсети", "Пустое поле — значка на сайте не будет",
     ["instagram", "vk", "pinterest", "dzen"]),
    ("Реквизиты и оплата", "Реквизиты — в подвале и договорах; «Как оплатить» — на счёте вместо кнопки оплаты",
     ["legal_name", "inn", "payment_note"]),
    ("Регламент", "Публикуется на сайте дословно и подтверждается в договоре",
     ["workday_start", "workday_end", "reply_hours", "regulations"]),
    ("Загрузка", "Сверх этого числа новые проекты встают в очередь",
     ["wip_limit"]),
]


class AboutForm(forms.ModelForm):
    class Meta:
        model = SiteSettings
        fields = [name for _, _, names in ABOUT_GROUPS for name in names]
        widgets = {
            "owner_intro": forms.Textarea(attrs={"rows": 4}),
            "owner_about": forms.Textarea(attrs={"rows": 10}),
            "payment_note": forms.Textarea(attrs={"rows": 3}),
            "regulations": forms.Textarea(attrs={"rows": 8}),
        }

    def groups(self):
        return [(title, hint, [self[name] for name in names]) for title, hint, names in ABOUT_GROUPS]


@login_required
@owner_only
def about(request):
    site = SiteSettings.get()
    if request.method == "POST":
        form = AboutForm(request.POST, request.FILES, instance=site)
        if form.is_valid():
            form.save()
            messages.success(request, "Сохранено. Уже на сайте.")
            return redirect("cabinet:site_about")
        messages.error(request, "Проверьте отмеченные поля.")
    else:
        form = AboutForm(instance=site)
    return render(request, "cabinet/site/about.html", {"section": "site", "form": form})


# --- Работы: объект и его фотографии ----------------------------------------

from django.db.models import Max
from django.http import JsonResponse
from django.template.loader import render_to_string
from django.views.decorators.http import require_POST

from apps.core.models import PortfolioPhoto, PortfolioProject

WORK_GROUPS = [
    ("Объект", "Название, город и площадь видны в списке работ; «Коротко» — под названием",
     ["title", "city", "area", "style", "year", "designed_on", "built_on", "summary"]),
    ("Как это делалось", "Свёрнутые блоки под фотографиями на странице объекта",
     ["task", "solution", "result", "modules"]),
    ("Отзыв заказчика", "Показывается, только если стоит галочка «Заказчик разрешил публикацию»",
     ["client_name", "client_quote", "client_photo", "client_video", "client_consent"]),
    ("Показ", "", ["is_published", "is_featured", "order"]),
]


class WorkForm(forms.ModelForm):
    class Meta:
        model = PortfolioProject
        fields = [name for _, _, names in WORK_GROUPS for name in names]
        widgets = {
            "summary": forms.Textarea(attrs={"rows": 2}),
            "task": forms.Textarea(attrs={"rows": 4}),
            "solution": forms.Textarea(attrs={"rows": 4}),
            "result": forms.Textarea(attrs={"rows": 4}),
            "client_quote": forms.Textarea(attrs={"rows": 4}),
            "modules": forms.CheckboxSelectMultiple,
        }
        labels = {
            "modules": "Что было сделано (услуги)",
            "is_published": "Показывать на сайте",
            "order": "Порядок в списке работ",
        }
        help_texts = {"order": "Меньше — выше"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["modules"].required = False

    def groups(self):
        return [(title, hint, [self[name] for name in names]) for title, hint, names in WORK_GROUPS]


@login_required
@owner_only
def works(request):
    projects = PortfolioProject.objects.prefetch_related("photos")
    return render(request, "cabinet/site/works.html", {"section": "site", "projects": projects})


@login_required
@owner_only
def work_edit(request, pk=None):
    project = get_object_or_404(PortfolioProject, pk=pk) if pk else None

    if request.method == "POST":
        if project and request.POST.get("remove"):
            title = project.title
            project.delete()
            messages.success(request, f"Работа «{title}» удалена вместе с фотографиями.")
            return redirect("cabinet:site_works")

        form = WorkForm(request.POST, instance=project)
        if form.is_valid():
            project = form.save()
            if pk:
                _save_photos(request, project)
                messages.success(request, f"Сохранено: «{project.title}». Уже на сайте.")
                return redirect("cabinet:site_works")
            # Новая работа — сразу к фотографиям: без них объекта на сайте нет.
            messages.success(request, f"Работа «{project.title}» заведена. Теперь добавьте фотографии.")
            return redirect("cabinet:site_work", pk=project.pk)
        messages.error(request, "Проверьте отмеченные поля.")
    else:
        form = WorkForm(instance=project)

    return render(
        request,
        "cabinet/site/work_edit.html",
        {"section": "site", "form": form, "project": project,
         "photos": project.photos.all() if project else []},
    )


def _save_photos(request, project):
    """Подписи, отметки и порядок кадров — из той же формы, что и объект.

    Порядок — это порядок карточек на странице: их перетаскивают, и форма
    отправляет id в новом порядке. Номера пишутся с шагом десять, как
    в админке, — между соседями всегда есть место.
    """
    photos = {str(p.pk): p for p in project.photos.all()}
    cover = request.POST.get("cover", "")
    for position, photo_id in enumerate(request.POST.getlist("photo"), start=1):
        photo = photos.get(photo_id)
        if not photo:
            continue
        if request.POST.get(f"delete_{photo_id}"):
            photo.delete()
            continue
        photo.caption = request.POST.get(f"caption_{photo_id}", "")[:200]
        photo.is_wide = bool(request.POST.get(f"wide_{photo_id}"))
        photo.is_before = bool(request.POST.get(f"before_{photo_id}"))
        photo.is_cover = photo_id == cover
        photo.order = position * 10
        photo.save()


class PhotoUploadForm(forms.ModelForm):
    class Meta:
        model = PortfolioPhoto
        fields = ["image"]


@login_required
@owner_only
@require_POST
def work_photo_add(request, pk):
    """Один кадр за запрос: тридцать фотографий одним запросом не пропустит
    ни сервер, ни мобильная сеть, а по одному — видно, сколько осталось."""
    project = get_object_or_404(PortfolioProject, pk=pk)
    form = PhotoUploadForm(request.POST, request.FILES)
    if not form.is_valid():
        return JsonResponse({"ok": False, "error": "Это не похоже на фотографию."}, status=400)
    photo = form.save(commit=False)
    photo.project = project
    photo.order = (project.photos.aggregate(m=Max("order"))["m"] or 0) + 10
    if not project.photos.filter(is_cover=True).exists():
        photo.is_cover = True  # первый кадр — обложка, пока не выбрали другую
    photo.save()
    html = render_to_string("cabinet/site/_photo_tile.html", {"photo": photo}, request=request)
    return JsonResponse({"ok": True, "html": html})
