# Установка на BEGET VPS

Пошагово, с нуля. Домен уже есть — считаем, что он `example.ru`;
подставьте свой везде, где он встречается.

---

## 1. DNS

В панели регистратора домена — A-записи на IP вашего VPS:

```
@     A   <IP сервера>
www   A   <IP сервера>
```

Проверить: `dig +short example.ru`. Обновление занимает от минут до суток —
дальше можно идти, пока оно идёт.

---

## 2. Пользователь и система

```bash
ssh root@<IP>

adduser darya
usermod -aG sudo darya
apt update && apt upgrade -y
apt install -y python3-venv python3-dev build-essential \
               postgresql postgresql-contrib nginx certbot python3-certbot-nginx git
```

Дальше всё — от пользователя `darya`:

```bash
su - darya
```

---

## 3. База данных

```bash
sudo -u postgres psql
```

```sql
CREATE DATABASE darya;
CREATE USER darya WITH PASSWORD 'придумайте-длинный-пароль';
ALTER ROLE darya SET client_encoding TO 'utf8';
ALTER ROLE darya SET default_transaction_isolation TO 'read committed';
ALTER ROLE darya SET timezone TO 'Asia/Krasnoyarsk';
GRANT ALL PRIVILEGES ON DATABASE darya TO darya;
\c darya
GRANT ALL ON SCHEMA public TO darya;
\q
```

Последняя строка обязательна на PostgreSQL 15 и новее: там прав на схему
`public` по умолчанию больше не выдают, и без неё миграции падают
на ровном месте.

---

## 4. Код

```bash
sudo mkdir -p /srv/darya && sudo chown darya:darya /srv/darya
git clone <адрес репозитория> /srv/darya
cd /srv/darya

python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

---

## 5. Настройки

```bash
cp .env.example .env
nano .env
```

Обязательно заполнить:

| Переменная | Чем заполнить |
|---|---|
| `DJANGO_SECRET_KEY` | Длинная случайная строка. Сгенерировать: `python3 -c "import secrets;print(secrets.token_urlsafe(64))"` |
| `DJANGO_DEBUG` | `0` |
| `DJANGO_ALLOWED_HOSTS` | `example.ru,www.example.ru` |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | `https://example.ru,https://www.example.ru` |
| `SITE_URL` | `https://example.ru` |
| `POSTGRES_*` | То, что задали в пункте 3 |
| `EMAIL_*` | Почта для уведомлений |

Закрыть файл от чужих глаз: `chmod 600 .env`.

```bash
.venv/bin/python manage.py migrate
.venv/bin/python manage.py seed_catalog     # каталог услуг и цены
.venv/bin/python manage.py seed_legal       # документы и договоры
.venv/bin/python manage.py collectstatic --noinput
.venv/bin/python manage.py createsuperuser  # это Дарья
```

---

## 6. Gunicorn

```bash
sudo cp deploy/gunicorn.service /etc/systemd/system/darya.service
sudo systemctl daemon-reload
sudo systemctl enable --now darya
systemctl status darya
```

Если не поднялся — журнал: `sudo journalctl -u darya -n 50 --no-pager`.

---

## 7. Nginx и HTTPS

```bash
sudo cp deploy/nginx.conf /etc/nginx/sites-available/darya
sudo nano /etc/nginx/sites-available/darya     # заменить example.ru
```

**Сначала поднимаем только 80-й порт** — блоки с `listen 443` временно
закомментировать. Иначе nginx не стартует: сертификата ещё нет.

```bash
sudo mkdir -p /var/www/certbot
sudo ln -s /etc/nginx/sites-available/darya /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx

sudo certbot --nginx -d example.ru -d www.example.ru
```

После сертификата раскомментировать блоки 443 и ещё раз
`sudo nginx -t && sudo systemctl reload nginx`.

Права на статику:

```bash
sudo chmod o+x /srv /srv/darya
sudo chown -R darya:www-data /srv/darya/staticfiles /srv/darya/media
```

---

## 8. Регулярные задачи

```bash
crontab -u darya /srv/darya/deploy/crontab
crontab -u darya -l
sudo mkdir -p /srv/backups && sudo chown darya:darya /srv/backups
```

Проверить бэкап руками: `/srv/darya/deploy/backup.sh`.

---

## 9. Приём оплат: GetPlatinum

Пока реквизиты не заданы, приём оплат **выключен**: кнопка не показывается,
счёт помечается оплаченным вручную в кабинете. Это сделано намеренно —
кнопка, ведущая в никуда, хуже её отсутствия.

Чтобы включить:

1. В личном кабинете GetPlatinum получить **идентификатор магазина**
   и **секретный ключ**, найти **адрес API** для создания платежа.
2. Указать адрес для уведомлений об оплате:
   `https://example.ru/pay/getplatinum/callback/`
3. Заполнить в `.env`:

```
GETPLATINUM_MERCHANT_ID=...
GETPLATINUM_SECRET_KEY=...
GETPLATINUM_API_URL=https://...
GETPLATINUM_TEST_MODE=1
```

4. `sudo systemctl restart darya`
5. Провести тестовый платёж, затем поставить `GETPLATINUM_TEST_MODE=0`.

**Что почти наверняка придётся поправить под их протокол.** Весь код,
зависящий от формата GetPlatinum, лежит в одном файле
`apps/billing/getplatinum.py` и помечен `TODO`:

| Место | Что сверить с документацией |
|---|---|
| `_payload()` | Имена полей запроса на создание платежа |
| `signature()` | Формула подписи. Сейчас — HMAC-SHA256 по отсортированным параметрам |
| `parse_callback()` | Имена полей уведомления и набор статусов |

Остальная система знает только про счета и платежи, поэтому правка
локальная. Подпись уведомления проверяется всегда — без верной подписи
запрос отклоняется с 400.

Отдельно в nginx: маршрут `/pay/getplatinum/callback/` выведен из-под лимита
на формы. Уведомления приходят пачкой и не должны отбрасываться — иначе
оплаченные счета останутся неоплаченными в системе.

---

## 10. Обновление

```bash
ssh darya@<IP>
cd /srv/darya && ./deploy/deploy.sh
```

Скрипт сам делает бэкап, тянет изменения, ставит зависимости, применяет
миграции, собирает статику, прогоняет `check --deploy` и перезапускает
сервис. Если сервис не поднялся — покажет журнал и выйдет с ошибкой.

---

## Если что-то сломалось

| Симптом | Куда смотреть |
|---|---|
| 502 Bad Gateway | `sudo journalctl -u darya -n 50` — приложение упало или не стартовало |
| 400 Bad Request | `DJANGO_ALLOWED_HOSTS` не содержит домен |
| CSRF verification failed | `DJANGO_CSRF_TRUSTED_ORIGINS` без `https://` или без домена |
| Нет стилей | Не выполнен `collectstatic` либо нет прав: `sudo chmod o+x /srv /srv/darya` |
| Письма не уходят | Порт и режим шифрования: 465 — SSL, 587 — STARTTLS. Проверить `EMAIL_HOST_PASSWORD` — для Яндекса нужен пароль приложения |
| Оплата не отмечается | Журнал: `sudo journalctl -u darya | grep GetPlatinum`. Скорее всего не сходится подпись — сверить формулу в `getplatinum.py` |
| Миграции падают на правах | `GRANT ALL ON SCHEMA public TO darya;` из пункта 3 |

Откат на предыдущую версию:

```bash
cd /srv/darya
git log --oneline -5
git checkout <хеш>
.venv/bin/python manage.py migrate
sudo systemctl restart darya
```

Восстановление базы из копии:

```bash
gunzip -c /srv/backups/db_ГГГГ-ММ-ДД_ЧЧ-ММ.sql.gz | psql -U darya darya
```
