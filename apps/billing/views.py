"""Оплата: страница счёта, старт платежа, возврат и уведомление."""

import logging

from django.contrib import messages
from django.db import IntegrityError, transaction
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from . import getplatinum
from .models import Invoice, Payment

log = logging.getLogger(__name__)


def invoice(request, token):
    obj = get_object_or_404(Invoice.objects.select_related("client", "project"), token=token)
    return render(
        request,
        "public/invoice.html",
        {
            "invoice": obj,
            "payments_enabled": getplatinum.is_enabled(),
        },
    )


@require_POST
def pay(request, token):
    obj = get_object_or_404(Invoice, token=token)
    if not obj.is_payable:
        messages.info(request, "Этот счёт оплачивать не нужно.")
        return redirect(obj.get_absolute_url())

    try:
        url, payment_id = getplatinum.create_payment(obj)
    except getplatinum.PaymentError as exc:
        messages.error(request, str(exc))
        return redirect(obj.get_absolute_url())

    Payment.objects.create(
        invoice=obj,
        provider=Payment.Provider.GETPLATINUM,
        provider_payment_id=payment_id,
        amount=obj.left_to_pay,
        status=Payment.Status.PENDING,
    )
    return redirect(url)


def return_success(request, token):
    obj = get_object_or_404(Invoice, token=token)
    # Возврат из платёжной формы — не подтверждение оплаты: подтверждает
    # только уведомление от сервиса. Поэтому здесь ничего не меняем,
    # а показываем фактический статус счёта.
    return render(request, "public/pay_return.html", {"invoice": obj, "ok": True})


def return_fail(request, token):
    obj = get_object_or_404(Invoice, token=token)
    return render(request, "public/pay_return.html", {"invoice": obj, "ok": False})


@csrf_exempt
@require_POST
def webhook(request):
    """Уведомление от GetPlatinum.

    Без CSRF — запрос приходит со стороны, сессии у него нет. Защита здесь
    другая и единственная возможная: подпись.
    """
    params = request.POST.dict()
    if not params:
        try:
            import json

            params = json.loads(request.body.decode() or "{}")
        except ValueError:
            return HttpResponseBadRequest("bad payload")

    if not getplatinum.verify_signature(params):
        log.warning("GetPlatinum: уведомление с неверной подписью")
        return HttpResponseBadRequest("bad signature")

    data = getplatinum.parse_callback(params)
    try:
        obj = Invoice.objects.get(pk=data["invoice_id"])
    except (Invoice.DoesNotExist, ValueError, TypeError):
        log.warning("GetPlatinum: счёт %s не найден", data.get("invoice_id"))
        return HttpResponseBadRequest("unknown invoice")

    with transaction.atomic():
        payment = None
        if data["payment_id"]:
            payment = Payment.objects.select_for_update().filter(
                provider=Payment.Provider.GETPLATINUM,
                provider_payment_id=data["payment_id"],
            ).first()
        if payment is None:
            # Платёж мог начаться не с нашей кнопки, а из личного кабинета
            # провайдера — тогда записи ещё нет.
            try:
                payment = Payment.objects.create(
                    invoice=obj,
                    provider=Payment.Provider.GETPLATINUM,
                    provider_payment_id=data["payment_id"],
                    amount=data["amount"],
                    status=Payment.Status.PENDING,
                )
            except IntegrityError:
                payment = Payment.objects.select_for_update().get(
                    provider=Payment.Provider.GETPLATINUM,
                    provider_payment_id=data["payment_id"],
                )

        payment.status = data["status"]
        if data["amount"] > 0:
            payment.amount = data["amount"]
        payment.raw = params
        payment.save(update_fields=["status", "amount", "raw", "updated_at"])
        obj.refresh_status()

    return HttpResponse("OK")
