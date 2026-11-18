#!/usr/bin/env bash
# Резервная копия базы и загруженных файлов.
# Файлы проектов — визуализации и чертежи — терять нельзя ни при каких
# условиях: заново их не сделать.
#
#   ./deploy/backup.sh            база и файлы (ночной крон)
#   ./deploy/backup.sh --db-only  только база (перед каждой выкаткой)
set -euo pipefail

DB_ONLY=0
[ "${1:-}" = "--db-only" ] && DB_ONLY=1

ROOT="/srv/dades"
DEST="/srv/backups"
KEEP_DAYS=30
STAMP="$(date +%Y-%m-%d_%H-%M)"
MADE=()

mkdir -p "$DEST"

# Из .env берём ровно нужные строки, а не выполняем файл целиком.
#
# `source .env` спотыкается о совершенно законное значение: в строке
# «DEFAULT_FROM_EMAIL=Дарья <dark-ost@ya.ru>» угловые скобки для bash —
# это перенаправление ввода-вывода, и файл падает с синтаксической
# ошибкой. Django читает .env своим разбором и проблемы не видит,
# так что ломается только бэкап — то есть ровно то, о чём узнают
# в самый неподходящий момент.
env_value() {
    local line
    line="$(grep -m1 "^$1=" "$ROOT/.env" || true)"
    line="${line#*=}"
    # Снимаем обрамляющие кавычки, если значение записано в них.
    line="${line%\"}"; line="${line#\"}"
    line="${line%\'}"; line="${line#\'}"
    printf '%s' "$line"
}

POSTGRES_DB="$(env_value POSTGRES_DB)"
POSTGRES_USER="$(env_value POSTGRES_USER)"
POSTGRES_PASSWORD="$(env_value POSTGRES_PASSWORD)"
POSTGRES_HOST="$(env_value POSTGRES_HOST)"

if [ -n "${POSTGRES_DB:-}" ]; then
    PGPASSWORD="$POSTGRES_PASSWORD" pg_dump \
        -h "${POSTGRES_HOST:-localhost}" -U "$POSTGRES_USER" "$POSTGRES_DB" \
        | gzip > "$DEST/db_$STAMP.sql.gz"
    MADE+=("$DEST/db_$STAMP.sql.gz")
fi

if [ "$DB_ONLY" = 0 ] && [ -d "$ROOT/media" ]; then
    tar czf "$DEST/media_$STAMP.tar.gz" -C "$ROOT" media
    MADE+=("$DEST/media_$STAMP.tar.gz")
fi

find "$DEST" -type f -mtime +$KEEP_DAYS -delete
echo "✓ Копия: $DEST/*_$STAMP.*"

# Вторая копия — в облако, у другого провайдера. Копия на том же сервере
# спасает от ошибки, но не от смерти сервера: в ноябре 2026 VPS умер
# вместе со всеми копиями. Пока BACKUP_S3_BUCKET в .env пустой, команда
# просто говорит, что облако не настроено.
#
# Перед выкаткой (--db-only) неудачная отправка не останавливает выкатку:
# локальная копия уже есть, а держать сайт на старой версии из-за сети
# до хранилища — хуже. Ночью — завершаемся с ошибкой, чтобы это было
# видно в журнале /var/log/dades-backup.log.
if [ "${#MADE[@]}" -gt 0 ]; then
    if ! "$ROOT/.venv/bin/python" "$ROOT/manage.py" backup_upload "${MADE[@]}"; then
        echo "✗ Копия в облако не ушла — локальная копия на месте: $DEST"
        [ "$DB_ONLY" = 1 ] || exit 1
    fi
fi
