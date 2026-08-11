"""Оплата: страница счёта, старт платежа, возврат и уведомление."""

import json
import logging

from django.contrib import messages
from django.db import IntegrityError, transaction
from django.http import HttpResponse
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
        {"invoice": obj, "payments_enabled": getplatinum.is_enabled()},
    )


@require_POST
def pay(request, token):
    obj = get_object_or_404(Invoice.objects.select_related("client"), token=token)
    if not obj.is_payable:
        messages.info(request, "Этот счёт оплачивать не нужно.")
        return redirect(obj.get_absolute_url())

    amount = obj.left_to_pay
    try:
        url, deal = getplatinum.create_payment(obj, amount)
    except getplatinum.PaymentError as exc:
        messages.error(request, str(exc))
        return redirect(obj.get_absolute_url())

    # Запись создаём заранее и в состоянии «ожидает»: если коллбэк
    # потеряется, у нас всё равно останется след начатой оплаты,
    # по которому команда sync_payments сверится с провайдером.
    Payment.objects.create(
        invoice=obj,
        provider=Payment.Provider.GETPLATINUM,
        amount=amount,
        status=Payment.Status.PENDING,
        raw={"dealId": deal},
    )
    return redirect(url)


def return_success(request, token):
    obj = get_object_or_404(Invoice, token=token)
    # Возврат из платёжной формы оплату НЕ подтверждает — это прямо сказано
    # в документации GetPlatinum, и это логично: адрес «спасибо» можно
    # открыть руками. Поэтому здесь ничего не меняем, а показываем
    # фактический статус счёта.
    return render(request, "public/pay_return.html", {"invoice": obj, "ok": True})


def return_fail(request, token):
    obj = get_object_or_404(Invoice, token=token)
    return render(request, "public/pay_return.html", {"invoice": obj, "ok": False})


@csrf_exempt
@require_POST
def webhook(request):
    """Коллбэк GetPlatinum об оплате.

    Отвечаем 200 всегда. У них нет повторных попыток: любой другой код
    ответа означает, что уведомление потеряно навсегда, а вместе с ним —
    и факт оплаты. Поэтому «принял» и «зачислил» здесь разные вещи:
    принимаем всё, зачисляем только проверенное.

    Без CSRF: запрос приходит со стороны, сессии у него нет. Защита
    здесь другая и единственная возможная — подпись.
    """
    try:
        params = json.loads(request.body.decode() or "{}")
    except (ValueError, UnicodeDecodeError):
        log.warning("GetPlatinum: коллбэк не разобрался как JSON")
        return HttpResponse("OK")

    if not isinstance(params, dict):
        return HttpResponse("OK")

    data = getplatinum.parse_notification(params)
    if data["invoice_id"] is None:
        log.warning("GetPlatinum: чужой dealId в коллбэке: %r", data["deal_id"])
        return HttpResponse("OK")

    obj = Invoice.objects.filter(pk=data["invoice_id"]).first()
    if obj is None:
        log.warning("GetPlatinum: счёт %s не найден", data["invoice_id"])
        return HttpResponse("OK")

    trusted = getplatinum.verify_checksum(params)
    if not trusted:
        # Подпись считается по вложенной структуре, и разойтись с ними
        # в мелочах сериализации легко. Молча выбросить уведомление
        # значит потерять платёж, поэтому идём проверять напрямую.
        log.error("GetPlatinum: подпись не сошлась по счёту %s, сверяемся через /status", obj.pk)
        try:
            status = getplatinum.fetch_status(obj)
        except getplatinum.PaymentError:
            log.exception("GetPlatinum: сверка через /status не удалась, счёт %s", obj.pk)
            return HttpResponse("OK")
        data["is_success"] = status["is_success"]
        data["payment_id"] = status["payment_id"] or data["payment_id"]
        if status["amount"]:
            data["amount"] = status["amount"]

    _apply_payment(obj, data, params, verified_by="checksum" if trusted else "status")
    return HttpResponse("OK")


@transaction.atomic
def _apply_payment(obj, data, raw, verified_by):
    """Записать платёж и пересчитать статус счёта.

    Задвоение гасится уникальностью пары «провайдер + идентификатор
    платежа» на уровне базы: повторный коллбэк — это норма, а не сбой.
    """
    payment = None
    if data["payment_id"]:
        payment = (
            Payment.objects.select_for_update()
            .filter(
                provider=Payment.Provider.GETPLATINUM,
                provider_payment_id=data["payment_id"],
            )
            .first()
        )

    if payment is None:
        # Подхватываем запись, созданную при старте оплаты: иначе на счёте
        # останется висеть лишний «ожидает».
        payment = (
            Payment.objects.select_for_update()
            .filter(
                invoice=obj,
                provider=Payment.Provider.GETPLATINUM,
                provider_payment_id="",
                status=Payment.Status.PENDING,
            )
            .order_by("-created_at")
            .first()
        )

    if payment is None:
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

    payment.provider_payment_id = data["payment_id"] or payment.provider_payment_id
    payment.status = Payment.Status.SUCCEEDED if data["is_success"] else Payment.Status.FAILED
    if data["amount"] > 0:
        payment.amount = data["amount"]
    payment.raw = {"verified_by": verified_by, "payload": raw}
    payment.save()
    obj.refresh_status()
    return payment
