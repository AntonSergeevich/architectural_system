"""Вход в кабинет.

Страница входа — единственная дверь в систему. Если она не открывается,
не работает ничего, поэтому здесь проверяется в первую очередь именно то,
на чём она уже один раз сломалась.
"""

import json
from unittest import mock

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import Role, TelegramAccount, User
from apps.core import notify


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

    def test_password_reset_pages_open(self):
        """Пароль от кабинета будет забыт — это «когда», а не «если»."""
        response = self.client.get(reverse("accounts:password_reset"))
        self.assertEqual(response.status_code, 200)

        response = self.client.post(
            reverse("accounts:password_reset"), {"email": "darya@example.com"}
        )
        self.assertRedirects(response, reverse("accounts:password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("parol/novyy/", mail.outbox[0].body)


class TelegramLinkTests(TestCase):
    """Привязка бота: кнопка, код, chat_id."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            email="klient@example.com", password="pass-12345", full_name="Мария"
        )

    def test_code_exists_before_anything_happens(self):
        """Ссылка должна существовать в момент, когда её решили нажать."""
        account = TelegramAccount.for_user(self.user)
        self.assertTrue(account.link_code)
        self.assertFalse(account.is_linked)

    def _update(self, text, chat_id=555, username="mariya"):
        return {
            "message": {
                "chat": {"id": chat_id, "username": username},
                "text": text,
            }
        }

    def _post(self, update, secret="test-secret"):
        return self.client.post(
            reverse("accounts:telegram_webhook", args=[secret]),
            data=json.dumps(update),
            content_type="application/json",
        )

    @override_settings(TELEGRAM_WEBHOOK_SECRET="test-secret", TELEGRAM_BOT_TOKEN="")
    def test_start_with_code_links_the_chat(self):
        account = TelegramAccount.for_user(self.user)
        response = self._post(self._update(f"/start {account.link_code}"))
        self.assertEqual(response.status_code, 200)

        account.refresh_from_db()
        self.assertEqual(account.chat_id, "555")
        self.assertEqual(account.username, "mariya")
        self.assertIsNotNone(account.linked_at)

    @override_settings(TELEGRAM_WEBHOOK_SECRET="test-secret", TELEGRAM_BOT_TOKEN="")
    def test_wrong_secret_is_refused(self):
        """Адрес вебхука может утечь из логов — секрет проверяем всегда."""
        account = TelegramAccount.for_user(self.user)
        response = self._post(self._update(f"/start {account.link_code}"), secret="не-тот")
        self.assertEqual(response.status_code, 403)
        account.refresh_from_db()
        self.assertFalse(account.is_linked)

    @override_settings(TELEGRAM_WEBHOOK_SECRET="test-secret", TELEGRAM_BOT_TOKEN="")
    def test_one_chat_belongs_to_one_account(self):
        """Иначе чужие уведомления придут тому, кто открыл ссылку из переписки."""
        other = User.objects.create_user(email="other@example.com", password="pass-12345")
        first = TelegramAccount.for_user(self.user)
        second = TelegramAccount.for_user(other)

        self._post(self._update(f"/start {first.link_code}"))
        self._post(self._update(f"/start {second.link_code}"))

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertFalse(first.is_linked)
        self.assertTrue(second.is_linked)

    @override_settings(TELEGRAM_WEBHOOK_SECRET="test-secret", TELEGRAM_BOT_TOKEN="")
    def test_stop_unlinks_and_burns_the_old_code(self):
        account = TelegramAccount.for_user(self.user)
        old_code = account.link_code
        self._post(self._update(f"/start {old_code}"))
        self._post(self._update("/stop"))

        account.refresh_from_db()
        self.assertFalse(account.is_linked)
        self.assertNotEqual(account.link_code, old_code)

    @override_settings(TELEGRAM_WEBHOOK_SECRET="test-secret", TELEGRAM_BOT_TOKEN="")
    def test_unknown_code_does_not_link_anything(self):
        response = self._post(self._update("/start чужой-код"))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(TelegramAccount.objects.filter(chat_id="555").exists())

    def test_notifications_respect_the_switches(self):
        """Отключивший сообщения не должен получать их «в порядке исключения»."""
        account = TelegramAccount.for_user(self.user)
        account.chat_id = "555"
        account.notify_messages = False
        account.save()

        self.user.refresh_from_db()
        with mock.patch("apps.core.notify.send") as sent:
            notify.to_user(self.user, "текст", kind="message")
            sent.assert_not_called()

            notify.to_user(self.user, "текст", kind="stage")
            sent.assert_called_once()
