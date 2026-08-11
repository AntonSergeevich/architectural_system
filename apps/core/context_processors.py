from django.conf import settings

from .models import LegalDocument, SiteSettings


def site(request):
    """Настройки и куки-баннер — на каждой странице."""
    consent = request.COOKIES.get("cookie_consent", "")
    return {
        "site": SiteSettings.get(),
        "cookie_consent": consent,
        "show_cookie_banner": not consent,
        "legal_menu": LegalDocument.objects.filter(is_published=True),
        "payments_enabled": settings.PAYMENTS_ENABLED,
    }
