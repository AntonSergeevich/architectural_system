"""Расчёт стоимости.

Одна функция считает и то, что видно в конструкторе, и то, что попадает
в коммерческое предложение. Двух реализаций быть не должно: расхождение
между «посчитал сайт» и «выставила Дарья» — это ровно тот разговор,
которого система должна избавить.
"""

from dataclasses import dataclass, field
from decimal import Decimal

from .models import Block, ComplexityFactor, Preset, ServiceModule, Unit

# Ориентировочная длительность реализации. Нужна, чтобы показать абонентские
# услуги в понятном масштабе: «50 000 ₽/мес» без числа месяцев ни о чём
# не говорит. Числа заведомо приблизительные, и в интерфейсе они так
# и подписаны.
DEFAULT_SUPERVISION_MONTHS = 6
DEFAULT_PROCUREMENT_STAGES = 3


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
    lines: list[Line] = field(default_factory=list)
    missing: list[ServiceModule] = field(default_factory=list)

    @property
    def factor(self):
        return self.complexity.factor if self.complexity else Decimal("1")

    def _sum(self, block):
        return sum(
            (line.amount for line in self.lines if line.module.block == block and line.amount),
            Decimal("0"),
        )

    @property
    def design_total(self):
        return self._sum(Block.DESIGN)

    @property
    def realization_total(self):
        return self._sum(Block.REALIZATION)

    @property
    def extra_total(self):
        return self._sum(Block.EXTRA)

    @property
    def has_custom(self):
        return any(line.is_custom for line in self.lines)

    @property
    def working_days(self):
        return sum(line.module.duration_days for line in self.lines)

    def as_dict(self):
        """Для JSON-ответа конструктору."""
        return {
            "area": str(self.area),
            "rooms": self.rooms,
            "complexity": self.complexity.code if self.complexity else None,
            "factor": str(self.factor),
            "design_total": int(self.design_total),
            "realization_total": int(self.realization_total),
            "extra_total": int(self.extra_total),
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


def quantity_for(module, months=DEFAULT_SUPERVISION_MONTHS, stages=DEFAULT_PROCUREMENT_STAGES):
    """Сколько единиц берём для модуля с абонентской или поэтапной ценой."""
    if module.unit == Unit.MONTH:
        return Decimal(months)
    if module.unit == Unit.STAGE:
        return Decimal(stages)
    return Decimal("1")


def calculate(area, rooms=1, complexity=None, modules=None, months=None, stages=None):
    """Посчитать стоимость для набора модулей.

    `area` — площадь в м², `modules` — итерируемое с ServiceModule.
    Обязательные модули добавляются всегда: убрать фундамент нельзя.
    """
    area = Decimal(area or 0)
    modules = list(modules or [])
    chosen = {m.pk: m for m in modules}

    for required in ServiceModule.objects.filter(is_required=True, is_active=True):
        chosen.setdefault(required.pk, required)

    factor = complexity.factor if complexity else Decimal("1")
    calc = Calculation(area=area, rooms=rooms or 1, complexity=complexity)

    for module in sorted(chosen.values(), key=lambda m: (m.block, m.order, m.code)):
        qty = quantity_for(
            module,
            months=months or DEFAULT_SUPERVISION_MONTHS,
            stages=stages or DEFAULT_PROCUREMENT_STAGES,
        )
        calc.lines.append(
            Line(
                module=module,
                quantity=qty,
                amount=module.amount_for(area, factor, qty),
            )
        )

    # Что снято — нужно не меньше, чем что выбрано: из этого собираются дыры
    # в доме и честные плашки «что вы берёте на себя».
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
