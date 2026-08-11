"""Публичный сайт."""

from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.catalog.models import Block, ComplexityFactor, ModuleGroup, Preset, ServiceModule
from apps.catalog.pricing import calculate, default_complexity, default_preset
from apps.contracts.models import ClauseQuestion, Contract, ContractAck
from apps.crm.models import Client, Lead, Property, Quote, QuoteItem

from .forms import CalculatorForm, LeadForm
from .models import (
    Article,
    CookieConsent,
    LegalDocument,
    Objection,
    PersonalDataConsent,
    PortfolioProject,
    SiteSettings,
    StageNorm,
)
from .utils import working_deadline

CONSENT_COOKIE_AGE = 60 * 60 * 24 * 180  # полгода — типовой срок для куки-согласия


def _client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def _catalog_context():
    modules = list(
        ServiceModule.objects.filter(is_active=True).select_related("group").order_by("block", "order")
    )
    return {
        "modules": modules,
        "design_modules": [m for m in modules if m.block == Block.DESIGN],
        "realization_modules": [m for m in modules if m.block == Block.REALIZATION],
        "extra_modules": [m for m in modules if m.block == Block.EXTRA],
        "groups": ModuleGroup.objects.prefetch_related("modules").all(),
        "presets": Preset.objects.filter(is_active=True).prefetch_related("modules"),
        "complexities": ComplexityFactor.objects.all(),
    }


# --- Страницы ---------------------------------------------------------------


def home(request):
    return render(
        request,
        "public/home.html",
        {
            "featured": PortfolioProject.objects.filter(is_published=True, is_featured=True)[:4],
            "presets": Preset.objects.filter(is_active=True).prefetch_related("modules"),
            "objections": Objection.objects.filter(is_published=True)[:3],
        },
    )


def about(request):
    return render(request, "public/about.html", {})


def services(request):
    return render(request, "public/services.html", _catalog_context())


def how(request):
    return render(
        request,
        "public/how.html",
        {
            "stages": StageNorm.objects.all(),
            "total_days": sum(s.working_days for s in StageNorm.objects.all()),
            "client_days": sum(s.client_days for s in StageNorm.objects.all()),
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
    preset = default_preset()
    complexity = default_complexity()

    selected = list(preset.modules.filter(is_active=True)) if preset else []
    area = Decimal("60")
    rooms = 2

    if request.method == "POST":
        # Путь без JavaScript: те же поля обычным POST, считает тот же код.
        form = CalculatorForm(request.POST)
        if form.is_valid():
            area = form.cleaned_data["area"]
            rooms = form.cleaned_data["rooms"]
            complexity = form.cleaned_data.get("complexity") or complexity
            selected = list(form.cleaned_data["modules"])
    calc = calculate(area=area, rooms=rooms, complexity=complexity, modules=selected)

    context.update(
        {
            "preset": preset,
            "calc": calc,
            "area": area,
            "rooms": rooms,
            "complexity": complexity,
            "selected_ids": [line.module.pk for line in calc.lines],
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
        modules=form.cleaned_data["modules"],
        months=form.cleaned_data.get("supervision_months"),
        stages=form.cleaned_data.get("procurement_stages"),
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

    lead = Lead.objects.create(
        client=client,
        estate=prop,
        source="сайт",
        message=data.get("message", ""),
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
        ip=_client_ip(request),
    )

    token = data.get("quote_token")
    if token:
        Quote.objects.filter(token=token, client__isnull=True).update(client=client, lead=lead)
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
        modules=form.cleaned_data["modules"],
        months=form.cleaned_data.get("supervision_months"),
        stages=form.cleaned_data.get("procurement_stages"),
    )

    with transaction.atomic():
        quote = Quote.objects.create(
            area=form.cleaned_data["area"],
            rooms=form.cleaned_data["rooms"],
            complexity=complexity,
            supervision_months=form.cleaned_data.get("supervision_months") or 6,
            procurement_stages=form.cleaned_data.get("procurement_stages") or 3,
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
