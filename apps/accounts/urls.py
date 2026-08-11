from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy

from . import telegram
from .views import LoginView

app_name = "accounts"

urlpatterns = [
    path("vhod/", LoginView.as_view(), name="login"),
    path("vyhod/", auth_views.LogoutView.as_view(), name="logout"),
    # --- Восстановление пароля --------------------------------------------
    # Пароль от кабинета, куда заходят раз в неделю, будет забыт — это
    # не «если», а «когда». Без самостоятельного восстановления каждый
    # такой случай превращается в звонок Дарье.
    path(
        "parol/",
        auth_views.PasswordResetView.as_view(
            template_name="registration/password_reset_form.html",
            email_template_name="registration/password_reset_email.txt",
            subject_template_name="registration/password_reset_subject.txt",
            success_url=reverse_lazy("accounts:password_reset_done"),
        ),
        name="password_reset",
    ),
    path(
        "parol/otpravleno/",
        auth_views.PasswordResetDoneView.as_view(
            template_name="registration/password_reset_done.html"
        ),
        name="password_reset_done",
    ),
    path(
        "parol/novyy/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="registration/password_reset_confirm.html",
            success_url=reverse_lazy("accounts:password_reset_complete"),
        ),
        name="password_reset_confirm",
    ),
    path(
        "parol/gotovo/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="registration/password_reset_complete.html"
        ),
        name="password_reset_complete",
    ),
    # --- Бот ---------------------------------------------------------------
    path("telegram/<str:secret>/", telegram.webhook, name="telegram_webhook"),
]
