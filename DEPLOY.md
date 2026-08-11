# Установка на BEGET VPS

Пошагово, с нуля. Домен: **da-des.ru**. Сервер: **155.212.209.229**.

---

## 1. DNS

В панели регистратора домена — A-записи на IP вашего VPS:

```
@     A   155.212.209.229
www   A   155.212.209.229
```

Проверить: `dig +short da-des.ru`. Обновление занимает от минут до суток —
дальше можно идти, пока оно идёт.

---

## 2. Пользователь и система

```bash
ssh root@155.212.209.229

adduser dades
usermod -aG sudo dades
apt update && apt upgrade -y
apt install -y python3-venv python3-dev build-essential \
               postgresql postgresql-contrib nginx certbot python3-certbot-nginx git
```

Дальше всё — от пользователя `dades`:

```bash
su - dades
```

---

## 3. База данных

```bash
sudo -u postgres psql
```

```sql
CREATE DATABASE dades;
CREATE USER dades WITH PASSWORD 'придумайте-длинный-пароль';
ALTER ROLE dades SET client_encoding TO 'utf8';
ALTER ROLE dades SET default_transaction_isolation TO 'read committed';
ALTER ROLE dades SET timezone TO 'Asia/Krasnoyarsk';
GRANT ALL PRIVILEGES ON DATABASE dades TO dades;
\q
```

Дальше — права на схему, уже из обычной командной строки:

```bash
sudo -u postgres psql -d dades -c "GRANT ALL ON SCHEMA public TO dades;"
sudo -u postgres psql -d dades -c "ALTER DATABASE dades OWNER TO dades;"
```

Права на схему обязательны на PostgreSQL 15 и новее: там их по умолчанию
больше не выдают, и без них миграции падают на ровном месте.

Почему отдельными командами, а не `\c dades` внутри psql: `\c` — это
не SQL, а метакоманда, и она читает **всю строку** как свои аргументы.
При вставке блока целиком она склеивается со следующей строкой,
превращается в `\c dades GRANT ALL ON …` и падает с загадочным
«invalid integer value "ON" for connection option "port"». База при этом
выглядит созданной, а прав на схеме нет.

Проверить, что получилось, — двумя командами. Первая про пароль,
вторая про права:

```bash
psql -h localhost -U dades -d dades -c "SELECT version();"
psql -h localhost -U dades -d dades -c "CREATE TABLE probe(id int); DROP TABLE probe;"
```

Вторая важнее первой: подключиться можно и без прав на создание таблиц,
и тогда всё выглядит хорошо ровно до шага с миграциями.

---

## 4. Код

```bash
sudo mkdir -p /srv/dades && sudo chown dades:dades /srv/dades
git clone -b main https://github.com/AntonSergeevich/architectural_system.git /srv/dades
cd /srv/dades

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
| `DJANGO_ALLOWED_HOSTS` | `da-des.ru,www.da-des.ru` |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | `https://da-des.ru,https://www.da-des.ru` |
| `SITE_URL` | `https://da-des.ru` |
| `POSTGRES_*` | **Снять комментарии** с этих пяти строк и подставить то, что задали в пункте 3. По умолчанию они закомментированы: без них проект работает на SQLite, и это правильно для локальной разработки, но не для сервера |
| `EMAIL_*` | Почта Дарьи `dark-ost@ya.ru`. Пароль — **не** пароль от почты, а пароль приложения: Яндекс ID → Безопасность → Пароли приложений → Почта |
| `TELEGRAM_BOT_TOKEN` | Токен бота `@daarch_bot` от @BotFather |
| `TELEGRAM_CHAT_ID` | Куда бот пишет Дарье — как узнать, ниже |
| `TELEGRAM_BOT_USERNAME` | `daarch_bot`, без «@» |
| `TELEGRAM_WEBHOOK_SECRET` | Длинная случайная строка, как секретный ключ Django |

Закрыть файл от чужих глаз: `chmod 600 .env`.

**Про токен бота.** Это пароль от бота: у кого он есть, тот пишет от имени
Дарьи. Поэтому токен живёт только здесь, в `.env` на сервере, и никогда
в репозитории. Токен, попавший в git, считается скомпрометированным:
его отзывают у @BotFather и выпускают новый — даже если коммит потом
удалили, история остаётся у всех, кто успел склонировать.

**Как узнать `TELEGRAM_CHAT_ID`.** Бот не может написать первым — это
ограничение Telegram, а не настройки. Поэтому:

1. Дарья открывает `@daarch_bot` и отправляет ему любое сообщение.
2. В браузере открыть `https://api.telegram.org/bot<ТОКЕН>/getUpdates`.
3. Взять из ответа `message.chat.id` — это и есть значение.

Проверить, что всё сошлось: `.venv/bin/python manage.py telegram_test` —
в Telegram должно прийти сообщение «Проверка связи». Пока переменные
пустые, уведомления просто не отправляются, всё остальное работает.

```bash
.venv/bin/python manage.py migrate
.venv/bin/python manage.py seed_catalog     # каталог услуг и цены
.venv/bin/python manage.py seed_legal       # документы и договоры
.venv/bin/python manage.py seed_tasks       # готовые задачи для этапов проекта
.venv/bin/python manage.py collectstatic --noinput
.venv/bin/python manage.py createsuperuser  # это Дарья
```

---

## 6. Gunicorn

```bash
sudo cp deploy/gunicorn.service /etc/systemd/system/dades.service
sudo systemctl daemon-reload
sudo systemctl enable --now dades
systemctl status dades
```

Если не поднялся — журнал: `sudo journalctl -u dades -n 50 --no-pager`.

---

## 7. Nginx и HTTPS

```bash
sudo cp deploy/nginx.conf /etc/nginx/sites-available/dades
```

**Сначала поднимаем только 80-й порт** — блоки с `listen 443` временно
закомментировать. Иначе nginx не стартует: сертификата ещё нет.

```bash
sudo mkdir -p /var/www/certbot
sudo ln -s /etc/nginx/sites-available/dades /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx

sudo certbot --nginx -d da-des.ru -d www.da-des.ru
```

После сертификата раскомментировать блоки 443 и ещё раз
`sudo nginx -t && sudo systemctl reload nginx`.

Права на статику:

```bash
sudo chmod o+x /srv /srv/dades
sudo chown -R dades:www-data /srv/dades/staticfiles /srv/dades/media
```

---

## 8. Регулярные задачи

```bash
crontab -u dades /srv/dades/deploy/crontab
crontab -u dades -l
sudo mkdir -p /srv/backups && sudo chown dades:dades /srv/backups
```

Проверить бэкап руками: `/srv/dades/deploy/backup.sh`.

---

## 9. Бот: включить приём сообщений

Уведомления бот умеет отправлять сразу, как только заполнен токен.
А вот **слышать** — только после регистрации вебхука: без него кнопка
«Подключить Telegram» в кабинете не сработает, потому что код привязки
некому будет получить.

Регистрируется один раз, после того как заработал HTTPS:

```bash
cd /srv/dades
.venv/bin/python manage.py telegram_webhook
.venv/bin/python manage.py telegram_webhook --info   # проверить
```

В `.env` для этого нужны две строки:

```
TELEGRAM_BOT_USERNAME=daarch_bot
TELEGRAM_WEBHOOK_SECRET=<длинная случайная строка>
```

Секрет генерируется так же, как ключ Django:
`python3 -c "import secrets;print(secrets.token_urlsafe(24))"`.
Он попадает в адрес вебхука, и без него в этот адрес может постучаться
кто угодно.

Проверка целиком: зайти в кабинет, нажать «Подключить Telegram»,
в открывшемся боте нажать «Запустить». В кабинете после обновления
страницы появится «подключено».

Сменили домен — зарегистрируйте вебхук заново.

---

## 10. Контент: фото, тексты, регламент

Всё, что видно на сайте, правится Дарьей без программиста. Вход:
`https://da-des.ru/admin/`, логин и пароль — те, что задали
в `createsuperuser`.

| Что | Где | Куда попадает |
|---|---|---|
| **Фото Дарьи** | Настройки сайта → **Фото** | Первый экран блока «Обо мне» на главной и страница «Обо мне» |
| Текст о себе, телефон, почта, Telegram | Настройки сайта | Шапка, подвал, контакты, договоры |
| Регламент | Настройки сайта → Регламент | Публикуется дословно и подтверждается в договоре |
| Цены | Каталог → Модули услуг | Конструктор, мини-расчёт на главной, КП |
| Работы | Портфолио → Объекты и фотографии | Раздел «Работы» |
| Тексты документов и договоров | Юридические документы, Шаблоны договоров | Правовые страницы и договоры |

Фото загружается обычной кнопкой «Выберите файл» и попадает
в `/srv/dades/media/site/`. Если картинка не открывается — права
на каталог: `sudo chown -R dades:www-data /srv/dades/media`.

---

## 11. Приём оплат: GetPlatinum

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

4. `sudo systemctl restart dades`
5. Выставить счёт на небольшую сумму и оплатить его по-настоящему.

**Адрес для уведомлений мы передаём сами** в каждом запросе
(`notificationUrl`), настраивать его в их кабинете не нужно. Он такой:
`https://da-des.ru/pay/getplatinum/callback/`

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

## 12. Обновление

```bash
ssh dades@155.212.209.229
cd /srv/dades && ./deploy/deploy.sh
```

Скрипт сам делает бэкап, тянет изменения, ставит зависимости, применяет
миграции, собирает статику, прогоняет `check --deploy` и перезапускает
сервис. Если сервис не поднялся — покажет журнал и выйдет с ошибкой.

---

## Если что-то сломалось

| Симптом | Куда смотреть |
|---|---|
| 502 Bad Gateway | `sudo journalctl -u dades -n 50` — приложение упало или не стартовало |
| 400 Bad Request | `DJANGO_ALLOWED_HOSTS` не содержит домен |
| CSRF verification failed | `DJANGO_CSRF_TRUSTED_ORIGINS` без `https://` или без домена |
| Нет стилей | Не выполнен `collectstatic` либо нет прав: `sudo chmod o+x /srv /srv/dades` |
| Письма не уходят | Порт и режим шифрования: 465 — SSL, 587 — STARTTLS. Проверить `EMAIL_HOST_PASSWORD` — для Яндекса нужен пароль приложения |
| Оплата не отмечается | `sudo journalctl -u dades \| grep GetPlatinum`. Если в журнале «подпись не сошлась» — система уже сверилась через `/status`, счёт закроется сам либо по крону `sync_payments` |
| Миграции падают на правах | `GRANT ALL ON SCHEMA public TO dades;` из пункта 3 |

Откат на предыдущую версию:

```bash
cd /srv/dades
git log --oneline -5
git checkout <хеш>
.venv/bin/python manage.py migrate
sudo systemctl restart dades
```

Восстановление базы из копии:

```bash
gunzip -c /srv/backups/db_ГГГГ-ММ-ДД_ЧЧ-ММ.sql.gz | psql -U dades dades
```
