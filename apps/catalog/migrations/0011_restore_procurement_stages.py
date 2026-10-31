"""Возвращает текст трёх этапов комплектации, если он стёрся.

Дарья сохранила услугу со страницы, открытой до выкатки поля «Текст
страницы», и пустое поле затёрло текст. Её остальные правки (цена,
«Что входит») миграция не трогает — только пустое поле страницы.
"""

from django.db import migrations

from apps.catalog.texts import PROCUREMENT_STAGES


def forwards(apps, schema_editor):
    ServiceModule = apps.get_model("catalog", "ServiceModule")
    ServiceModule.objects.filter(code="B3", details="").update(details=PROCUREMENT_STAGES)


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0010_details_survive_old_forms"),
    ]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
