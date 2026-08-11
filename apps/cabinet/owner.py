"""Кабинет Дарьи: воронка, проекты, цены, договоры, счета."""

from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.billing.models import Invoice
from apps.catalog.models import ComplexityFactor, PriceHistory, ServiceModule
from apps.contracts.models import Contract, ContractClause, ContractTemplate
from apps.core.models import SiteSettings
from apps.crm.models import Lead
from apps.projects.models import Project, Stage

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
        {"lead": lead, "statuses": Lead.Status.choices},
    )


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
            "projects": qs,
            "wip_limit": site.wip_limit,
            "wip_used": active,
            "wip_exceeded": active > site.wip_limit,
        },
    )


@login_required
@owner_only
def project_detail(request, pk):
    project = get_object_or_404(
        Project.objects.select_related("client", "estate").prefetch_related(
            "stages__revisions", "stages__files"
        ),
        pk=pk,
    )
    return render(request, "cabinet/project_detail.html", {"project": project})


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
    if request.method == "POST":
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
        {"modules": modules, "complexities": ComplexityFactor.objects.all()},
    )


@login_required
@owner_only
def contracts(request):
    return render(
        request,
        "cabinet/contracts.html",
        {
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

    return render(request, "cabinet/contract_edit.html", {"template": template})


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
        {"invoices": Invoice.objects.select_related("client", "project").prefetch_related("payments")},
    )
