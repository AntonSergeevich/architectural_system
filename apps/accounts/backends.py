"""Вход по email или телефону.

Заказчики стабильно помнят что-то одно, и заранее неизвестно, что именно.
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend

from apps.core.utils import normalize_phone


class EmailOrPhoneBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        User = get_user_model()
        login = (username or kwargs.get("email") or "").strip()
        if not login or password is None:
            return None

        phone = normalize_phone(login)
        user = (
            User.objects.filter(email__iexact=login).first()
            or (User.objects.filter(phone=phone).first() if phone else None)
        )
        if user is None:
            # Прогоняем хеширование вхолостую: иначе по времени ответа видно,
            # существует такой пользователь или нет.
            User().set_password(password)
            return None

        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
