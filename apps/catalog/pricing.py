"""Расчёт стоимости.

Одна функция считает и то, что видно в конструкторе, и то, что попадает
в коммерческое предложение. Двух реализаций быть не должно: расхождение
между «посчитал сайт» и «выставила Дарья» — это ровно тот разговор,
которого система должна избавить.
"""

from dataclasses import dataclass, field
from decimal import Decimal

from .models import Block, ComplexityFactor, Preset, PricingSettings, ServiceModule, Unit

# Комплектация идёт помесячно и параллельно стройке, поэтому её срок
# по умолчанию совпадает со сроком надзора.


@dataclass
class Line:
    module: ServiceModule
    quantity: Decimal
    amount: Decimal | None  # None — индивидуальный расчёт

    @property
    def is_custom(self):
        return self.amount is None


@dataclass
class Calculation:
    area: Decimal
    rooms: int
    complexity: ComplexityFactor | None
    months: int
    lines: list[Line] = field(default_factory=list)
    missing: list[ServiceModule] = field(default_factory=list)
    # Фикс для маленьких помещений: проектирование стоит ровно столько,
    # сколько бы ни насчиталось по квадратам.
    fixed_design_price: Decimal | None = None
    settings: PricingSettings | None = None

    @property
    def factor(self):
        if self.settings and not self.settings.complexity_enabled:
            return Decimal("1")
        return self.complexity.factor if self.complexity else Decimal("1")

    def _sum(self, block):
        return sum(
            (line.amount for line in self.lines if line.module.block == block and line.amount),
            Decimal("0"),
        )

    @property
    def design_total(self):
        if self.fixed_design_price is not None:
            return self.fixed_design_price
        return self._sum(Block.DESIGN)

    @property
    def realization_total(self):
        return self._sum(Block.REALIZATION)

    @property
    def extra_total(self):
        return self._sum(Block.EXTRA)

    @property
    def grand_total(self):
        """Всё вместе, включая надзор за весь срок стройки.

        Пятьдесят тысяч в месяц выглядят небольшой суммой ровно до тех пор,
        пока их не умножили на срок стройки. Показать это честнее, чем
        оставить заказчика самого умножать — и куда лучше, чем узнать
        об этом на восьмом месяце.
        """
        return self.design_total + self.realization_total + self.extra_total

    @property
    def has_custom(self):
        return any(line.is_custom for line in self.lines)

    @property
    def working_days(self):
        return sum(line.module.duration_days for line in self.lines)

    @property
    def monthly_lines(self):
        return [line for line in self.lines if line.module.unit == Unit.MONTH and line.amount]

    def as_dict(self):
        """Для JSON-ответа конструктору."""
        return {
            "area": str(self.area),
            "rooms": self.rooms,
            "months": self.months,
            "complexity": self.complexity.code if self.complexity else None,
            "factor": str(self.factor),
            "design_total": int(self.design_total),
            "realization_total": int(self.realization_total),
            "extra_total": int(self.extra_total),
            "grand_total": int(self.grand_total),
            "fixed_design": self.fixed_design_price is not None,
            "has_custom": self.has_custom,
            "working_days": self.working_days,
            "lines": [
                {
                    "code": line.module.code,
                    "title": line.module.label,
                    "unit": line.module.unit,
                    "quantity": str(line.quantity),
                    "amount": None if line.amount is None else int(line.amount),
                    "house_part": line.module.house_part,
                }
                for line in self.lines
            ],
            "missing": [
                {
                    "code": m.code,
                    "title": m.label,
                    "house_part": m.house_part,
                    "warning": m.warning,
                }
                for m in self.missing
            ],
        }


def quantity_for(module, months=1, stages=1):
    """Сколько единиц берём для модуля с абонентской или поэтапной ценой."""
    if module.unit == Unit.MONTH:
        return Decimal(months)
    if module.unit == Unit.STAGE:
        return Decimal(stages)
    if module.unit == Unit.HOURS:
        return module.included_units or Decimal("1")
    return Decimal("1")


def calculate(area, rooms=1, complexity=None, modules=None, months=None, stages=None, settings=None):
    """Посчитать стоимость для набора модулей.

    `area` — площадь в м², `modules` — итерируемое с ServiceModule.
    Обязательные модули добавляются всегда: убрать фундамент нельзя.
    """
    settings = settings or PricingSettings.get()
    area = Decimal(area or 0)
    months = int(months or settings.months_for(area))
    stages = int(stages or 1)

    modules = list(modules or [])
    chosen = {m.pk: m for m in modules}
    for required in ServiceModule.objects.filter(is_required=True, is_active=True):
        chosen.setdefault(required.pk, required)

    calc = Calculation(
        area=area,
        rooms=rooms or 1,
        complexity=complexity,
        months=months,
        settings=settings,
    )
    factor = calc.factor

    for module in sorted(chosen.values(), key=lambda m: (m.block, m.order, m.code)):
        qty = quantity_for(module, months=months, stages=stages)
        calc.lines.append(
            Line(module=module, quantity=qty, amount=module.amount_for(area, factor, qty))
        )

    # Фикс для маленьких помещений. Считать санузел или гардеробную
    # по квадратам бессмысленно: включения там столько же, сколько
    # в комнате втрое больше, а сумма выходит такая, за которую работать
    # нельзя. Поэтому проектирование там стоит фиксировано, каким бы
    # ни был набор блоков.
    if (
        settings.small_area_enabled
        and Decimal("0") < area <= settings.small_area_threshold
        and any(line.module.block == Block.DESIGN for line in calc.lines)
    ):
        calc.fixed_design_price = settings.small_area_price

    # Что снято — нужно не меньше, чем что выбрано: из этого собираются
    # дыры в доме и честные плашки «что вы берёте на себя».
    calc.missing = list(
        ServiceModule.objects.filter(is_active=True, is_required=False)
        .exclude(pk__in=chosen)
        .exclude(warning="")
        .order_by("order")
    )
    return calc


def default_preset():
    return (
        Preset.objects.filter(is_active=True, is_default=True).first()
        or Preset.objects.filter(is_active=True).first()
    )


def default_complexity():
    return (
        ComplexityFactor.objects.filter(is_default=True).first()
        or ComplexityFactor.objects.first()
    )
