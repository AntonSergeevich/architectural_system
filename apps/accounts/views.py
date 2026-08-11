"""Вход в кабинет."""

from django.contrib.auth import views as auth_views


class LoginView(auth_views.LoginView):
    """Стандартный вход, но без чужого `site` в контексте.

    `LoginView` кладёт в контекст `site` и `site_name` из
    django.contrib.sites. У нас `site` — это настройки сайта (имя, телефон,
    реквизиты), и они приходят своим контекстным процессором. Django
    затирал их, и любое обращение к нашему полю на этой странице
    заканчивалось ошибкой.

    Убираем чужие ключи — и лежащий под ними наш `site` снова виден.
    """

    template_name = "registration/login.html"
    redirect_authenticated_user = True

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.pop("site", None)
        context.pop("site_name", None)
        return context
