from django.conf import settings
from django.utils import timezone

from .models import LegalDocument, SiteSettings

# Месяц → время года. Каждое — своя маленькая деталь на рисунке главной
# и в знаке: осенью листопад, зимой снег, весной цветение и птицы, летом
# бабочка и лучи солнца. Сайт, который знает, какое сейчас время года,
# выглядит живым, а не сделанным однажды и забытым.
SEASONS = {
    12: "winter", 1: "winter", 2: "winter",
    3: "spring", 4: "spring", 5: "spring",
    6: "summer", 7: "summer", 8: "summer",
    9: "autumn", 10: "autumn", 11: "autumn",
}
PREVIEWS = {"winter", "spring", "summer", "autumn", "newyear"}


def season_of(day):
    """Время года для оформления: winter, spring, summer или autumn."""
    return SEASONS[day.month]


def is_new_year(day):
    """Новогодние праздники: ёлка в комнате и шапка на коте.

    С 15 декабря по Старый Новый год включительно. Ёлка в феврале —
    это уже не праздник, а забытая ёлка, поэтому остальная зима — просто
    снег.
    """
    return (day.month == 12 and day.day >= 15) or (day.month == 1 and day.day <= 14)


def season_context(request, enabled):
    """Сезон и праздник для шаблона.

    ?season=winter (spring, summer, autumn, newyear) показывает любой
    сезон прямо сейчас: посмотреть зиму в октябре, не дожидаясь декабря.
    Это только оформление, поэтому доступно всем — ссылку можно просто
    переслать.
    """
    preview = request.GET.get("season", "")
    if preview in PREVIEWS:
        if preview == "newyear":
            return "winter", True
        return preview, False
    if not enabled:
        return "", False
    today = timezone.localdate()
    return season_of(today), is_new_year(today)


def site(request):
    """Настройки и куки-баннер — на каждой странице."""
    consent = request.COOKIES.get("cookie_consent", "")
    settings_row = SiteSettings.get()
    season, new_year = season_context(request, settings_row.seasonal)
    return {
        "site": settings_row,
        "cookie_consent": consent,
        "show_cookie_banner": not consent,
        "legal_menu": LegalDocument.objects.filter(is_published=True),
        "payments_enabled": settings.PAYMENTS_ENABLED,
        # Дата — по Красноярску (TIME_ZONE), а не по UTC: в ночь на
        # первое сентября разница в семь часов — это разница в сезоне.
        "season": season,
        "new_year": new_year,
    }
