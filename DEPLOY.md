# Установка на BEGET VPS

Пошагово, с нуля. Домен: **daarch.ru**. Сервер: **155.212.209.229**.

---

## 1. DNS

В панели регистратора домена — A-записи на IP вашего VPS:

```
@     A   155.212.209.229
www   A   155.212.209.229
```

Проверить: `dig +short daarch.ru`. Обновление занимает от минут до суток —
дальше можно идти, пока оно идёт.

---

## 2. Пользователь и система

```bash
ssh root@155.212.209.229

adduser daarch
usermod -aG sudo daarch
apt update && apt upgrade -y
apt install -y python3-venv python3-dev build-essential \
               postgresql postgresql-contrib nginx certbot python3-certbot-nginx git
```

Дальше всё — от пользователя `daarch`:

```bash
su - daarch
```

---

## 3. База данных

```bash
sudo -u postgres psql
```

```sql
CREATE DATABASE daarch;
CREATE USER daarch WITH PASSWORD 'придумайте-длинный-пароль';
ALTER ROLE daarch SET client_encoding TO 'utf8';
ALTER ROLE daarch SET default_transaction_isolation TO 'read committed';
ALTER ROLE daarch SET timezone TO 'Asia/Krasnoyarsk';
GRANT ALL PRIVILEGES ON DATABASE daarch TO daarch;
\c daarch
GRANT ALL ON SCHEMA public TO daarch;
\q
```

Последняя строка обязательна на PostgreSQL 15 и новее: там прав на схему
`public` по умолчанию больше не выдают, и без неё миграции падают
на ровном месте.

---

## 4. Код

```bash
sudo mkdir -p /srv/daarch && sudo chown daarch:daarch /srv/daarch
git clone https://github.com/AntonSergeevich/architectural_system.git /srv/daarch
cd /srv/daarch

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
| `DJANGO_ALLOWED_HOSTS` | `daarch.ru,www.daarch.ru` |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | `https://daarch.ru,https://www.daarch.ru` |
| `SITE_URL` | `https://daarch.ru` |
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
sudo cp deploy/gunicorn.service /etc/systemd/system/daarch.service
sudo systemctl daemon-reload
sudo systemctl enable --now daarch
systemctl status daarch
```

Если не поднялся — журнал: `sudo journalctl -u daarch -n 50 --no-pager`.

---

## 7. Nginx и HTTPS

```bash
sudo cp deploy/nginx.conf /etc/nginx/sites-available/daarch
```

**Сначала поднимаем только 80-й порт** — блоки с `listen 443` временно
закомментировать. Иначе nginx не стартует: сертификата ещё нет.

```bash
sudo mkdir -p /var/www/certbot
sudo ln -s /etc/nginx/sites-available/daarch /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx

sudo certbot --nginx -d daarch.ru -d www.daarch.ru
```

После сертификата раскомментировать блоки 443 и ещё раз
`sudo nginx -t && sudo systemctl reload nginx`.

Права на статику:

```bash
sudo chmod o+x /srv /srv/daarch
sudo chown -R daarch:www-data /srv/daarch/staticfiles /srv/daarch/media
```

---

## 8. Регулярные задачи

```bash
crontab -u daarch /srv/daarch/deploy/crontab
crontab -u daarch -l
sudo mkdir -p /srv/backups && sudo chown daarch:daarch /srv/backups
```

Проверить бэкап руками: `/srv/daarch/deploy/backup.sh`.

---

## 9. Приём оплат: GetPlatinum

Пока реквизиты не заданы, приём оплат **выключен**: кнопка не показывается,
счёт помечается оплаченным вручную в кабинете. Это сделано намеренно —
кнопка, ведущая в никуда, хуже её отсутствия.

Чтобы включить:

1. Зарегистрировать кабинет на getplatinum.ru и подать заявку
   на подключение организации. API работает только после одобрения.
2. Личный кабинет → **Настройки** → нужная организация → кнопка настроек →
   скопировать **API-ключ**.
3. Заполнить в `.env` (`<аккаунт>` — имя вашего аккаунта GetPlatinum,
   оно же в адресе кабинета):

```
GETPLATINUM_API_URL=https://<аккаунт>.getplatinum.ru/api/public/pay
GETPLATINUM_API_KEY=<ключ из кабинета>
GETPLATINUM_VAT=none
```

`none` — «НДС не применяется». Для самозанятого это верное значение;
`0` означает другое — ставку 0 %, и ошибка здесь ведёт к проблемам
с налоговым учётом.

4. `sudo systemctl restart daarch`
5. Выставить счёт на небольшую сумму и оплатить его по-настоящему.

**Адрес для уведомлений мы передаём сами** в каждом запросе
(`notificationUrl`), настраивать его в их кабинете не нужно. Он такой:
`https://daarch.ru/pay/getplatinum/callback/`

**Что важно знать про их коллбэк.** Он приходит ровно один раз: если
ответить не 200, повторной попытки не будет и платёж потеряется.
Поэтому наш обработчик отвечает 200 всегда, а зачисляет только
проверенное. Если подпись не сошлась — идёт и спрашивает статус платежа
через их метод `/status`. Плюс раз в час по крону работает
`sync_payments`, который добирает счета, по которым коллбэк не дошёл.

Отдельно в nginx: маршрут `/pay/getplatinum/callback/` выведен из-под лимита
на формы. Уведомления приходят пачкой и не должны отбрасываться — иначе
оплаченные счета останутся неоплаченными в системе.

---

## 10. Обновление

```bash
ssh daarch@155.212.209.229
cd /srv/daarch && ./deploy/deploy.sh
```

Скрипт сам делает бэкап, тянет изменения, ставит зависимости, применяет
миграции, собирает статику, прогоняет `check --deploy` и перезапускает
сервис. Если сервис не поднялся — покажет журнал и выйдет с ошибкой.

---

## Если что-то сломалось

| Симптом | Куда смотреть |
|---|---|
| 502 Bad Gateway | `sudo journalctl -u daarch -n 50` — приложение упало или не стартовало |
| 400 Bad Request | `DJANGO_ALLOWED_HOSTS` не содержит домен |
| CSRF verification failed | `DJANGO_CSRF_TRUSTED_ORIGINS` без `https://` или без домена |
| Нет стилей | Не выполнен `collectstatic` либо нет прав: `sudo chmod o+x /srv /srv/daarch` |
| Письма не уходят | Порт и режим шифрования: 465 — SSL, 587 — STARTTLS. Проверить `EMAIL_HOST_PASSWORD` — для Яндекса нужен пароль приложения |
| Оплата не отмечается | `sudo journalctl -u daarch \| grep GetPlatinum`. Если в журнале «подпись не сошлась» — система уже сверилась через `/status`, счёт закроется сам либо по крону `sync_payments` |
| Миграции падают на правах | `GRANT ALL ON SCHEMA public TO daarch;` из пункта 3 |

Откат на предыдущую версию:

```bash
cd /srv/daarch
git log --oneline -5
git checkout <хеш>
.venv/bin/python manage.py migrate
sudo systemctl restart daarch
```

Восстановление базы из копии:

```bash
gunzip -c /srv/backups/db_ГГГГ-ММ-ДД_ЧЧ-ММ.sql.gz | psql -U daarch daarch
```
