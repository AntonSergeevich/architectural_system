"""Адреса страниц для всех услуг и текст Дарьи про три этапа комплектации.

Текст кладётся только в пустое поле: если Дарья уже успела написать своё,
миграция его не трогает.
"""

from django.db import migrations
from django.utils.text import slugify

from apps.catalog.texts import PROCUREMENT_STAGES as PROCUREMENT


def forwards(apps, schema_editor):
    from apps.core.models import translit

    ServiceModule = apps.get_model("catalog", "ServiceModule")
    taken = set(ServiceModule.objects.exclude(slug="").values_list("slug", flat=True))
    for module in ServiceModule.objects.filter(slug="").order_by("pk"):
        base = slugify(translit(module.title))[:60] or slugify(module.code)
        slug, n = base, 2
        while slug in taken:
            slug, n = f"{base}-{n}", n + 1
        taken.add(slug)
        module.slug = slug
        module.save(update_fields=["slug"])

    ServiceModule.objects.filter(code="B3", details="").update(details=PROCUREMENT)


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0008_service_details"),
    ]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
