#!/usr/bin/env bash
# Выкатка одной командой. Запускать из корня проекта на сервере:
#   cd /srv/dades && ./deploy/deploy.sh
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"
PY="$ROOT/.venv/bin/python"
PIP="$ROOT/.venv/bin/pip"

echo "→ Резервная копия базы перед выкаткой"
./deploy/backup.sh

echo "→ Забираем изменения"
git pull --ff-only

echo "→ Зависимости"
"$PIP" install -q -r requirements.txt

echo "→ Миграции"
"$PY" manage.py migrate --noinput

echo "→ Статика"
"$PY" manage.py collectstatic --noinput

echo "→ Проверка боевых настроек"
# --deploy ловит то, что молчит в разработке: незакрытые куки, отсутствие
# HSTS, отладочный режим на бою.
"$PY" manage.py check --deploy

echo "→ Перезапуск"
sudo systemctl restart dades
sleep 2
systemctl is-active --quiet dades && echo "✓ Готово" || {
    echo "✗ Сервис не поднялся, смотрим журнал:"
    sudo journalctl -u dades -n 40 --no-pager
    exit 1
}
