"""Публичный сайт: страницы открываются, заявка сохраняется, куки пишутся."""

import time
from decimal import Decimal
from unittest import mock

from django.core import signing
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from apps.catalog.models import ServiceModule
from apps.crm.models import Lead

from . import notify, views
from .forms import LeadForm
from .models import (
    CookieConsent,
    LegalDocument,
    PersonalDataConsent,
    PortfolioPhoto,
    PortfolioProject,
)


def stamp(seconds_ago=30):
    """Метка «форму открыли столько-то секунд назад».

    Живой человек её получает вместе со страницей; в тестах страницу
    никто не открывает, поэтому метку ставим руками.
    """
    return signing.dumps(int(time.time()) - seconds_ago, salt=LeadForm.TRAP_SALT)


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
            "opened_at": stamp(),
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
        # Ошибка должна быть видимой: ловушка стоит на невидимом поле,
        # и молча вернувшаяся форма — это тупик для живого человека,
        # которому поле заполнил браузер.
        self.assertContains(response, "Не удалось отправить заявку")

    def test_instant_submit_is_rejected(self):
        """Форму из девяти полей не заполняют за секунду."""
        response = self.client.post(reverse("public:contacts"), self._payload(opened_at=stamp(1)))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Lead.objects.exists())
        self.assertContains(response, "слишком быстро")

    def test_post_without_stamp_is_rejected(self):
        """Бот стучится прямо в адрес формы, не открывая страницу."""
        payload = self._payload()
        payload.pop("opened_at")
        response = self.client.post(reverse("public:contacts"), payload)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Lead.objects.exists())

    def test_form_page_carries_trap_and_stamp(self):
        page = self.client.get(reverse("public:contacts")).content.decode()
        self.assertIn('name="website"', page)
        self.assertIn('class="trap"', page)
        self.assertIn('name="opened_at"', page)

    def test_mailing_lands_in_spam_without_notification(self):
        """Рассылку не отбиваем, а откладываем — и молчим о ней.

        Цена ошибки несимметрична: пропущенная рассылка стоит минуты,
        отбитая заявка — заказчика.
        """
        with mock.patch.object(notify, "new_lead") as sent:
            response = self.client.post(
                reverse("public:contacts"),
                self._payload(message="Продвижение сайтов в топ, пишите https://spam.xyz"),
            )
        self.assertRedirects(response, reverse("public:thanks"))
        lead = Lead.objects.get()
        self.assertTrue(lead.is_spam)
        self.assertTrue(lead.spam_reason)
        sent.assert_not_called()
        self.assertFalse(Lead.objects.real().exists())

    def test_normal_lead_is_not_spam(self):
        """Ссылка на планировку — обычное дело, и заявку она не портит."""
        self.client.post(
            reverse("public:contacts"),
            self._payload(message="Вот планировка: https://disk.yandex.ru/i/abc"),
        )
        lead = Lead.objects.get()
        self.assertFalse(lead.is_spam, lead.spam_reason)


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
                    "opened_at": stamp(),
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

    def test_photos_stand_before_the_long_text(self):
        """На телефоне колонка с рассказом вставала первой, и до первого
        кадра человек прокручивал несколько экранов текста. Пришёл он
        смотреть, поэтому в разметке кадры идут раньше подробностей."""
        body = self.client.get(self.project.get_absolute_url()).content.decode()
        self.assertLess(body.index('class="mosaic"'), body.index('class="object__story"'))

    def test_long_parts_are_folded(self):
        """Задача, решение, результат и состав работ — под раскрытие."""
        from apps.catalog.models import ServiceModule

        self.project.task = "Три комнаты и ниша"
        self.project.solution = "Кухня-гостиная одним объёмом"
        self.project.save(update_fields=["task", "solution"])
        module = ServiceModule.objects.create(
            code="Z1", title="Рабочая документация", price=1, unit="шт", order=1
        )
        self.project.modules.add(module)

        body = self.client.get(self.project.get_absolute_url()).content.decode()
        self.assertIn("Как это делалось", body)
        self.assertIn("Что было сделано", body)
        # Текст остаётся на странице — он свёрнут, а не выброшен:
        # его читают поисковики и те, кому подробности нужны.
        self.assertIn("Кухня-гостиная одним объёмом", body)
        self.assertIn("Рабочая документация", body)

    def test_project_and_realization_dates(self):
        """Между проектом и стройкой бывает два года — и это норма,
        о которой заказчик не знает."""
        self.project.designed_on = "январь 2023"
        self.project.built_on = "март 2025"
        self.project.save(update_fields=["designed_on", "built_on"])

        response = self.client.get(self.project.get_absolute_url())
        self.assertContains(response, "январь 2023")
        self.assertContains(response, "март 2025")
        self.assertContains(response, "Реализация")

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
        """Пустая «Пресса» говорит громче, чем её отсутствие."""
        from .models import PressMention

        body = self.client.get(reverse("public:home")).content.decode()
        self.assertNotIn("Меня зовут писать", body)

        PressMention.objects.create(outlet="Красивые дома", title="Квартира с характером")
        body = self.client.get(reverse("public:home")).content.decode()
        self.assertIn("Меня зовут писать", body)
        self.assertIn("Квартира с характером", body)

    def test_publications_page_shows_the_issue_and_reading(self):
        """Свой файл надёжнее чужой ссылки: издания переезжают."""
        from .models import PressMention

        item = PressMention.objects.create(
            outlet="ДОМ снаружи и внутри",
            issue="№273, август 2026",
            title="Как офактурить интерьер",
            url="https://example.com/dom273",
        )
        response = self.client.get(reverse("public:publications"))
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn("№273, август 2026", body)
        self.assertIn("Как офактурить интерьер", body)
        # Файла нет — читают на сайте издания.
        self.assertIn("https://example.com/dom273", body)
        self.assertEqual(item.read_url, "https://example.com/dom273")

    def test_publications_are_not_a_menu_item(self):
        """Шестая ссылка в шапке размывает первые пять: сюда приходят
        с главной, по обложке, и из подвала."""
        from .models import PressMention

        PressMention.objects.create(outlet="ДОМ", title="Как офактурить интерьер")
        body = self.client.get(reverse("public:home")).content.decode()
        nav = body[body.index('<nav class="nav"'):body.index("</nav>")]
        self.assertNotIn(reverse("public:publications"), nav)
        self.assertIn(reverse("public:publications"), body)

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


class EnvFileTests(TestCase):
    """Чтение .env: файл один, а читают его двое — systemd и manage.py."""

    def _write(self, text):
        import tempfile
        from pathlib import Path

        path = Path(tempfile.mkdtemp()) / ".env"
        path.write_text(text, encoding="utf-8")
        return path

    def test_last_line_wins(self):
        """Ключ, записанный дважды, берётся по последней строке.

        Ровно так его понимает systemd. Разойдись поведение — служба
        работала бы с одним значением, а проверка в терминале
        показывала бы другое, и найти это почти невозможно.
        """
        from config.settings import read_env_file

        values = read_env_file(self._write("EMAIL_HOST_PASSWORD=\nEMAIL_HOST_PASSWORD=секрет\n"))
        self.assertEqual(values["EMAIL_HOST_PASSWORD"], "секрет")

    def test_quotes_belong_to_the_record(self):
        from config.settings import read_env_file

        values = read_env_file(self._write('DEFAULT_FROM_EMAIL="Дарья <a@b.ru>"\n'))
        self.assertEqual(values["DEFAULT_FROM_EMAIL"], "Дарья <a@b.ru>")

    def test_comments_and_junk_are_skipped(self):
        from config.settings import read_env_file

        values = read_env_file(self._write("# комментарий\n\nПРОСТО СТРОКА\nA=1\n"))
        self.assertEqual(values, {"A": "1"})


class HeroAndLogoTests(TestCase):
    """Знак, рисунок и страница «не найдено»."""

    @classmethod
    def setUpTestData(cls):
        call_command("seed_catalog", verbosity=0)
        call_command("seed_legal", verbosity=0)

    def test_hero_can_be_switched_on(self):
        """Картинка — кнопка: свет включается и с клавиатуры тоже."""
        body = self.client.get(reverse("public:home")).content.decode()
        self.assertIn("data-art", body)
        self.assertIn('aria-pressed="false"', body)
        # Без JS кнопка ничего не делает — и в обход клавиатурой не лезет.
        self.assertIn('tabindex="-1"', body)

    def test_arch_and_cat_are_in_the_picture(self):
        body = self.client.get(reverse("public:home")).content.decode()
        self.assertIn("art__cat", body)
        self.assertIn("art__stage", body)
        self.assertIn("art__leaves", body)

    def test_not_found_page_offers_open_doors(self):
        """Код ошибки крупными цифрами человеку ничего не даёт."""
        response = self.client.get("/net-takoy-stranicy/")
        self.assertEqual(response.status_code, 404)
        body = response.content.decode()
        self.assertIn("Такой комнаты в проекте нет", body)
        self.assertIn(reverse("public:portfolio"), body)
        self.assertIn(reverse("public:contacts"), body)


class ProcessBlocksTests(TestCase):
    """Три блока 30 / 40 / 30 — одни и те же на сайте и в кабинете."""

    @classmethod
    def setUpTestData(cls):
        call_command("seed_catalog", verbosity=0)
        call_command("seed_legal", verbosity=0)

    def test_how_page_shows_three_arches(self):
        response = self.client.get(reverse("public:how"))
        blocks = response.context["blocks"]
        self.assertEqual([b["share"] for b in blocks], [30, 40, 30])
        self.assertEqual([len(b["stages"]) for b in blocks], [3, 3, 2])
        for block in blocks:
            self.assertContains(response, block["title"])

    def test_cabinet_and_site_share_one_definition(self):
        """Две копии разбивки однажды разъедутся, и стороны увидят разное."""
        from apps.cabinet import services
        from apps.core.models import STAGE_BLOCKS

        self.assertIs(services.STAGE_BLOCKS, STAGE_BLOCKS)

    def test_stage_with_unknown_number_lands_in_the_last_block(self):
        from apps.core.models import StageNorm, group_by_block

        stages = list(StageNorm.objects.all())
        stages.append(StageNorm(number=42, title="Особый"))
        blocks = group_by_block(stages)
        self.assertEqual(sum(len(b["stages"]) for b in blocks), len(stages))
        self.assertEqual(blocks[-1]["stages"][-1].title, "Особый")


class EmptyRoomTests(TestCase):
    """Пустая комната в конструкторе — ответ на «за что я плачу»."""

    @classmethod
    def setUpTestData(cls):
        call_command("seed_catalog", verbosity=0)
        call_command("seed_legal", verbosity=0)

    def test_constructor_explains_what_stays(self):
        body = self.client.get(reverse("public:constructor")).content.decode()
        self.assertIn("house__bare", body)
        self.assertIn("Пустая комната", body)
        self.assertIn("кроме пола", body)


class PhotoOrderingTests(TestCase):
    """Порядок кадров задаётся перетаскиванием, номера — про запас."""

    @classmethod
    def setUpTestData(cls):
        from apps.accounts.models import Role, User

        cls.admin = User.objects.create_superuser(
            email="root@example.com", password="root-pass-123", role=Role.OWNER
        )
        cls.project = PortfolioProject.objects.create(title="Квартира", is_published=True)
        for i, caption in enumerate(("Кухня", "Спальня", "Санузел"), start=1):
            PortfolioPhoto.objects.create(
                project=cls.project, image=f"portfolio/{i}.jpg", caption=caption, order=i * 10
            )

    def test_admin_page_carries_the_sorter(self):
        """Без скрипта и миниатюр перетаскивание бессмысленно: в строке
        видно имя файла вроде «IMG_4417.jpg», а раскладывают картинки."""
        self.client.force_login(self.admin)
        body = self.client.get(
            reverse("admin:core_portfolioproject_change", args=[self.project.pk])
        ).content.decode()
        self.assertIn("admin_sort.js", body)
        self.assertIn("admin_sort.css", body)
        self.assertIn("photo-thumb", body)
        # Номера остаются: без JavaScript и для точной правки они
        # единственный способ.
        self.assertIn('name="photos-0-order"', body)

    def test_order_decides_the_gallery(self):
        first = self.project.photos.get(caption="Санузел")
        first.order = 1
        first.save(update_fields=["order"])
        self.assertEqual(self.project.gallery[0].caption, "Санузел")
