"""Отправить файлы резервной копии в Yandex Object Storage.

Зовётся из deploy/backup.sh сразу после того, как копия собрана:

    manage.py backup_upload /srv/backups/db_2026-11-18_03-30.sql.gz ...

Файл кладётся в бакет под ключом «dades/2026-11/db_….sql.gz»: по папке
на месяц, чтобы в консоли было легко найти нужную ночь.

Пока бакет не настроен, команда ничего не делает и говорит об этом —
бэкап на сервере от этого не ломается.
"""

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


def make_client():
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=settings.BACKUP_S3_ENDPOINT,
        region_name=settings.BACKUP_S3_REGION,
        aws_access_key_id=settings.BACKUP_S3_KEY_ID,
        aws_secret_access_key=settings.BACKUP_S3_SECRET,
        # Свежий boto3 по умолчанию шлёт контрольные суммы так, как умеет
        # только сам AWS; S3-совместимые хранилища на этом спотыкаются.
        # «Когда требуется» — поведение, которое понимают все.
        config=Config(
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
            retries={"max_attempts": 5, "mode": "standard"},
        ),
    )


def object_key(path):
    """«db_2026-11-18_03-30.sql.gz» → «dades/2026-11/db_2026-11-18_03-30.sql.gz»."""
    name = Path(path).name
    stamp = name.split("_", 1)[1] if "_" in name else ""
    month = stamp[:7] if len(stamp) >= 7 and stamp[4] == "-" else "other"
    prefix = settings.BACKUP_S3_PREFIX
    if prefix and not prefix.endswith("/"):
        prefix += "/"
    return f"{prefix}{month}/{name}"


class Command(BaseCommand):
    help = "Отправить файлы резервной копии в облачное хранилище"

    def add_arguments(self, parser):
        parser.add_argument("files", nargs="+")

    def handle(self, *args, files, **options):
        if not settings.BACKUP_S3_BUCKET:
            self.stdout.write("Облако не настроено (BACKUP_S3_BUCKET пуст) — копия только на сервере.")
            return
        if not (settings.BACKUP_S3_KEY_ID and settings.BACKUP_S3_SECRET):
            raise CommandError("Не заданы BACKUP_S3_KEY_ID и BACKUP_S3_SECRET в .env.")

        paths = [Path(f) for f in files]
        missing = [str(p) for p in paths if not p.is_file()]
        if missing:
            raise CommandError("Нет таких файлов: " + ", ".join(missing))

        client = make_client()
        failed = []
        for path in paths:
            key = object_key(path)
            try:
                client.upload_file(str(path), settings.BACKUP_S3_BUCKET, key)
            except Exception as error:  # noqa: BLE001 — любая причина значит «не ушло»
                failed.append(f"{path.name}: {error}")
                continue
            size = path.stat().st_size / 1024 / 1024
            self.stdout.write(f"✓ В облаке: {settings.BACKUP_S3_BUCKET}/{key} ({size:.1f} МБ)")

        if failed:
            raise CommandError("Не ушло в облако:\n" + "\n".join(failed))
