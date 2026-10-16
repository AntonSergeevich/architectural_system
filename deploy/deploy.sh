#!/usr/bin/env bash
# Выкатка одной командой. Запускать из корня проекта на сервере:
#   cd /srv/dades && ./deploy/deploy.sh
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"
PY="$ROOT/.venv/bin/python"
PIP="$ROOT/.venv/bin/pip"

# Без аргумента — выкатить свежий main. С хешем — ровно этот коммит:
# так работает автоматическая выкатка (deploy/autodeploy.sh), которой
# нельзя прихватить коммит новее — его тесты могут быть ещё не пройдены.
TARGET="${1:-}"

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

# Без терминала (автоматическая выкатка) sudo не может спросить пароль
# и падает посреди дела — уже после миграций. Проверяем заранее и
# говорим, чего не хватает, пока ничего не тронуто.
if [ ! -t 0 ] && ! sudo -n -l /usr/bin/systemctl restart dades >/dev/null 2>&1; then
    echo "✗ Для выкатки без терминала нужно право перезапускать сайт без пароля."
    echo "  Один раз на сервере, см. DEPLOY.md «Автоматическая выкатка»:"
    echo "  sudo visudo -cf $ROOT/deploy/sudoers && sudo install -m 440 -o root -g root $ROOT/deploy/sudoers /etc/sudoers.d/dades-deploy"
    exit 1
fi

# Только база: выкатка меняет код и схему, а не загруженные файлы.
# Полная копия с фотографиями делается каждую ночь по крону, и архив
# всех медиа на каждый пуш за месяц съел бы диск.
echo "→ Резервная копия базы перед выкаткой"
./deploy/backup.sh --db-only

echo "→ Забираем изменения"
if [ -n "$TARGET" ]; then
    git fetch -q origin main
    git merge --ff-only -q "$TARGET"
else
    git pull --ff-only
fi
echo "  версия: $(git log -1 --format='%h %s')"

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
