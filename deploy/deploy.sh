#!/usr/bin/env bash
# Выкатка одной командой. Запускать из корня проекта на сервере:
#   cd /srv/dades && ./deploy/deploy.sh
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"
PY="$ROOT/.venv/bin/python"
PIP="$ROOT/.venv/bin/pip"

# Выкатку запускает владелец проекта — и проверяется это первым делом,
# до бэкапа и до всего остального.
#
# Из-под root git отказывается работать с чужим репозиторием («dubious
# ownership»). Соблазн добавить safe.directory велик, но он лечит симптом:
# git под root начнёт создавать файлы с владельцем root, и следующая
# выкатка от обычного пользователя сломается уже правами, которые
# придётся разбирать руками.
OWNER="$(stat -c '%U' "$ROOT")"
if [ "$(id -un)" != "$OWNER" ]; then
    echo "✗ Выкатку запускает $OWNER, а сейчас вы $(id -un)."
    echo
    echo "  su - $OWNER"
    echo "  cd $ROOT && ./deploy/deploy.sh"
    exit 1
fi

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

# Ждём, а не спим ровно две секунды: на холодном старте приложение
# поднимается дольше, и «не успел за две секунды» — это не поломка.
for _ in $(seq 1 15); do
    systemctl is-active --quiet dades && break
    sleep 1
done

if ! systemctl is-active --quiet dades; then
    echo "✗ Сервис не поднялся, смотрим журнал:"
    sudo journalctl -u dades -n 40 --no-pager
    exit 1
fi

# Живой сервис ещё не значит работающий сайт: приложение может отвечать
# ошибкой на каждый запрос. Проверяем именно то, что увидит человек.
# Причину молчания probe.sh пишет в поток ошибок — придерживаем её, чтобы
# показать рядом с приговором, а не раньше него.
PROBE_ERR="$(mktemp)"
trap 'rm -f "$PROBE_ERR"' EXIT
CODE="$(./deploy/probe.sh 2>"$PROBE_ERR")"

if [ "$CODE" = "200" ]; then
    echo "✓ Готово, сайт отвечает"
else
    if [ "$CODE" = "нет-сокета" ]; then
        echo "✗ Сервис запущен, но сокет для nginx так и не появился."
    else
        echo "✗ Сервис запущен, но главная отвечает кодом $CODE."
    fi
    if [ -s "$PROBE_ERR" ]; then sed 's/^/  /' "$PROBE_ERR"; fi
    echo "  Смотрим журнал:"
    sudo journalctl -u dades -n 40 --no-pager
    echo
    echo "  Подробнее: ./deploy/health.sh"
    exit 1
fi
