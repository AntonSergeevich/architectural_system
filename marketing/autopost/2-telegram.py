# ── Дописать в landing/services/telegram.py ────────────────────────────────
# Рядом с notify() и send_to(). _call, API, logger и requests уже есть в этом файле.

# Telegram режет подпись к картинке на 1024 символах, а обычное сообщение —
# на 4096. Длинный пост с картинкой поэтому уходит двумя сообщениями:
# сначала картинка, следом текст. Иначе Telegram молча обрежет конец,
# и узнаешь об этом от подписчиков.
CAPTION_LIMIT = 1024
MESSAGE_LIMIT = 4096


def _channel_id():
    """Куда постим. Отдельная переменная: группа и закрытый клуб — не одно и то же."""
    chat_id = (getattr(settings, 'TELEGRAM_POST_CHAT_ID', None)
               or getattr(settings, 'TELEGRAM_CLUB_CHAT_ID', None))
    if not chat_id:
        logger.warning('TELEGRAM_POST_CHAT_ID не задан — публикация пропущена')
    return chat_id


def _send_photo(chat_id, fh, caption):
    """sendPhoto живёт отдельно от _call: у него multipart, а не form-data."""
    token = getattr(settings, 'TELEGRAM_BOT_TOKEN', None)
    if not token:
        logger.warning('TELEGRAM_BOT_TOKEN не задан — sendPhoto пропущен')
        return None
    try:
        response = requests.post(
            API.format(token=token, method='sendPhoto'),
            data={'chat_id': chat_id, 'caption': caption, 'parse_mode': 'HTML'},
            files={'photo': fh}, timeout=30)
        data = response.json()
    except (requests.exceptions.RequestException, ValueError):
        logger.exception('Telegram sendPhoto: не удалось отправить')
        return None
    if not data.get('ok'):
        logger.error('Telegram sendPhoto: %s', data.get('description'))
        return None
    return data.get('result')


def _send_text(chat_id, text):
    return _call('sendMessage', {
        'chat_id': chat_id,
        'text': text,
        'parse_mode': 'HTML',
        'disable_web_page_preview': True,
    })


def publish_post(text, image_path=None):
    """Публикует пост в канал. Возвращает message_id или None.

    Возвращаемый id — не украшение: по нему пост потом можно найти
    и отредактировать, не создавая в канале второй такой же.
    """
    chat_id = _channel_id()
    if not chat_id:
        return None

    text = (text or '').strip()
    if not text:
        logger.error('Публикация пропущена: пустой текст')
        return None
    if len(text) > MESSAGE_LIMIT:
        logger.error('Публикация пропущена: текст длиннее %s символов', MESSAGE_LIMIT)
        return None

    if not image_path:
        result = _send_text(chat_id, text)
        return result.get('message_id') if result else None

    fits_in_caption = len(text) <= CAPTION_LIMIT
    with open(image_path, 'rb') as fh:
        photo = _send_photo(chat_id, fh, text if fits_in_caption else '')
    if photo is None:
        return None
    if fits_in_caption:
        return photo.get('message_id')

    # Картинка ушла, текст в подпись не поместился — досылаем отдельным
    # сообщением. Если не дошло и оно, в канале осталась голая картинка:
    # это видно, и сообщение можно дослать руками, а вот дубль поста
    # разгребать было бы хуже.
    tail = _send_text(chat_id, text)
    if tail is None:
        logger.error('Картинка ушла, текст не ушёл — в канале остался голый кадр')
    return (tail or photo).get('message_id')
