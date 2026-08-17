#!/usr/bin/env bash
# Стучимся в приложение так же, как это делает nginx, и печатаем код ответа.
#   ./deploy/probe.sh   →   200
#
# Отдельный файл, потому что проверка нужна двум скриптам — выкатке и
# health.sh — и однажды уже разъехалась: оба стучались на 127.0.0.1:8000,
# которого здесь нет. Gunicorn слушает не порт, а юникс-сокет, и порт
# всегда отвечал «000, не отвечает совсем» на живом сайте.
#
# Одного адреса сокета мало: приложение на бою проверяет заголовки.
#   Host            — иначе ALLOWED_HOSTS отдаст 400;
#   X-Forwarded-Proto — иначе SECURE_SSL_REDIRECT отдаст 301 на https.
# Оба заголовка nginx подставляет сам, здесь их приходится писать руками.

cd "$(dirname "$0")/.."
ROOT="$(pwd)"

SOCK="${DADES_SOCKET:-/run/dades/gunicorn.sock}"

# Домен берём из .env, чтобы проверка не разошлась с настройками сайта.
HOST="localhost"
if [ -f "$ROOT/.env" ]; then
    FROM_ENV="$(sed -n 's/^DJANGO_ALLOWED_HOSTS=//p' "$ROOT/.env" | tail -1 | tr -d '"'"'"' ' | cut -d, -f1)"
    # «.da-des.ru» в настройках означает домен со всеми поддоменами,
    # а в заголовке Host точка спереди не нужна.
    [ -n "$FROM_ENV" ] && HOST="${FROM_ENV#.}"
fi

if [ ! -S "$SOCK" ]; then
    echo "нет-сокета"
    exit 0
fi

# curl при обрыве печатает «000» и возвращает ошибку — значит ошибку
# глушим, а на пустой или мусорный вывод отвечаем теми же нулями.
CODE="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 \
    --unix-socket "$SOCK" \
    -H "Host: $HOST" \
    -H 'X-Forwarded-Proto: https' \
    http://localhost/ 2>/dev/null || true)"

case "$CODE" in
    ''|*[!0-9]*) CODE=000 ;;
esac
echo "$CODE"
