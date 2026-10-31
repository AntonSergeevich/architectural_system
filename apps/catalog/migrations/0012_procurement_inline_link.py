"""«Комплектация разбита на 3 этапа» — «3 этапа» становится ссылкой.

Так попросила Дарья. Ссылка делается квадратными скобками в тексте
«Что входит»; миграция ставит их один раз, если Дарья ещё не поставила
сама, и только вокруг первого «N этапа».
"""

import re

from django.db import migrations

STAGES = re.compile(r"(?<!\[)\b((?:\d+|три|два|четыре)\s+этап(?:а|ов)?)\b", re.I)


def forwards(apps, schema_editor):
    ServiceModule = apps.get_model("catalog", "ServiceModule")
    module = ServiceModule.objects.filter(code="B3").first()
    if module is None or "[" in module.description or not module.details.strip():
        return
    text, count = STAGES.subn(r"[\1]", module.description, count=1)
    if count:
        module.description = text
        module.save(update_fields=["description"])


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0011_restore_procurement_stages"),
    ]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
