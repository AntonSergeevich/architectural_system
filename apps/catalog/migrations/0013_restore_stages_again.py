"""Второй раз возвращает этапы комплектации и ставит ссылку «[3 этапа]».

Вкладка с правкой услуги, открытая, пока поле было пустым, при сохранении
снова записала пустоту. С этой выкатки форма пишет только поля, которые
человек поменял, — повторения не будет. Здесь: текст этапов — если поле
пустое, скобки вокруг «3 этапа» — если Дарья не поставила свои.
updated_at обновляется, чтобы уже открытые вкладки увидели перемену.
"""

import re

from django.db import migrations
from django.utils import timezone

from apps.catalog.texts import PROCUREMENT_STAGES

STAGES = re.compile(r"(?<!\[)\b((?:\d+|три|два|четыре)\s+этап(?:а|ов)?)\b", re.I)


def forwards(apps, schema_editor):
    ServiceModule = apps.get_model("catalog", "ServiceModule")
    module = ServiceModule.objects.filter(code="B3").first()
    if module is None:
        return
    fields = []
    if not module.details.strip():
        module.details = PROCUREMENT_STAGES
        fields.append("details")
    if "[" not in module.description:
        text, count = STAGES.subn(r"[\1]", module.description, count=1)
        if count:
            module.description = text
            fields.append("description")
    if fields:
        module.updated_at = timezone.now()
        module.save(update_fields=fields + ["updated_at"])


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0012_procurement_inline_link"),
    ]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
