"""Вход в кабинет.

Страница входа — единственная дверь в систему. Если она не открывается,
не работает ничего, поэтому здесь проверяется в первую очередь именно то,
на чём она уже один раз сломалась.
"""

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Role, User


class LoginTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            email="darya@example.com", password="pass-12345", role=Role.OWNER
        )

    def test_login_page_opens(self):
        """LoginView кладёт в контекст свой `site` и затирает наш.

        Пока это не было учтено, страница входа падала целиком: логотип
        обращается к `site.owner_title`, а у чужого объекта такого поля нет.
        """
        response = self.client.get(reverse("accounts:login"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Дарья")

    def test_login_by_email(self):
        ok = self.client.login(email="darya@example.com", password="pass-12345")
        self.assertTrue(ok)

    def test_login_by_phone(self):
        self.user.phone = "+79130001122"
        self.user.save(update_fields=["phone"])
        ok = self.client.login(email="+7 913 000 11 22", password="pass-12345")
        self.assertTrue(ok)

    def test_owner_lands_in_the_cabinet(self):
        self.client.login(email="darya@example.com", password="pass-12345")
        response = self.client.get(reverse("cabinet:home"))
        self.assertRedirects(response, reverse("cabinet:dashboard"))
