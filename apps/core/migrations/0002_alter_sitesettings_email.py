"""Почта Дарьи в настройках сайта.

Значение по умолчанию само по себе достаётся только новой строке,
а строка настроек к этому моменту уже создана — поэтому пустую почту
заполняем отдельным шагом. Без неё документы печатаются со строкой
«почта не указана», и это видно на сайте.
"""

from django.db import migrations, models

EMAIL = "dark-ost@ya.ru"


def fill_email(apps, schema_editor):
    SiteSettings = apps.get_model("core", "SiteSettings")
    SiteSettings.objects.filter(email="").update(email=EMAIL)


def unfill(apps, schema_editor):
    SiteSettings = apps.get_model("core", "SiteSettings")
    SiteSettings.objects.filter(email=EMAIL).update(email="")


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="sitesettings",
            name="email",
            field=models.EmailField(
                blank=True,
                default=EMAIL,
                max_length=254,
                verbose_name="Email",
            ),
        ),
        migrations.RunPython(fill_email, unfill),
    ]
