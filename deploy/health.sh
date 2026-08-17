#!/usr/bin/env bash
# Что с сайтом, одной командой:
#   cd /srv/dades && ./deploy/health.sh
#
# Нужен, когда браузер показывает 503 или 502. Эти коды говорят одно:
# nginx работает, а приложение за ним — нет. Причина всегда в журнале,
# но чтобы её увидеть, нужно знать четыре команды и помнить их порядок.
# Здесь они собраны в одну, а вывод можно целиком отправить разработчику.

cd "$(dirname "$0")/.."
ROOT="$(pwd)"

line() { printf '\n=== %s ===\n' "$1"; }

line "Служба приложения"
systemctl is-active dades >/dev/null 2>&1 \
    && echo "работает" \
    || { echo "НЕ РАБОТАЕТ — это и есть причина 503"; }
systemctl status dades --no-pager -n 0 2>&1 | head -12

line "Последние 40 строк журнала"
journalctl -u dades -n 40 --no-pager 2>&1 | tail -40

line "Приложение отвечает на своём сокете"
curl -s -o /dev/null -w 'код ответа: %{http_code}\n' --max-time 5 http://127.0.0.1:8000/ \
    || echo "не отвечает совсем"

line "nginx"
systemctl is-active nginx >/dev/null 2>&1 && echo "работает" || echo "НЕ РАБОТАЕТ"
nginx -t 2>&1 | tail -3

line "Место на диске"
df -h / | tail -2
echo "Медиа: $(du -sh "$ROOT/media" 2>/dev/null | cut -f1)"

line "Оперативная память"
free -h | head -2

line "Незаделанные миграции"
"$ROOT/.venv/bin/python" manage.py showmigrations --plan 2>&1 | grep -c '^\[ \]' \
    | xargs -I{} echo "ждут применения: {}"

line "Версия кода"
git -C "$ROOT" log --oneline -1 2>&1

printf '\nЧаще всего помогает: sudo systemctl restart dades\n'
printf 'Если после перезапуска снова падает — причина в журнале выше.\n'
