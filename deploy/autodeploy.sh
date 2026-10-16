#!/usr/bin/env bash
# Вход для автоматической выкатки из GitHub Actions.
#
# Этот скрипт не запускают руками. Ключ GitHub в ~/.ssh/authorized_keys
# привязан к нему опцией command=, поэтому, что бы ни прислал клиент,
# выполняется только он. Присланная строка доступна здесь как
# SSH_ORIGINAL_COMMAND и проверяется так, будто её писал злоумышленник:
# принимается ровно «deploy <40 знаков хеша>», и хеш должен быть в main.
#
# Настройка — DEPLOY.md, раздел «Автоматическая выкатка».
set -euo pipefail

cd "$(dirname "$0")/.."

REQUEST="${SSH_ORIGINAL_COMMAND:-}"
if [[ ! "$REQUEST" =~ ^deploy\ ([0-9a-f]{40})$ ]]; then
    echo "✗ Ожидалось «deploy <хеш коммита>», пришло другое. Ничего не делаю." >&2
    exit 2
fi
SHA="${BASH_REMATCH[1]}"

# Два пуша подряд — две выкатки. Вторая ждёт, пока закончит первая:
# одновременный git merge и перезапуск в одной папке ломают обе.
exec 9>"$HOME/.dades-deploy.lock"
if ! flock -w 900 9; then
    echo "✗ Предыдущая выкатка идёт дольше 15 минут — разберитесь руками: ./deploy/health.sh" >&2
    exit 1
fi

git fetch -q origin main

# Запоздавший запуск: пока он ждал очереди, выкатили коммит новее,
# в котором этот уже есть. Откатывать сайт назад нельзя.
if git merge-base --is-ancestor "$SHA" HEAD 2>/dev/null; then
    echo "✓ Коммит ${SHA:0:7} уже на сервере, выкатывать нечего."
    exit 0
fi

# Выкатываем только main. Хеш из чужой ветки или форка сюда не пройдёт,
# даже если ключ окажется не в тех руках.
if ! git merge-base --is-ancestor "$SHA" origin/main; then
    echo "✗ Коммит ${SHA:0:7} не из main — не выкатываю." >&2
    exit 2
fi

echo "→ Выкатываю ${SHA:0:7}: $(git log -1 --format=%s "$SHA")"
exec ./deploy/deploy.sh "$SHA"
