"""Расчёт стоимости — то место, где ошибка обходится дороже всего."""

from datetime import datetime
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.core.utils import normalize_phone, working_deadline

from .models import ComplexityFactor, ModuleGroup, Preset, ServiceModule, Unit
from .pricing import calculate


class PricingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.simple = ComplexityFactor.objects.create(
            code="laconic", title="Лаконичный", factor=Decimal("1.00"), is_default=True
        )
        cls.author = ComplexityFactor.objects.create(
            code="author", title="Авторский", factor=Decimal("1.30")
        )
        cls.windows = ModuleGroup.objects.create(code="windows", title="Окна")

        cls.survey = ServiceModule.objects.create(
            code="A1", title="Обмер", unit=Unit.FIXED, price=Decimal("8000"),
            is_required=True, affected_by_complexity=False, house_part="foundation",
        )
        cls.plans = ServiceModule.objects.create(
            code="A3", title="Планировки", unit=Unit.SQM, price=Decimal("700"),
            is_required=True, house_part="foundation",
        )
        cls.render3d = ServiceModule.objects.create(
            code="A6c", title="3D", unit=Unit.SQM, price=Decimal("900"),
            group=cls.windows, house_part="windows", warning="Картинки не будет",
        )
        cls.neuro = ServiceModule.objects.create(
            code="A6b", title="Нейро", unit=Unit.SQM, price=Decimal("650"),
            group=cls.windows, house_part="windows",
        )
        cls.drawings = ServiceModule.objects.create(
            code="A7", title="Чертежи", unit=Unit.SQM, price=Decimal("900"),
            house_part="walls", warning="Бригада без документации",
        )
        cls.partial = ServiceModule.objects.create(
            code="A7p", title="Чертежи частично", unit=Unit.CUSTOM, price=Decimal("0"),
            house_part="walls",
        )
        cls.supervision = ServiceModule.objects.create(
            code="B1", title="Надзор", unit=Unit.MONTH, price=Decimal("50000"),
            block="realization", affected_by_complexity=False, house_part="roof",
        )
        cls.procurement = ServiceModule.objects.create(
            code="B3", title="Комплектация", unit=Unit.STAGE, price=Decimal("60000"),
            block="realization", affected_by_complexity=False, house_part="light",
        )

    def test_square_meter_modules_multiply_by_area(self):
        calc = calculate(area=100, complexity=self.simple, modules=[self.render3d])
        amounts = {line.module.code: line.amount for line in calc.lines}
        self.assertEqual(amounts["A6c"], Decimal("90000"))
        self.assertEqual(amounts["A3"], Decimal("70000"))

    def test_required_modules_are_always_added(self):
        """Фундамент снять нельзя — даже если его не передали в набор."""
        calc = calculate(area=50, complexity=self.simple, modules=[])
        codes = {line.module.code for line in calc.lines}
        self.assertIn("A1", codes)
        self.assertIn("A3", codes)

    def test_fixed_price_ignores_area(self):
        small = calculate(area=30, complexity=self.simple, modules=[])
        big = calculate(area=300, complexity=self.simple, modules=[])
        fixed = lambda calc: next(l.amount for l in calc.lines if l.module.code == "A1")
        self.assertEqual(fixed(small), fixed(big))

    def test_complexity_applies_only_where_allowed(self):
        calc = calculate(area=100, complexity=self.author, modules=[self.render3d])
        amounts = {line.module.code: line.amount for line in calc.lines}
        # 900 × 100 × 1.3
        self.assertEqual(amounts["A6c"], Decimal("117000"))
        # обмер от сложности не зависит
        self.assertEqual(amounts["A1"], Decimal("8000"))

    def test_custom_price_is_none_not_zero(self):
        """Индивидуальный расчёт не должен превращаться в ноль в итоге."""
        calc = calculate(area=100, complexity=self.simple, modules=[self.partial])
        line = next(l for l in calc.lines if l.module.code == "A7p")
        self.assertIsNone(line.amount)
        self.assertTrue(calc.has_custom)

    def test_subscription_modules_use_quantity(self):
        calc = calculate(
            area=100, complexity=self.simple,
            modules=[self.supervision, self.procurement], months=4, stages=2,
        )
        amounts = {line.module.code: line.amount for line in calc.lines}
        self.assertEqual(amounts["B1"], Decimal("200000"))
        self.assertEqual(amounts["B3"], Decimal("120000"))

    def test_totals_split_by_block(self):
        calc = calculate(
            area=100, complexity=self.simple, modules=[self.render3d, self.supervision], months=6
        )
        # Разовое и абонентское не складываются в одно число: сумма получилась бы
        # пугающей и при этом неправдой.
        self.assertEqual(calc.design_total, Decimal("70000") + Decimal("90000") + Decimal("8000"))
        self.assertEqual(calc.realization_total, Decimal("300000"))

    def test_missing_modules_collected_for_warnings(self):
        calc = calculate(area=100, complexity=self.simple, modules=[self.render3d])
        missing = {m.code for m in calc.missing}
        self.assertIn("A7", missing)
        self.assertNotIn("A6c", missing)

    def test_full_design_matches_market_ceiling(self):
        """Сумма модулей «за м²» в полном проекте — верхняя планка рынка."""
        per_sqm = sum(
            m.price for m in [self.plans, self.render3d, self.drawings]
        )
        self.assertEqual(per_sqm, Decimal("2500"))


class PresetTests(TestCase):
    def test_default_preset_is_the_assembled_house(self):
        module = ServiceModule.objects.create(code="X", title="X", unit=Unit.SQM, price=Decimal("1"))
        preset = Preset.objects.create(code="turnkey", title="Под ключ", is_default=True)
        preset.modules.add(module)
        from .pricing import default_preset

        self.assertEqual(default_preset(), preset)


class UtilsTests(TestCase):
    def test_phone_normalisation(self):
        for raw in ["89130322908", "+7 913 032-29-08", "8 (913) 032 29 08", "79130322908"]:
            self.assertEqual(normalize_phone(raw), "+79130322908")

    def test_reply_deadline_skips_weekend(self):
        """Вопрос вечером пятницы получает срок в понедельник, а не в субботу.

        Ровно это и означает «отвечу в течение суток в рабочее время».
        """
        tz = timezone.get_current_timezone()
        friday_evening = datetime(2026, 8, 14, 18, 0, tzinfo=tz)  # пятница
        deadline = working_deadline(friday_evening, hours=9, day_start=10, day_end=19)
        self.assertEqual(deadline.weekday(), 0)  # понедельник

    def test_reply_deadline_within_same_day(self):
        tz = timezone.get_current_timezone()
        tuesday_morning = datetime(2026, 8, 11, 11, 0, tzinfo=tz)
        deadline = working_deadline(tuesday_morning, hours=3, day_start=10, day_end=19)
        self.assertEqual(deadline.hour, 14)
        self.assertEqual(deadline.day, 11)

    def test_request_before_opening_starts_at_opening(self):
        tz = timezone.get_current_timezone()
        early = datetime(2026, 8, 11, 7, 0, tzinfo=tz)
        deadline = working_deadline(early, hours=2, day_start=10, day_end=19)
        self.assertEqual(deadline.hour, 12)
