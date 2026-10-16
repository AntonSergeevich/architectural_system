from django.conf import settings
from django.utils import timezone

from .models import LegalDocument, SiteSettings

# Месяц → время года. Весной и летом сайту украшать нечем: рисунок
# и так светлый и зелёный, а лишняя анимация — это шум.
SEASONS = {9: "autumn", 10: "autumn", 11: "autumn", 12: "winter", 1: "winter", 2: "winter"}


def season_of(day):
    """Время года для оформления: «autumn», «winter» или пустая строка."""
    return SEASONS.get(day.month, "")


def site(request):
    """Настройки и куки-баннер — на каждой странице."""
    consent = request.COOKIES.get("cookie_consent", "")
    settings_row = SiteSettings.get()
    return {
        "site": settings_row,
        "cookie_consent": consent,
        "show_cookie_banner": not consent,
        "legal_menu": LegalDocument.objects.filter(is_published=True),
        "payments_enabled": settings.PAYMENTS_ENABLED,
        # Дата — по Красноярску (TIME_ZONE), а не по UTC: в ночь на
        # первое сентября разница в семь часов — это разница в сезоне.
        "season": season_of(timezone.localdate()) if settings_row.seasonal else "",
    }
