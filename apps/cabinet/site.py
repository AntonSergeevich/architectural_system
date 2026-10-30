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
