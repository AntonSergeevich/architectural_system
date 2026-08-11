#!/usr/bin/env bash
# Резервная копия базы и загруженных файлов.
# Файлы проектов — визуализации и чертежи — терять нельзя ни при каких
# условиях: заново их не сделать.
set -euo pipefail

ROOT="/srv/darya"
DEST="/srv/backups"
KEEP_DAYS=30
STAMP="$(date +%Y-%m-%d_%H-%M)"

mkdir -p "$DEST"

# shellcheck disable=SC1091
set -a; source "$ROOT/.env"; set +a

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
