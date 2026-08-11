"""Публичный сайт: страницы открываются, заявка сохраняется, куки пишутся."""

from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from apps.catalog.models import ServiceModule
from apps.crm.models import Lead

from . import views
from .models import CookieConsent, LegalDocument, PersonalDataConsent


class PublicPagesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_catalog", verbosity=0)
        call_command("seed_legal", verbosity=0)

    def test_pages_open(self):
        for name in [
            "public:home", "public:about", "public:services", "public:constructor",
            "public:how", "public:objections", "public:portfolio", "public:contacts",
            "public:articles",
        ]:
            with self.subTest(page=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)

    def test_legal_documents_published(self):
        for kind in ["privacy", "consent", "cookies", "offer"]:
            with self.subTest(kind=kind):
                response = self.client.get(reverse("public:legal", args=[kind]))
                self.assertEqual(response.status_code, 200)

    def test_constructor_starts_with_assembled_house(self):
        """Стартовое состояние — «Под ключ»: клиент разбирает, а не собирает."""
        response = self.client.get(reverse("public:constructor"))
        self.assertContains(response, "Соберите свой дом")
        self.assertGreater(response.context["calc"].design_total, 0)
        self.assertGreater(response.context["calc"].realization_total, 0)

    def test_constructor_works_without_javascript(self):
        modules = ServiceModule.objects.filter(is_active=True, unit="sqm")[:2]
        response = self.client.post(
            reverse("public:constructor"),
            {"area": "80", "rooms": 3, "modules": [m.pk for m in modules]},
        )
        self.assertEqual(response.status_code, 200)
        self.assertGreater(response.context["calc"].design_total, 0)

    def test_calculate_api(self):
        module = ServiceModule.objects.filter(is_active=True, unit="sqm").first()
        response = self.client.post(
            reverse("public:calculate"), {"area": "100", "rooms": 2, "modules": [module.pk]}
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertIn("design_total", payload["calc"])

    def test_saved_quote_gets_its_own_link(self):
        """Именно ссылка заменяет PDF: один адрес, всё внутри."""
        module = ServiceModule.objects.filter(is_active=True, unit="sqm").first()
        response = self.client.post(
            reverse("public:save_quote"), {"area": "70", "rooms": 2, "modules": [module.pk]}
        )
        self.assertEqual(response.status_code, 200)
        url = response.json()["url"]
        self.assertEqual(self.client.get(url).status_code, 200)


class HeroCalculatorTests(TestCase):
    """Мини-расчёт на главной обязан совпадать с конструктором.

    Два разных числа для одной квартиры — это ровно тот разговор,
    от которого система должна избавлять, только теперь ещё и внутри сайта.
    """

    @classmethod
    def setUpTestData(cls):
        call_command("seed_catalog", verbosity=0)

    def test_hero_numbers_match_the_constructor(self):
        from decimal import Decimal

        from apps.catalog.pricing import calculate, default_preset

        hero = views._hero_pricing()
        area = Decimal("84")
        expected = Decimal(hero["per_sqm"]) * area + Decimal(hero["fixed"])

        preset = default_preset()
        calc = calculate(area=area, modules=list(preset.modules.filter(is_active=True)))
        self.assertEqual(calc.design_total, expected)

    def test_small_area_rule_is_exposed_to_the_hero(self):
        hero = views._hero_pricing()
        self.assertTrue(hero["small_enabled"])
        self.assertEqual(hero["small_price"], 80000)
        self.assertEqual(hero["small_threshold"], 20.0)

    def test_area_from_link_prefills_the_constructor(self):
        """С главной площадь уезжает ссылкой — вводить второй раз незачем."""
        response = self.client.get(reverse("public:constructor"), {"area": "15"})
        self.assertEqual(response.context["area"], Decimal("15"))
        self.assertIsNotNone(response.context["calc"].fixed_design_price)

    def test_broken_area_in_link_does_not_break_the_page(self):
        for value in ["abc", "-5", "99999999", ""]:
            with self.subTest(value=value):
                response = self.client.get(reverse("public:constructor"), {"area": value})
                self.assertEqual(response.status_code, 200)


class LeadTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_catalog", verbosity=0)
        call_command("seed_legal", verbosity=0)

    def _payload(self, **extra):
        data = {
            "name": "Мария",
            "phone": "8 913 000 00 01",
            "area": "84",
            "rooms": 3,
            "message": "хочу яркий интерьер",
            "personal_data_consent": "on",
        }
        data.update(extra)
        return data

    def test_lead_created_with_next_action(self):
        """Заявка без даты следующего шага — это и есть потерянная заявка."""
        response = self.client.post(reverse("public:contacts"), self._payload())
        self.assertRedirects(response, reverse("public:thanks"))

        lead = Lead.objects.get()
        self.assertEqual(lead.client.phone, "+79130000001")
        self.assertTrue(lead.next_action)
        self.assertIsNotNone(lead.next_action_at)
        self.assertEqual(lead.estate.area, Decimal("84"))

    def test_consent_is_recorded_with_document_version(self):
        self.client.post(reverse("public:contacts"), self._payload())
        consent = PersonalDataConsent.objects.get()
        version = LegalDocument.objects.get(kind="consent").version
        self.assertEqual(consent.document_version, version)

    def test_consent_is_required(self):
        response = self.client.post(
            reverse("public:contacts"), self._payload(personal_data_consent="")
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Lead.objects.exists())

    def test_contact_required(self):
        response = self.client.post(
            reverse("public:contacts"), self._payload(phone="", email="", messenger="")
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Lead.objects.exists())

    def test_honeypot_blocks_bots(self):
        response = self.client.post(reverse("public:contacts"), self._payload(website="spam"))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Lead.objects.exists())


class CookieTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_legal", verbosity=0)

    def test_banner_shown_until_choice_made(self):
        response = self.client.get(reverse("public:home"))
        self.assertTrue(response.context["show_cookie_banner"])

    def test_choice_is_logged_and_stored_in_cookie(self):
        """Согласие нужно доказывать, а доказать можно только записанное."""
        response = self.client.post(
            reverse("public:cookie_consent"), {"choice": "necessary"}, follow=True
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.cookies["cookie_consent"].value, "necessary")

        record = CookieConsent.objects.get()
        self.assertEqual(record.choice, "necessary")
        self.assertFalse(record.analytics)
        self.assertEqual(record.policy_version, LegalDocument.objects.get(kind="cookies").version)

    def test_unknown_choice_rejected(self):
        response = self.client.post(reverse("public:cookie_consent"), {"choice": "everything"})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(CookieConsent.objects.exists())
