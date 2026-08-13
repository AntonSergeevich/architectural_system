"""Публичный сайт: страницы открываются, заявка сохраняется, куки пишутся."""

from decimal import Decimal
from unittest import mock

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from apps.catalog.models import ServiceModule
from apps.crm.models import Lead

from . import notify, views
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

    def test_login_link_is_visible_to_guests(self):
        """Доступ в кабинет получает каждый заказчик — дверь должна быть видна.

        Пока ссылка показывалась только вошедшим, адрес страницы входа
        приходилось диктовать голосом.
        """
        body = self.client.get(reverse("public:home")).content.decode()
        self.assertIn(reverse("accounts:login"), body)

    def test_legal_documents_published(self):
        for kind in ["privacy", "consent", "cookies", "offer"]:
            with self.subTest(kind=kind):
                response = self.client.get(reverse("public:legal", args=[kind]))
                self.assertEqual(response.status_code, 200)

    def test_constructor_starts_with_the_foundation_only(self):
        """Стартовое состояние — только пол, комнату собирают с нуля.

        Обязательные модули всё равно посчитаны: убрать обмер, бриф
        и планировку нельзя, без них проекта не существует. А всё,
        от чего можно отказаться, изначально снято.
        """
        response = self.client.get(reverse("public:constructor"))
        self.assertContains(response, "Соберите свою комнату")

        calc = response.context["calc"]
        self.assertGreater(calc.design_total, 0)
        self.assertEqual(calc.realization_total, 0)
        self.assertTrue(all(line.module.is_required for line in calc.lines))

    def test_optional_modules_are_offered_as_warnings_from_the_start(self):
        """Чего не хватает — видно сразу, а не после снятия галочки."""
        response = self.client.get(reverse("public:constructor"))
        missing = {m.code for m in response.context["calc"].missing}
        self.assertIn("A7", missing)
        self.assertIn("B1", missing)

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


class TemplateHygieneTests(TestCase):
    """Комментарии не должны утекать на страницу.

    Django понимает `{# … #}` только в пределах одной строки: закрывающую
    скобку он ищет до конца строки и, не найдя, печатает всё как обычный
    текст. Многострочный комментарий поэтому выводится посетителю целиком —
    ровно это и случилось в шапке.
    """

    @classmethod
    def setUpTestData(cls):
        call_command("seed_catalog", verbosity=0)
        call_command("seed_legal", verbosity=0)

    def test_no_template_syntax_leaks_into_pages(self):
        pages = [
            "public:home", "public:constructor", "public:about", "public:services",
            "public:how", "public:objections", "public:contacts",
        ]
        for name in pages:
            with self.subTest(page=name):
                body = self.client.get(reverse(name)).content.decode()
                for leak in ["{#", "#}", "{% comment", "{% endcomment", "{{ ", "{% if", "{% for"]:
                    self.assertNotIn(leak, body, f"{name}: на страницу утёк {leak!r}")

    def test_source_has_no_multiline_hash_comments(self):
        import pathlib
        import re

        # Однострочные {# … #} допустимы, многострочные — нет.
        broken = re.compile(r"\{#(?![^\n#]*#\})")
        offenders = [
            str(path)
            for path in pathlib.Path("templates").rglob("*.html")
            if broken.search(path.read_text(encoding="utf-8"))
        ]
        self.assertEqual(offenders, [], "многострочные {# #} печатаются как текст")


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

    def test_answers_are_readable(self):
        """В кабинете анкета — это вопрос и ответ, а не имена полей формы.

        «has_builders False» читается как ошибка, хотя это законный ответ
        «своей бригады нет».
        """
        self.client.post(reverse("public:contacts"), self._payload(keys_received="on"))
        rows = Lead.objects.get().answers_display
        shown = {row["label"]: row["value"] for row in rows}

        self.assertIn("Ключи получены", shown)
        self.assertEqual(shown["Ключи получены"], "да")
        self.assertEqual(shown["Своя бригада"], "нет")
        for row in rows:
            self.assertNotIn("_", row["label"], f"осталось имя поля: {row['label']}")
            self.assertNotIn(row["value"], (True, False), "осталось питоновское значение")

    def test_honeypot_blocks_bots(self):
        response = self.client.post(reverse("public:contacts"), self._payload(website="spam"))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Lead.objects.exists())


class ShelfTests(TestCase):
    """Группа взаимоисключающих услуг — один блок, а не несколько.

    Место в комнате одно: потолок один, окно одно. Три отдельных блока
    на складе означали, что человек кладёт «выезды», видит потолок,
    кладёт «надзор» — снова тот же потолок, а как убрать конкретный
    блок, не понимает вовсе.
    """

    @classmethod
    def setUpTestData(cls):
        call_command("seed_catalog", verbosity=0)
        call_command("seed_legal", verbosity=0)

    def test_group_is_one_draggable_block(self):
        response = self.client.get(reverse("public:constructor"))
        sections = response.context["realization_sections"]
        roof = [s for s in sections if s["group"] and s["group"].house_part == "roof"]
        self.assertEqual(len(roof), 1, "потолок должен быть одной секцией")
        self.assertGreater(len(roof[0]["modules"]), 1, "форматов надзора несколько")
        self.assertIn(roof[0]["active"], roof[0]["modules"])

    def test_one_house_part_never_has_two_draggable_blocks(self):
        """Иначе на один слот в комнате претендуют две карточки склада.

        Обязательные модули не в счёт: их не перетаскивают и не снимают,
        фундамент уложен изначально.
        """
        response = self.client.get(reverse("public:constructor"))
        parts = []
        for key in ("design_sections", "realization_sections", "extra_sections"):
            for section in response.context[key]:
                module = section.get("active") or section["modules"][0]
                if module.house_part and not module.is_required:
                    parts.append(module.house_part)
        self.assertEqual(len(parts), len(set(parts)), f"на один элемент дома два блока: {parts}")

    def test_every_module_keeps_its_checkbox(self):
        """Без JavaScript расчёт делает форма, значит галочки нужны все."""
        body = self.client.get(reverse("public:constructor")).content.decode()
        for module in ServiceModule.objects.filter(is_active=True):
            self.assertIn(f'value="{module.pk}"', body)


class TelegramNotifyTests(TestCase):
    """Уведомление не имеет права уронить заявку."""

    @classmethod
    def setUpTestData(cls):
        call_command("seed_catalog", verbosity=0)
        call_command("seed_legal", verbosity=0)

    def test_disabled_without_settings(self):
        with self.settings(TELEGRAM_BOT_TOKEN="", TELEGRAM_CHAT_ID=""):
            self.assertFalse(notify.enabled())
            self.assertFalse(notify.send("привет"))

    def test_lead_is_saved_even_if_telegram_falls(self):
        def boom(_lead):
            raise RuntimeError("телеграм лёг")

        with mock.patch.object(views.notify, "new_lead", boom):
            response = self.client.post(
                reverse("public:contacts"),
                {
                    "name": "Мария",
                    "phone": "8 913 000 00 02",
                    "area": "60",
                    "rooms": 2,
                    "personal_data_consent": "on",
                },
            )
        self.assertRedirects(response, reverse("public:thanks"))
        self.assertTrue(Lead.objects.exists())

    def test_message_escapes_user_text(self):
        self.assertEqual(notify.escape("<b>Вася</b>"), "&lt;b&gt;Вася&lt;/b&gt;")


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


class FilterTests(TestCase):
    """Мелочи текста. «21 рабочих дней» на экране заказчика читается
    как небрежность — а небрежность в мелочах переносят на работу."""

    def test_workdays_uses_all_three_russian_forms(self):
        from .templatetags.richtext import workdays

        cases = {
            1: "1 рабочий день",
            2: "2 рабочих дня",
            5: "5 рабочих дней",
            11: "11 рабочих дней",
            14: "14 рабочих дней",
            21: "21 рабочий день",
            22: "22 рабочих дня",
            25: "25 рабочих дней",
        }
        for number, expected in cases.items():
            with self.subTest(number=number):
                self.assertEqual(workdays(number), expected)


class PortfolioObjectTests(TestCase):
    """Страница объекта: обложка, мозаика, видеоотзыв."""

    @classmethod
    def setUpTestData(cls):
        from .models import PortfolioPhoto, PortfolioProject

        cls.project = PortfolioProject.objects.create(
            title="Квартира на Мира", city="Красноярск", year=2025, is_published=True
        )
        cls.first = PortfolioPhoto.objects.create(
            project=cls.project, image="portfolio/1.jpg", order=1, caption="Гостиная"
        )
        cls.chosen = PortfolioPhoto.objects.create(
            project=cls.project, image="portfolio/2.jpg", order=2, is_cover=True, caption="Кухня"
        )
        cls.wide = PortfolioPhoto.objects.create(
            project=cls.project, image="portfolio/3.jpg", order=3, is_wide=True
        )

    def test_cover_is_the_chosen_photo_not_the_first_one(self):
        """Порядок кадров задаётся под рассказ, обложка — под первый взгляд."""
        self.assertEqual(self.project.cover, self.chosen)
        self.assertEqual(self.project.gallery[0], self.chosen)
        self.assertEqual(len(self.project.gallery), 3)

    def test_without_a_chosen_cover_the_first_photo_is_used(self):
        self.chosen.is_cover = False
        self.chosen.save(update_fields=["is_cover"])
        self.assertEqual(self.project.cover, self.first)

    def test_page_shows_mosaic_and_zoom(self):
        response = self.client.get(self.project.get_absolute_url())
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn("mosaic", body)
        self.assertIn('data-lightbox', body)
        self.assertIn("mosaic__item--wide", body)

    def test_client_block_hidden_without_consent(self):
        """Ни имени, ни слов, ни видео — пока заказчик не разрешил."""
        self.project.client_name = "Мария"
        self.project.client_quote = "Всё понравилось"
        self.project.save()
        body = self.client.get(self.project.get_absolute_url()).content.decode()
        self.assertNotIn("Всё понравилось", body)

        self.project.client_consent = True
        self.project.save(update_fields=["client_consent"])
        body = self.client.get(self.project.get_absolute_url()).content.decode()
        self.assertIn("Всё понравилось", body)


class PressAndSocialsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_catalog", verbosity=0)
        call_command("seed_legal", verbosity=0)

    def test_press_section_appears_only_when_there_is_press(self):
        from .models import PressMention

        body = self.client.get(reverse("public:home")).content.decode()
        self.assertNotIn("Обо мне пишут", body)

        PressMention.objects.create(outlet="Красивые дома", title="Квартира с характером")
        body = self.client.get(reverse("public:home")).content.decode()
        self.assertIn("Обо мне пишут", body)
        self.assertIn("Квартира с характером", body)

    def test_instagram_is_published_with_the_legal_notice(self):
        """Упоминание Instagram без пометки — нарушение, а не мелочь."""
        from .models import SiteSettings

        site = SiteSettings.get()
        site.instagram = "https://instagram.com/example"
        site.save()

        body = self.client.get(reverse("public:home")).content.decode()
        self.assertIn("instagram.com/example", body)
        self.assertIn("экстремистской организацией", body)

    def test_no_notice_when_there_is_no_instagram(self):
        body = self.client.get(reverse("public:home")).content.decode()
        self.assertNotIn("экстремистской организацией", body)


class ComplexityTests(TestCase):
    """Коэффициент сложности: характер интерьера плюс обстоятельства объекта.

    Учёт сложности включается галочкой в «Ценах» и по умолчанию выключен:
    решение «считать ли сложность» — Дарьино, а не программиста.
    """

    @classmethod
    def setUpTestData(cls):
        from apps.catalog.models import PricingSettings

        call_command("seed_catalog", verbosity=0)
        pricing = PricingSettings.get()
        pricing.complexity_enabled = True
        pricing.save(update_fields=["complexity_enabled"])

    def test_conditions_add_up_to_the_style_factor(self):
        """Складываются, а не перемножаются: так коэффициент можно
        объяснить вслух — «характер 1.15, старый фонд плюс 0.15»."""
        from apps.catalog.models import ComplexityFactor
        from apps.catalog.pricing import calculate

        style = ComplexityFactor.objects.get(code="character")
        old_fund = ComplexityFactor.objects.get(code="old")
        started = ComplexityFactor.objects.get(code="started")

        plain = calculate(area=80, complexity=style)
        harder = calculate(area=80, complexity=style, conditions=[old_fund, started])

        self.assertEqual(plain.factor, style.factor)
        self.assertEqual(harder.factor, style.factor + old_fund.factor + started.factor)
        self.assertGreater(harder.design_total, plain.design_total)

    def test_constructor_asks_about_the_object(self):
        response = self.client.get(reverse("public:constructor"))
        self.assertContains(response, "Что осложняет объект")
        self.assertContains(response, "Ремонт уже начат без проекта")

    def test_calculation_api_takes_conditions(self):
        from apps.catalog.models import ComplexityFactor

        module = ServiceModule.objects.filter(is_active=True, unit="sqm").first()
        old_fund = ComplexityFactor.objects.get(code="old")

        base = self.client.post(
            reverse("public:calculate"), {"area": "80", "rooms": 2, "modules": [module.pk]}
        ).json()["calc"]
        harder = self.client.post(
            reverse("public:calculate"),
            {"area": "80", "rooms": 2, "modules": [module.pk], "conditions": [old_fund.pk]},
        ).json()["calc"]
        self.assertGreater(harder["design_total"], base["design_total"])
