"""Публичный сайт."""

import logging
from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.catalog.models import (
    Block,
    ComplexityFactor,
    ModuleGroup,
    Preset,
    PricingSettings,
    ServiceModule,
)
from apps.catalog.pricing import calculate, default_complexity, default_preset
from apps.contracts.models import ClauseQuestion, Contract, ContractAck
from apps.crm.models import Client, Lead, Property, Quote, QuoteItem

from . import notify, spam
from .forms import CalculatorForm, LeadForm
from .models import (
    Article,
    CookieConsent,
    LegalDocument,
    Objection,
    PersonalDataConsent,
    PortfolioProject,
    PressMention,
    SiteSettings,
    StageNorm,
    group_by_block,
)
from .utils import working_deadline

logger = logging.getLogger(__name__)

CONSENT_COOKIE_AGE = 60 * 60 * 24 * 180  # полгода — типовой срок для куки-согласия


def _client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def _shelf_sections(modules):
    """Блоки склада: одиночные и группы взаимоисключающих вариантов.

    Потолок, окно и стены — это по нескольку взаимоисключающих модулей.
    Раньше они лежали на складе отдельными блоками, и получалась
    путаница: берёшь «выезды» — подсвечивается потолок, берёшь «надзор» —
    снова тот же потолок. А как убрать потом один конкретный блок, если
    потолок один, было непонятно вовсе.

    Поэтому группа приезжает на склад ОДНИМ блоком с переключателем
    формата. Место в комнате одно — значит и блок один: что положили,
    то и убирают.
    """
    sections = []
    by_group = {}
    for module in modules:
        if not module.group_id:
            sections.append({"group": None, "modules": [module]})
            continue
        section = by_group.get(module.group_id)
        if section is None:
            section = {"group": module.group, "modules": [], "active": module}
            by_group[module.group_id] = section
            sections.append(section)
        section["modules"].append(module)
    return sections


def _mark_active_variants(context, selected_ids):
    """Какой вариант в группе показан выбранным.

    Тот, что лежит в комнате. Если там пусто — первый: блок должен
    что-то означать ещё до того, как его понесли.
    """
    chosen = set(selected_ids)
    for key in ("design_sections", "realization_sections", "extra_sections"):
        for section in context.get(key, []):
            if not section.get("group"):
                continue
            picked = [m for m in section["modules"] if m.pk in chosen]
            section["active"] = picked[0] if picked else section["modules"][0]


def _catalog_context():
    modules = list(
        ServiceModule.objects.filter(is_active=True).select_related("group").order_by("block", "order")
    )
    design = [m for m in modules if m.block == Block.DESIGN]
    realization = [m for m in modules if m.block == Block.REALIZATION]
    extra = [m for m in modules if m.block == Block.EXTRA]
    return {
        "modules": modules,
        "design_sections": _shelf_sections(design),
        "realization_sections": _shelf_sections(realization),
        "extra_sections": _shelf_sections(extra),
        "design_modules": design,
        "realization_modules": realization,
        "extra_modules": extra,
        "groups": ModuleGroup.objects.prefetch_related("modules").all(),
        "presets": Preset.objects.filter(is_active=True).prefetch_related("modules"),
        "complexities": ComplexityFactor.objects.filter(kind=ComplexityFactor.Kind.STYLE),
        "conditions": ComplexityFactor.objects.filter(kind=ComplexityFactor.Kind.CONDITION),
        "pricing": PricingSettings.get(),
    }


# --- Страницы ---------------------------------------------------------------


def _hero_pricing():
    """Числа для мини-расчёта на первом экране.

    Первый экран должен отвечать на вопрос, ради которого сюда пришли:
    сколько это стоит для МОЕЙ квартиры. Не «от стольки-то за квадрат»,
    а число. Считается тем же каталогом, что и всё остальное, поэтому
    разойтись с конструктором не может.
    """
    pricing = PricingSettings.get()
    preset = default_preset()
    modules = list(preset.modules.filter(is_active=True)) if preset else []

    per_sqm = sum(
        (m.price for m in modules if m.unit == "sqm"), Decimal("0")
    )
    fixed = sum((m.price for m in modules if m.unit == "fixed"), Decimal("0"))

    # Площадь по умолчанию — маленькая намеренно. Первое число, которое
    # видит человек, задаёт тон разговору: с площади «как у среднего
    # заказа» на экране сразу стоит сумма, от которой половина закрывает
    # вкладку, не дочитав, из чего она складывается. Свою площадь всё
    # равно введут — а первым впечатлением будет посильная цифра.
    default_area = Decimal("30")
    if pricing.small_area_enabled and default_area <= pricing.small_area_threshold:
        default_price = pricing.small_area_price
    else:
        default_price = per_sqm * default_area + fixed

    return {
        "per_sqm": int(per_sqm),
        "fixed": int(fixed),
        "small_enabled": pricing.small_area_enabled,
        "small_threshold": float(pricing.small_area_threshold),
        "small_price": int(pricing.small_area_price),
        "default_area": int(default_area),
        # Это число видит тот, у кого не выполнился JavaScript. Оно обязано
        # совпадать с тем, что посчитает скрипт, иначе цена «прыгает».
        "default_price": int(default_price),
    }


def _press():
    """Публикации в прессе. Пустой список — раздел не показывается вовсе:
    пустая «Пресса» говорит громче, чем её отсутствие."""
    return PressMention.objects.filter(is_published=True)


def _featured_projects(published, limit=4):
    """Работы для главной.

    Галочка «На главную» задаёт порядок, а не ограничивает витрину:
    отмеченные идут первыми, свободные места добираются последними
    опубликованными. Иначе получается то, что и получилось — Дарья
    завела три объекта, отметила один, и на главной остался один,
    хотя в «Работах» их три.
    """
    chosen = list(published.filter(is_featured=True)[:limit])
    if len(chosen) < limit:
        taken = [p.pk for p in chosen]
        chosen += list(published.exclude(pk__in=taken)[: limit - len(chosen)])
    return chosen


def home(request):
    published = PortfolioProject.objects.filter(is_published=True)
    return render(
        request,
        "public/home.html",
        {
            "featured": _featured_projects(published),
            "presets": Preset.objects.filter(is_active=True).prefetch_related("modules"),
            "objections": Objection.objects.filter(is_published=True)[:3],
            "hero_pricing": _hero_pricing(),
            "stage_count": StageNorm.objects.count(),
            "press": _press(),
        },
    )


def about(request):
    return render(request, "public/about.html", {"press": _press()})


def publications(request):
    """Публикации в изданиях.

    Отдельная страница, но не отдельный пункт меню. Шестая ссылка
    в шапке размывает первые пять, а публикации — это доказательство,
    и работает оно там, где человек сомневается: на главной и в «Обо мне».
    Оттуда сюда и приходят, по обложке.
    """
    return render(request, "public/publications.html", {"press": _press()})


def services(request):
    return render(request, "public/services.html", _catalog_context())


def how(request):
    stages = list(StageNorm.objects.all())
    return render(
        request,
        "public/how.html",
        {
            "stages": stages,
            # Те же три блока, что и на шкале в кабинете: человек, который
            # прочитал страницу до заказа, потом узнаёт их в своём проекте.
            "blocks": group_by_block(stages),
            "total_days": sum(s.working_days for s in stages),
            "client_days": sum(s.client_days for s in stages),
        },
    )


def objections(request):
    return render(
        request, "public/objections.html", {"objections": Objection.objects.filter(is_published=True)}
    )


def portfolio(request):
    return render(
        request,
        "public/portfolio.html",
        {"projects": PortfolioProject.objects.filter(is_published=True).prefetch_related("photos")},
    )


def portfolio_detail(request, slug):
    project = get_object_or_404(
        PortfolioProject.objects.prefetch_related("photos", "modules"),
        slug=slug,
        is_published=True,
    )
    return render(request, "public/portfolio_detail.html", {"project": project})


def articles(request):
    return render(
        request, "public/articles.html", {"articles": Article.objects.filter(is_published=True)}
    )


def article(request, slug):
    return render(
        request,
        "public/article.html",
        {"article": get_object_or_404(Article, slug=slug, is_published=True)},
    )


def legal(request, kind):
    doc = get_object_or_404(LegalDocument, kind=kind, is_published=True)
    return render(request, "public/legal.html", {"doc": doc})


# --- Конструктор ------------------------------------------------------------


def constructor(request):
    """Дом из кубиков.

    Стартовое состояние — собранный дом «Под ключ», а не пустая площадка:
    клиент не собирает с нуля, он разбирает. Каждое снятие переживается
    как потеря, а не как экономия.
    """
    context = _catalog_context()
    pricing = context["pricing"]
    complexity = default_complexity()
    conditions = []

    # Стартовое состояние — только пол. Комнату собирают с нуля:
    # так каждый блок оказывается осознанным решением, а не галочкой,
    # которую забыли снять.
    preset = None
    selected = []
    area = Decimal("60")
    rooms = 2
    months = None

    # Площадь может прийти ссылкой с главной: там человек её уже ввёл,
    # и заставлять вводить второй раз — потерять половину пришедших.
    raw_area = request.GET.get("area")
    if raw_area:
        try:
            candidate = Decimal(raw_area.replace(",", "."))
            if Decimal("1") <= candidate <= Decimal("10000"):
                area = candidate
        except (ArithmeticError, ValueError):
            pass

    if request.method == "POST":
        # Путь без JavaScript: те же поля обычным POST, считает тот же код.
        form = CalculatorForm(request.POST)
        if form.is_valid():
            area = form.cleaned_data["area"]
            rooms = form.cleaned_data["rooms"]
            complexity = form.cleaned_data.get("complexity") or complexity
            conditions = list(form.cleaned_data.get("conditions") or [])
            selected = list(form.cleaned_data["modules"])
            months = form.cleaned_data.get("supervision_months")

    calc = calculate(
        area=area,
        rooms=rooms,
        complexity=complexity,
        conditions=conditions,
        modules=selected,
        months=months,
        settings=pricing,
    )

    selected_ids = [line.module.pk for line in calc.lines]
    _mark_active_variants(context, selected_ids)

    context.update(
        {
            "preset": preset,
            "calc": calc,
            "area": area,
            "rooms": rooms,
            "complexity": complexity,
            "chosen_conditions": [c.pk for c in conditions],
            "months": calc.months,
            "selected_ids": selected_ids,
            # Отдаём словарём и печатаем через |json_script: он экранирует
            # содержимое так, что текст из базы не может закрыть тег script.
            "catalog_data": {
                "modules": [
                    {
                        "id": m.pk,
                        "code": m.code,
                        "title": m.label,
                        "block": m.block,
                        "housePart": m.house_part,
                        "unit": m.unit,
                        "price": float(m.price),
                        "required": m.is_required,
                        "complexity": m.affected_by_complexity,
                        "group": m.group_id,
                        "warning": m.warning,
                        "days": m.duration_days,
                    }
                    for m in context["modules"]
                ],
                "complexities": [
                    {"id": c.pk, "code": c.code, "factor": float(c.factor)}
                    for c in context["complexities"]
                ],
                "presets": [
                    {
                        "id": p.pk,
                        "code": p.code,
                        "title": p.title,
                        "modules": [m.pk for m in p.modules.all()],
                    }
                    for p in context["presets"]
                ],
            },
        }
    )
    return render(request, "public/constructor.html", context)


@require_POST
def calculate_api(request):
    """Пересчёт для конструктора.

    Считает тот же `calculate`, что и серверная форма: двух реализаций
    расчёта быть не должно, иначе сайт и Дарья однажды назовут разные суммы.
    """
    form = CalculatorForm(request.POST)
    if not form.is_valid():
        return JsonResponse({"ok": False, "errors": form.errors}, status=400)

    calc = calculate(
        area=form.cleaned_data["area"],
        rooms=form.cleaned_data["rooms"],
        complexity=form.cleaned_data.get("complexity") or default_complexity(),
        conditions=form.cleaned_data.get("conditions"),
        modules=form.cleaned_data["modules"],
        months=form.cleaned_data.get("supervision_months"),
    )
    return JsonResponse({"ok": True, "calc": calc.as_dict()})


# --- Заявка -----------------------------------------------------------------


def contacts(request):
    form = LeadForm(request.POST or None, initial={"quote_token": request.GET.get("quote", "")})
    if request.method == "POST" and form.is_valid():
        lead = _save_lead(request, form.cleaned_data)
        messages.success(
            request,
            "Заявка у меня. Отвечу в рабочее время — "
            f"до {timezone.localtime(_reply_deadline()):%d.%m в %H:%M}.",
        )
        return redirect("public:thanks")
    return render(request, "public/contacts.html", {"form": form})


def thanks(request):
    return render(request, "public/thanks.html", {"deadline": _reply_deadline()})


def _reply_deadline():
    settings_obj = SiteSettings.get()
    return working_deadline(
        timezone.now(),
        hours=settings_obj.reply_hours,
        day_start=settings_obj.workday_start,
        day_end=settings_obj.workday_end,
        workdays=settings_obj.workdays,
    )


@transaction.atomic
def _save_lead(request, data):
    """Создать заказчика, объект и заявку.

    Заявка всегда получает дату следующего шага: заявка без него и есть
    «потерянная заявка».
    """
    client, _ = Client.objects.get_or_create(
        phone=data["phone"] or "",
        email=data["email"] or "",
        defaults={"name": data["name"], "source": "сайт"},
    )
    if not client.name:
        client.name = data["name"]
        client.messenger = data.get("messenger", "")
        client.save(update_fields=["name", "messenger"])

    prop = None
    if data.get("area"):
        prop = Property.objects.create(
            client=client,
            city=data.get("city") or "Красноярск",
            kind=data.get("kind") or Property.Kind.NEW,
            area=data["area"],
            rooms=data.get("rooms") or 1,
            keys_received=bool(data.get("keys_received")),
            has_builders=bool(data.get("has_builders")),
            desired_move_in=data.get("desired_move_in", ""),
        )

    # Похоже ли на рассылку. Считаем до создания заявки, потому что от
    # ответа зависит и уведомление, и место заявки в кабинете.
    ip = _client_ip(request) or None
    recent = 0
    if ip:
        recent = Lead.objects.filter(
            ip=ip, created_at__gte=timezone.now() - timedelta(hours=1)
        ).count()
    is_spam, reason = spam.verdict(
        message=data.get("message", ""), name=data["name"], same_ip_hour=recent
    )

    lead = Lead.objects.create(
        client=client,
        estate=prop,
        source="сайт",
        message=data.get("message", ""),
        is_spam=is_spam,
        spam_reason=reason,
        ip=ip,
        answers={
            "complexity": data["complexity"].code if data.get("complexity") else None,
            "decides_alone": bool(data.get("decides_alone")),
            "desired_move_in": data.get("desired_move_in", ""),
            "has_builders": bool(data.get("has_builders")),
            "keys_received": bool(data.get("keys_received")),
        },
        next_action="Связаться и назначить созвон",
        next_action_at=_reply_deadline(),
    )

    consent_doc = LegalDocument.objects.filter(kind=LegalDocument.Kind.CONSENT).first()
    PersonalDataConsent.objects.create(
        name=data["name"],
        contact=data["phone"] or data["email"] or data.get("messenger", ""),
        document_version=consent_doc.version if consent_doc else "",
        source="заявка с сайта",
        ip=ip or "",
    )

    token = data.get("quote_token")
    if token:
        Quote.objects.filter(token=token, client__isnull=True).update(client=client, lead=lead)

    # Уведомление в Telegram. Оно НЕ имеет права уронить заявку: заявка
    # уже в базе, и упавший мессенджер не должен превращаться в ошибку
    # у человека, который только что заполнил форму.
    #
    # Про спам не пишем вовсе. Уведомление о рассылке хуже самой рассылки:
    # телефон звонит, Дарья открывает — а там ничего. Двух таких сообщений
    # хватает, чтобы перестать открывать все остальные.
    if not is_spam:
        try:
            notify.new_lead(lead)
        except Exception:  # noqa: BLE001 — здесь важно поймать вообще всё
            logger.exception("Не удалось отправить уведомление о заявке %s", lead.pk)

    return lead


@require_POST
def save_quote(request):
    """Сохранить собранный расчёт и получить на него ссылку.

    Именно это заменяет PDF: один адрес, всё внутри, открывается
    на телефоне и всегда актуален.
    """
    form = CalculatorForm(request.POST)
    if not form.is_valid():
        return JsonResponse({"ok": False, "errors": form.errors}, status=400)

    complexity = form.cleaned_data.get("complexity") or default_complexity()
    calc = calculate(
        area=form.cleaned_data["area"],
        rooms=form.cleaned_data["rooms"],
        complexity=complexity,
        conditions=form.cleaned_data.get("conditions"),
        modules=form.cleaned_data["modules"],
        months=form.cleaned_data.get("supervision_months"),
    )

    with transaction.atomic():
        quote = Quote.objects.create(
            area=form.cleaned_data["area"],
            rooms=form.cleaned_data["rooms"],
            complexity=complexity,
            supervision_months=calc.months,
            procurement_stages=1,
            design_total=calc.design_total,
            realization_total=calc.realization_total,
            extra_total=calc.extra_total,
            status=Quote.Status.DRAFT,
            valid_until=timezone.localdate() + timedelta(days=30),
        )
        QuoteItem.objects.bulk_create(
            QuoteItem(
                quote=quote,
                module=line.module,
                title=line.module.title,
                unit=line.module.unit,
                unit_price=line.module.price,
                quantity=line.quantity,
                amount=line.amount,
            )
            for line in calc.lines
        )
    return JsonResponse({"ok": True, "url": quote.get_absolute_url(), "token": quote.token})


def quote(request, token):
    obj = get_object_or_404(
        Quote.objects.select_related("client", "complexity").prefetch_related("items__module"), token=token
    )
    obj.mark_opened()
    return render(request, "public/quote.html", {"quote": obj})


# --- Договор ----------------------------------------------------------------


def contract(request, token):
    obj = get_object_or_404(
        Contract.objects.select_related("template", "client").prefetch_related("template__clauses"),
        token=token,
    )
    if request.method == "POST":
        _save_contract_feedback(request, obj)
        messages.success(request, "Спасибо, я вижу ваши отметки и вернусь с пояснениями.")
        return redirect(obj.get_absolute_url())

    asked = set(obj.questions.values_list("clause_id", flat=True))
    return render(request, "public/contract.html", {"contract": obj, "asked": asked})


@transaction.atomic
def _save_contract_feedback(request, obj):
    marked = request.POST.getlist("clause")
    obj.questions.exclude(clause_id__in=marked).delete()
    for clause_id in marked:
        ClauseQuestion.objects.get_or_create(
            contract=obj,
            clause_id=clause_id,
            defaults={"question": request.POST.get(f"question_{clause_id}", "")},
        )
    if request.POST.get("ack") and not hasattr(obj, "ack"):
        ContractAck.objects.create(
            contract=obj,
            name=request.POST.get("ack_name", "") or obj.client.name,
            template_version=obj.template.version,
            ip=_client_ip(request),
        )
        obj.status = Contract.Status.REVIEWED
        obj.save(update_fields=["status"])


# --- Куки -------------------------------------------------------------------


@require_POST
def cookie_consent(request):
    """Согласие на куки.

    Записывается в журнал: закон требует доказуемости, а доказать можно
    только записанное — что выбрал человек, когда и какую редакцию
    политики при этом видел.
    """
    choice = request.POST.get("choice")
    if choice not in {CookieConsent.Choice.ALL, CookieConsent.Choice.NECESSARY}:
        return JsonResponse({"ok": False}, status=400)

    if not request.session.session_key:
        request.session.save()

    policy = LegalDocument.objects.filter(kind=LegalDocument.Kind.COOKIES).first()
    CookieConsent.objects.create(
        session_key=request.session.session_key or "",
        choice=choice,
        analytics=choice == CookieConsent.Choice.ALL,
        policy_version=policy.version if policy else "",
        user_agent=request.META.get("HTTP_USER_AGENT", "")[:300],
    )

    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"
    response = (
        JsonResponse({"ok": True})
        if is_ajax
        else redirect(request.POST.get("next") or "public:home")
    )
    response.set_cookie(
        "cookie_consent",
        choice,
        max_age=CONSENT_COOKIE_AGE,
        samesite="Lax",
        secure=not request.get_host().startswith("127.0.0.1"),
    )
    return response


def csrf_failure(request, reason=""):
    """Токен устарел — это не ошибка человека и не повод его пугать.

    Стандартная страница Django говорит «Ошибка проверки CSRF, запрос
    отклонён» и предлагает почитать про подделку запросов. В жизни за этим
    почти всегда стоит одно: вкладку с кабинетом открыли вчера, а сегодня
    зашли заново — и токен в старой разметке уже не тот. На телефоне, где
    вкладки живут месяцами, это происходит регулярно.

    Ответ 403 сохраняем: для браузера ничего не изменилось, отклонён так
    отклонён. Меняется только то, что человек читает.
    """
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse(
            {"ok": False, "error": "Страница устарела. Обновите её и повторите."}, status=403
        )
    response = render(request, "public/csrf.html", {"reason": reason}, status=403)
    return response
