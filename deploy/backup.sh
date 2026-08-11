#!/usr/bin/env bash
# Резервная копия базы и загруженных файлов.
# Файлы проектов — визуализации и чертежи — терять нельзя ни при каких
# условиях: заново их не сделать.
set -euo pipefail

ROOT="/srv/dades"
DEST="/srv/backups"
KEEP_DAYS=30
STAMP="$(date +%Y-%m-%d_%H-%M)"

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
fi

if [ -d "$ROOT/media" ]; then
    tar czf "$DEST/media_$STAMP.tar.gz" -C "$ROOT" media
fi

find "$DEST" -type f -mtime +$KEEP_DAYS -delete
echo "✓ Копия: $DEST/*_$STAMP.*"
