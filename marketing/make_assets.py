# -*- coding: utf-8 -*-
"""
Генератор картинок для соцсетей: сторис 1080x1920 и карусель 1080x1350.

Палитра и типографика — те же, что на сайте Дарьи (static/css/tokens.css):
тёплая бумага, одна терракота, крупный гротеск с плотным трекингом.
Промо должно выглядеть как продукт, иначе оно ему противоречит.

Шрифты — Inter (OFL). Кладутся в ~/.cache/inter-ttf:

    curl -L -o /tmp/inter.zip \
      https://github.com/rsms/inter/releases/download/v4.1/Inter-4.1.zip
    unzip -j /tmp/inter.zip 'extras/ttf/*' -d ~/.cache/inter-ttf

Запуск:  python3 marketing/make_assets.py
Выход:   marketing/assets/*.jpg
"""

import os
from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "source")
OUT = os.path.join(HERE, "assets")
FONTS = os.path.expanduser(os.environ.get("INTER_TTF_DIR", "~/.cache/inter-ttf"))

os.makedirs(OUT, exist_ok=True)

# --- Палитра (из tokens.css) ------------------------------------------------
PAPER      = (250, 246, 240)
PAPER_ALT  = (243, 236, 226)
SAND       = (233, 223, 209)
LINE       = (222, 210, 194)
INK        = (35, 32, 29)
INK_2      = (74, 68, 62)
MUTED      = (122, 113, 102)
BRAND      = (178, 58, 43)     # терракота
BRAND_600  = (149, 46, 34)
BRAND_50   = (251, 240, 238)
MARKER     = (251, 231, 154)
DARK       = (26, 23, 21)

STORY = (1080, 1920)
CARD  = (1080, 1350)


def font(name, size):
    return ImageFont.truetype(os.path.join(FONTS, name + ".ttf"), size)


D_BLACK  = "InterDisplay-Black"
D_BOLD   = "InterDisplay-Bold"
D_SEMI   = "InterDisplay-SemiBold"
T_MED    = "Inter-Medium"
T_REG    = "Inter-Regular"
T_SEMI   = "Inter-SemiBold"


# --- Текстовые примитивы ----------------------------------------------------

def text_w(draw, s, f, tracking=0):
    if not s:
        return 0
    w = draw.textlength(s, font=f)
    return w + tracking * (len(s) - 1)


def draw_tracked(draw, xy, s, f, fill, tracking=0):
    """Строка с межбуквенным интервалом (Pillow его сам не умеет)."""
    x, y = xy
    if tracking == 0:
        draw.text((x, y), s, font=f, fill=fill)
        return text_w(draw, s, f)
    for ch in s:
        draw.text((x, y), ch, font=f, fill=fill)
        x += draw.textlength(ch, font=f) + tracking
    return x - xy[0]


def wrap(draw, s, f, max_w, tracking=0):
    words, lines, cur = s.split(" "), [], ""
    for wd in words:
        if wd == "\n":
            lines.append(cur); cur = ""; continue
        trial = (cur + " " + wd).strip()
        if text_w(draw, trial, f, tracking) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur); cur = wd
    if cur:
        lines.append(cur)
    return lines


OVERFLOW = []


def block(draw, s, f, box, fill, leading=1.12, tracking=0, align="left", tag=""):
    """Абзац в прямоугольник (x, y, ширина). Возвращает нижнюю границу.

    Перевод строки в тексте — жёсткий: ритм строк в плакатной вёрстке
    задаётся руками, а не шириной колонки. Если ручная строка не влезает,
    она переносится — и это записывается в OVERFLOW, чтобы такую строку
    было видно при сборке, а не на телефоне у клиента.
    """
    x, y, max_w = box
    lh = int(f.size * leading)
    for para in s.split("\n"):
        if not para.strip():
            y += int(lh * 0.5); continue
        lines = wrap(draw, para.strip(), f, max_w, tracking)
        if len(lines) > 1:
            OVERFLOW.append((tag or s[:34], para.strip()[:60],
                             int(text_w(draw, para.strip(), f, tracking)), max_w))
        for line in lines:
            lx = x
            if align == "center":
                lx = x + (max_w - text_w(draw, line, f, tracking)) / 2
            draw_tracked(draw, (lx, y), line, f, fill, tracking)
            y += lh
    return y


def eyebrow(draw, xy, s, fill=BRAND, size=26):
    """Надзаголовок капсом с широким трекингом."""
    return draw_tracked(draw, xy, s.upper(), font(T_SEMI, size), fill, tracking=size * 0.22)


def rule(draw, x, y, w, fill=LINE, h=2):
    draw.rectangle([x, y, x + w, y + h - 1], fill=fill)


# --- Работа с фото ----------------------------------------------------------

def cover(path, size, focus=(0.5, 0.42), zoom=1.0):
    im = Image.open(path).convert("RGB")
    tw, th = size
    scale = max(tw / im.width, th / im.height) * zoom
    im = im.resize((int(im.width * scale) + 1, int(im.height * scale) + 1), Image.LANCZOS)
    cx, cy = im.width * focus[0], im.height * focus[1]
    left = int(min(max(cx - tw / 2, 0), im.width - tw))
    top = int(min(max(cy - th / 2, 0), im.height - th))
    return im.crop((left, top, left + tw, top + th))


def grade(im, warmth=1.05, contrast=1.06, sat=0.94, bright=1.0):
    """Тёплый сдержанный грейд: фото должно жить в одной палитре с бумагой."""
    im = ImageEnhance.Color(im).enhance(sat)
    im = ImageEnhance.Contrast(im).enhance(contrast)
    im = ImageEnhance.Brightness(im).enhance(bright)
    r, g, b = im.split()
    r = r.point(lambda v: min(255, int(v * warmth)))
    b = b.point(lambda v: int(v * (2 - warmth) ** 0.5))
    return Image.merge("RGB", (r, g, b))


def scrim(im, top_stop=0.34, strength=0.86, color=(18, 15, 13)):
    """Градиент снизу, чтобы белый текст читался на любом кадре."""
    w, h = im.size
    mask = Image.new("L", (1, h), 0)
    px = mask.load()
    y0 = int(h * top_stop)
    for y in range(h):
        if y < y0:
            px[0, y] = 0
        else:
            t = (y - y0) / (h - y0)
            px[0, y] = int(255 * strength * (t ** 1.55))
    mask = mask.resize((w, h))
    return Image.composite(Image.new("RGB", (w, h), color), im, mask)


def top_scrim(im, strength=0.5, depth=0.3):
    w, h = im.size
    mask = Image.new("L", (1, h), 0)
    px = mask.load()
    y1 = int(h * depth)
    for y in range(h):
        px[0, y] = int(255 * strength * (1 - y / y1) ** 1.4) if y < y1 else 0
    return Image.composite(Image.new("RGB", (w, h), (18, 15, 13)), im, mask.resize((w, h)))


def paper(size, color=PAPER):
    return Image.new("RGB", size, color)


def grain(im, amount=6):
    """Немного зерна: плоская заливка на телефоне полосит."""
    import random
    n = Image.new("L", (im.width // 3, im.height // 3))
    n.putdata([random.randint(128 - amount, 128 + amount) for _ in range(n.width * n.height)])
    n = n.resize(im.size, Image.BILINEAR).filter(ImageFilter.GaussianBlur(0.6))
    return Image.blend(im, Image.merge("RGB", (n, n, n)), 0.055)


def save(im, name):
    path = os.path.join(OUT, name)
    grain(im).save(path, "JPEG", quality=92, subsampling=0, optimize=True)
    print("→", os.path.relpath(path, HERE))


def counter(draw, i, total, y=1790, fill=(255, 255, 255, 200), on_dark=True):
    c = (255, 255, 255) if on_dark else MUTED
    draw_tracked(draw, (88, y), f"{i} / {total}", font(T_MED, 26), c, tracking=4)


# --- Ссылки -----------------------------------------------------------------

SITE = "s-poryadok.ru"          # мой сайт
DARYA = "da-des.ru"             # система, про которую кейс


def link_band(d, y, url, caption, width=None, fill=BRAND, ink=PAPER, sub=(244, 214, 208)):
    """Плашка со ссылкой. Домен крупно, зачем идти — мелко под ним.

    Ссылка без объяснения не нажимается: человек не знает, что его там ждёт,
    и на всякий случай не идёт никуда.
    """
    w = width or (1080 - 2 * M)
    d.rectangle([M, y, M + w, y + 116], fill=fill)
    draw_tracked(d, (M + 40, y + 24), url, font(T_SEMI, 38), ink, tracking=0.5)
    draw_tracked(d, (M + 40, y + 74), caption, font(T_REG, 27), sub, tracking=1)
    return y + 116


def warm_bw(im, tone=(252, 246, 238), strength=0.10):
    """Чёрно-белый кадр рядом с тёплой бумагой выглядит холодным осколком.
    Лёгкий тёплый тон возвращает его в палитру, не превращая в сепию."""
    return Image.blend(im.convert("L").convert("RGB"), Image.new("RGB", im.size, tone), strength)


# ===========================================================================
#  СТОРИС — серия «Лето» про систему Дарьи
# ===========================================================================

M = 88  # поле


def photo_panel(photo, focus, zoom, panel_top, size=STORY, bg=PAPER,
                warmth=1.045, contrast=1.10, sat=0.90, bw=False):
    """Кадр сверху, бумажная панель снизу.

    Белый текст поверх фотографии — лотерея: на белой футболке он исчезает.
    Панель гарантирует контраст и заодно роднит сторис с сайтом, где вся
    типографика живёт на тёплой бумаге.
    """
    im = paper(size, bg)
    ph = cover(photo, (size[0], panel_top), focus=focus, zoom=zoom)
    ph = warm_bw(ph) if bw else grade(ph, warmth=warmth, contrast=contrast, sat=sat)
    ph = top_scrim(ph, strength=0.30 if bw else 0.34, depth=0.22)
    im.paste(ph, (0, 0))
    d = ImageDraw.Draw(im)
    d.rectangle([0, panel_top, size[0], panel_top + 12], fill=BRAND)
    return im, d


def story_01_hero():
    im, d = photo_panel(os.path.join(SRC, "photo-most.jpg"),
                        focus=(0.52, 0.36), zoom=1.0, panel_top=1258)

    eyebrow(d, (M, 118), "лето 2026", fill=(255, 255, 255), size=26)

    y = 1348
    y = block(d, "Я всё лето\nне только отдыхал.", font(D_BOLD, 88),
              (M, y, 1080 - 2 * M), INK, leading=1.08, tracking=-2.5, tag="s1-h")
    y += 30
    rule(d, M, y, 96, BRAND, h=5)
    y += 44
    block(d, "Я собирал систему, которая продаёт вместо\nархитектора. И перестаёт терять деньги там,\nгде она о них даже не думала.",
          font(T_REG, 35), (M, y, 1080 - 2 * M), INK_2, leading=1.44, tag="s1-t")

    draw_tracked(d, (M, 1836), "дальше — как это работает", font(T_MED, 27),
                 MUTED, tracking=3)
    save(im, "story-01-hero.jpg")


def story_02_vopros():
    im = paper(STORY, PAPER)
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, 1080, 14], fill=BRAND)

    eyebrow(d, (M, 190), "самый дорогой ответ в бизнесе")
    rule(d, M, 250, 1080 - 2 * M, LINE)

    block(d, "Сколько денег\nвы теряете\nкаждый месяц?", font(D_BOLD, 82),
          (M, 340, 1080 - 2 * M), INK, leading=1.1, tracking=-2.4, tag="s2-h")

    d.text((M - 8, 640), "— Не знаю", font=font(D_BLACK, 96), fill=BRAND)

    y = 830
    y = block(d, "Так отвечают почти все. И это не лень —\nэти деньги правда не видно: они утекают\nне из кассы, а из разговоров.",
              font(T_REG, 38), (M, y, 1080 - 2 * M), INK_2, leading=1.46, tag="s2-t")
    y += 34
    block(d, "Непроданный надзор. Проект, взятый дешевле\nсебестоимости. Клиент, ушедший подумать.",
          font(T_SEMI, 38), (M, y, 1080 - 2 * M), INK, leading=1.44, tag="s2-a")

    link_band(d, 1300, SITE, "прикинуть свою цифру — тест на сайте")

    counter(d, 2, 9, y=1806, on_dark=False)
    save(im, "story-02-vopros.jpg")


def story_03_quote():
    im = paper(STORY, PAPER_ALT)
    d = ImageDraw.Draw(im)

    eyebrow(d, (M, 190), "её словами")
    rule(d, M, 250, 1080 - 2 * M, LINE)

    block(d, "«Я рассказываю им каждый\nраз с нуля. Если я устала —\nмогу вообще забыть\nчто-то сказать»",
          font(D_SEMI, 64), (M, 360, 1080 - 2 * M), INK, leading=1.24, tracking=-1.5, tag="s3-q")

    draw_tracked(d, (M, 730), "ДАРЬЯ, АРХИТЕКТОР-ДИЗАЙНЕР", font(T_SEMI, 27), MUTED, tracking=4)
    rule(d, M, 810, 120, BRAND, h=5)

    y = 880
    y = block(d, "Заявка теряется не в блокноте.\nОна теряется в разговоре, где не прозвучало\nполовины ценности.",
              font(T_REG, 38), (M, y, 1080 - 2 * M), INK_2, leading=1.46, tag="s3-t")
    y += 46
    block(d, "Клиент уходит «подумать» и не возвращается.\nА специалист уверен, что не сошлись в цене.",
          font(T_SEMI, 38), (M, y, 1080 - 2 * M), BRAND_600, leading=1.42, tag="s3-a")

    d.rectangle([M, 1330, 1080 - M, 1620], fill=MARKER)
    block(d, "Это не лечится мотивацией.\nЭто лечится тем, что объясняет сайт,\nа не уставший человек в трубке.",
          font(T_SEMI, 38), (M + 44, 1392, 1080 - 2 * M - 88), INK, leading=1.42, tag="s3-m")

    counter(d, 3, 9, y=1806, on_dark=False)
    save(im, "story-03-citata.jpg")


def story_04_before_after():
    im = paper(STORY, PAPER)
    d = ImageDraw.Draw(im)

    d.rectangle([0, 0, 1080, 790], fill=(232, 228, 222))
    eyebrow(d, (M, 150), "было", fill=MUTED)
    rule(d, M, 210, 1080 - 2 * M, (214, 208, 200))

    was = [
        "Каждый разговор — заново, голосом",
        "Правки — в мессенджере, потом всё\nзаново переписывать ради договора",
        "Срок — «ну, примерно к зиме»",
        "Надзор и комплектация не продаются:\nна них не хватило сил в разговоре",
    ]
    y = 292
    for t in was:
        d.ellipse([M, y + 16, M + 14, y + 30], fill=(178, 172, 164))
        y = block(d, t, font(T_REG, 37), (M + 46, y, 1080 - 2 * M - 46), (112, 106, 98),
                  leading=1.34, tag="s4-was")
        y += 30

    eyebrow(d, (M, 892), "стало", fill=BRAND)
    rule(d, M, 952, 1080 - 2 * M, LINE)

    now = [
        "Состав и цену клиент собирает сам, на сайте",
        "Правки — в системе, с историей\nсогласований. И это защита в суде",
        "Срок считается в рабочих часах\nи виден клиенту сразу при отправке",
        "Заявку нельзя сохранить без даты\nследующего шага. Поле обязательное",
    ]
    y = 1042
    for t in now:
        d.rectangle([M, y + 14, M + 16, y + 30], fill=BRAND)
        y = block(d, t, font(T_MED, 37), (M + 46, y, 1080 - 2 * M - 46), INK,
                  leading=1.34, tag="s4-now")
        y += 30

    counter(d, 4, 9, y=1806, on_dark=False)
    save(im, "story-04-bylo-stalo.jpg")


def story_05_constructor():
    im = paper(STORY, PAPER)
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, 1080, 14], fill=BRAND)

    eyebrow(d, (M, 180), "главное решение")
    block(d, "Клиент собирает\nсвой проект сам.\nКак комнату\nиз кубиков.", font(D_BOLD, 88),
          (M, 268, 1080 - 2 * M), INK, leading=1.12, tracking=-2.5, tag="s5-h")

    bx, by, bw, bh = M, 790, 1080 - 2 * M, 340
    d.rectangle([bx, by, bx + bw, by + bh], outline=LINE, width=3)
    d.rectangle([bx + 24, by + bh - 96, bx + bw - 24, by + bh - 24], fill=BRAND)
    draw_tracked(d, (bx + 52, by + bh - 76), "ОБМЕР · БРИФ · ПЛАНИРОВКА",
                 font(T_SEMI, 28), PAPER, tracking=3)
    for x in range(bx + 24, bx + bw - 40, 34):
        d.rectangle([x, by + 34, x + 18, by + 40], fill=(211, 202, 190))
    draw_tracked(d, (bx + 26, by + 74), "здесь пусто — это авторский надзор",
                 font(T_REG, 30), MUTED, tracking=1)

    y = 1210
    y = block(d, "В начале в комнате только пол: без обмера\nи планировки проекта не существует.\nВсё остальное клиент приносит туда сам —\nи только перетаскиванием.",
              font(T_REG, 36), (M, y, 1080 - 2 * M), INK_2, leading=1.46, tag="s5-t")
    y += 32
    block(d, "Галочку ставят не думая.\nБлок доносят до места.",
          font(T_SEMI, 38), (M, y, 1080 - 2 * M), BRAND_600, leading=1.4, tag="s5-a")

    link_band(d, 1600, DARYA, "потрогать конструктор — сайт Дарьи")

    counter(d, 5, 9, y=1806, on_dark=False)
    save(im, "story-05-konstruktor.jpg")


def story_06_principle():
    im = paper(STORY, DARK)
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, 1080, 14], fill=BRAND)

    eyebrow(d, (M, 200), "принцип, на котором держится всё", fill=(214, 141, 128))

    block(d, "Заявка\nне может\nостаться без\nследующего\nшага.", font(D_BLACK, 106),
          (M, 320, 1080 - 2 * M), PAPER, leading=1.06, tracking=-3, tag="s6-h")

    y = 1080
    rule(d, M, y, 120, BRAND, h=5)
    y += 58
    y = block(d, "Это не про дисциплину и не про мотивацию.\nЭто обязательное поле в базе данных.",
              font(T_REG, 38), (M, y, 1080 - 2 * M), (206, 198, 190), leading=1.46, tag="s6-t1")
    y += 32
    y = block(d, "Просроченные касания светятся в кабинете\nи уходят напоминанием — ночью, без вас.",
              font(T_REG, 38), (M, y, 1080 - 2 * M), (206, 198, 190), leading=1.46, tag="s6-t2")
    y += 46
    block(d, "«Заявки теряются» перестаёт быть\nчертой характера и становится\nневозможным состоянием системы.",
          font(T_SEMI, 40), (M, y, 1080 - 2 * M), PAPER, leading=1.4, tag="s6-a")

    counter(d, 6, 9, y=1806, on_dark=True)
    save(im, "story-06-princip.jpg")


def story_07_slushal():
    im, d = photo_panel(os.path.join(SRC, "photo-divan.jpg"),
                        focus=(0.52, 0.40), zoom=1.0, panel_top=1120)

    eyebrow(d, (M, 118), "как это делается", fill=(255, 255, 255), size=26)

    y = 1206
    y = block(d, "Большую часть лета\nя не писал код.\nЯ слушал.", font(D_BOLD, 80),
              (M, y, 1080 - 2 * M), INK, leading=1.1, tracking=-2.3, tag="s7-h")
    y += 28
    rule(d, M, y, 96, BRAND, h=5)
    y += 42
    block(d, "Систему нельзя собрать, не разобрав бизнес.\nСначала долгий разговор, где человек говорит\nвслух то, чего обычно не говорит даже себе:\n«мне влом», «мне лень», «я забываю».\nИз этих фраз и получается задание.",
          font(T_REG, 34), (M, y, 1080 - 2 * M), INK_2, leading=1.44, tag="s7-t")

    counter(d, 7, 9, y=1836, on_dark=False)
    save(im, "story-07-slushal.jpg")


def story_08_personal():
    im = paper(STORY, PAPER_ALT)
    d = ImageDraw.Draw(im)

    eyebrow(d, (M, 150), "и да, отдыхал тоже")

    # Кадр вставкой, а не на всю ширину: исходник маленький, растягивать его
    # до 1080 значит показать кашу вместо фотографии.
    pw, ph_ = 680, 1080
    ph = cover(os.path.join(SRC, "photo-gitara.jpg"), (pw, ph_), focus=(0.58, 0.46))
    ph = grade(ph, warmth=1.04, contrast=1.08, sat=0.92)
    px, py = M, 250
    d.rectangle([px + 22, py + 22, px + pw + 22, py + ph_ + 22], fill=SAND)
    im.paste(ph, (px, py))
    d = ImageDraw.Draw(im)

    y = py + ph_ + 82
    y = block(d, "Гитара в парке — тоже часть работы.",
              font(D_SEMI, 52), (M, y, 1080 - 2 * M), INK, leading=1.2, tracking=-1.5, tag="s8-h")
    y += 40
    block(d, "Хорошая система нужна ровно за этим — чтобы\nбизнес не зависел от того, выспались вы\nили нет. Дарья теперь может уехать на неделю:\nзаявки подождут в воронке, а не потеряются.",
          font(T_REG, 34), (M, y, 1080 - 2 * M), INK_2, leading=1.44, tag="s8-t")

    counter(d, 8, 9, y=1836, on_dark=False)
    save(im, "story-08-lichnoe.jpg")


def story_09_cta():
    im, d = photo_panel(os.path.join(SRC, "photo-stul-bw.jpg"),
                        focus=(0.50, 0.28), zoom=1.0, panel_top=1000, bw=True)

    eyebrow(d, (M, 118), "3 системы собраны", fill=(255, 255, 255), size=26)

    y = 1086
    y = block(d, "Четвёртая\nможет быть вашей.", font(D_BOLD, 82),
              (M, y, 1080 - 2 * M), INK, leading=1.08, tracking=-2.4, tag="s9-h")
    y += 26
    rule(d, M, y, 96, BRAND, h=5)
    y += 40
    block(d, "Архитектор. Школа иностранных языков.\nЧастная школа. Один принцип: система\nработает вместо вас.",
          font(T_REG, 34), (M, y, 1080 - 2 * M), INK_2, leading=1.42, tag="s9-t")

    y = link_band(d, 1524, SITE, "разбор бизнеса и тест на потери")
    link_band(d, y + 18, DARYA, "система из этой серии — вживую",
              fill=PAPER_ALT, ink=INK, sub=MUTED)

    save(im, "story-09-cta.jpg")


STORIES = [story_01_hero, story_02_vopros, story_03_quote, story_04_before_after,
           story_05_constructor, story_06_principle, story_07_slushal,
           story_08_personal, story_09_cta]


# ===========================================================================
#  КАРУСЕЛЬ 1080×1350 — кейс «Было → Стало» для Instagram и ВК
# ===========================================================================

CM = 80          # поле карусели
CW = 1080 - 2 * CM


def card_ba(n, total, was_h, was_t, now_h, now_t, fname):
    """Слайд-разворот: половина «было», половина «стало».

    Одна и та же сетка на всех слайдах — при листании меняется только текст,
    и глаз сразу находит, куда смотреть. Это и есть половина работы карусели.
    """
    im = paper(CARD, PAPER)
    d = ImageDraw.Draw(im)

    split = 660
    d.rectangle([0, 0, 1080, split], fill=(232, 228, 222))
    d.rectangle([0, split - 6, 1080, split], fill=BRAND)

    draw_tracked(d, (CM, 74), f"{n:02d} / {total:02d}", font(T_MED, 25), (150, 143, 134), tracking=4)
    eyebrow(d, (CM, 150), "было", fill=(140, 133, 124), size=25)

    y = block(d, was_h, font(D_SEMI, 50), (CM, 214, CW), (92, 87, 80),
              leading=1.16, tracking=-1.2, tag=f"c{n}-was-h")
    y += 26
    block(d, was_t, font(T_REG, 32), (CM, y, CW), (128, 121, 112), leading=1.42, tag=f"c{n}-was-t")

    eyebrow(d, (CM, split + 90), "стало", fill=BRAND, size=25)
    y = block(d, now_h, font(D_SEMI, 50), (CM, split + 154, CW), INK,
              leading=1.16, tracking=-1.2, tag=f"c{n}-now-h")
    y += 26
    block(d, now_t, font(T_REG, 32), (CM, y, CW), INK_2, leading=1.42, tag=f"c{n}-now-t")

    save(im, fname)


def card_01_cover():
    im = paper(CARD, PAPER)
    ph = cover(os.path.join(SRC, "photo-chernaya-stena.jpg"), (1080, 700), focus=(0.5, 0.30))
    ph = grade(ph, warmth=1.03, contrast=1.06, sat=0.88)
    im.paste(ph, (0, 0))
    d = ImageDraw.Draw(im)
    d.rectangle([0, 700, 1080, 712], fill=BRAND)

    eyebrow(d, (CM, 92), "кейс · лето 2026", fill=(226, 220, 214), size=25)

    y = block(d, "«Сколько вы теряете\nкаждый месяц?»\n— Не знаю.", font(D_BOLD, 72),
              (CM, 786, CW), INK, leading=1.14, tracking=-2.2, tag="cover-h")
    y += 28
    rule(d, CM, y, 96, BRAND, h=5)
    y += 38
    block(d, "Самый частый ответ — и самый дорогой.\nЗа лето я собрал архитектору систему,\nкоторая закрывает места, где деньги утекали.",
          font(T_REG, 33), (CM, y, CW), INK_2, leading=1.44, tag="cover-t")

    draw_tracked(d, (CM, 1268), "ЛИСТАЙТЕ →", font(T_SEMI, 28), BRAND, tracking=4)
    save(im, "card-01-oblozhka.jpg")


def card_09_final():
    im = paper(CARD, DARK)
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, 1080, 12], fill=BRAND)

    draw_tracked(d, (CM, 100), "09 / 09", font(T_MED, 25), (120, 112, 104), tracking=4)
    eyebrow(d, (CM, 176), "что это дало", fill=(214, 141, 128), size=25)

    rows = [
        ("Первый разговор", "начинается не с нуля"),
        ("Надзор и комплектация", "продаёт сайт, а не уставший человек"),
        ("Правки", "лежат в системе и защищают в суде"),
        ("Заявка", "не может потеряться технически"),
    ]
    y = 250
    for a, b in rows:
        d.rectangle([CM, y + 16, CM + 16, y + 32], fill=BRAND)
        block(d, a, font(T_SEMI, 36), (CM + 44, y, CW - 44), PAPER, leading=1.3, tag="fin-a")
        y = block(d, b, font(T_REG, 34), (CM + 44, y + 48, CW - 44), (176, 168, 160),
                  leading=1.3, tag="fin-b")
        y += 38

    rule(d, CM, 758, CW, (62, 56, 51))

    y = block(d, "Три системы собраны: архитектор,\nшкола языков, частная школа.",
              font(D_SEMI, 46), (CM, 812, CW), PAPER, leading=1.2, tracking=-1.2, tag="fin-h")
    y += 26
    block(d, "Разные бизнесы — один принцип: система делает\nто, на что у собственника не остаётся сил.",
          font(T_REG, 33), (CM, y, CW), (176, 168, 160), leading=1.42, tag="fin-t")

    d.rectangle([CM, 1064, CM + CW, 1180], fill=BRAND)
    draw_tracked(d, (CM + 40, 1088), SITE, font(T_SEMI, 38), PAPER, tracking=0.5)
    draw_tracked(d, (CM + 40, 1138), "разбор бизнеса и тест на потери",
                 font(T_REG, 27), (244, 214, 208), tracking=1)

    d.rectangle([CM, 1198, CM + CW, 1294], fill=(44, 39, 36))
    draw_tracked(d, (CM + 40, 1218), DARYA, font(T_SEMI, 34), PAPER, tracking=0.5)
    draw_tracked(d, (CM + 40, 1260), "система из этого кейса — вживую",
                 font(T_REG, 26), (150, 143, 134), tracking=1)

    save(im, "card-09-final.jpg")


CAROUSEL_BA = [
    (2, "Каждый разговор —\nзаново, голосом",
     "«Пишу или рассказываю им каждый раз с нуля.\nЕсли я устала, могу вообще забыть\nпро что-то сказать»",
     "Клиент собирает\nсостав сам",
     "Конструктор на сайте: комната из блоков.\nВ начале только пол. Потолка нет — и пустое\nместо продаёт авторский надзор само.",
     "card-02-kp.jpg"),
    (3, "Правки живут\nв мессенджере",
     "Их приходится переписывать второй раз ради\nдоговора. «А мне часто просто лень,\nи я этого не делаю»",
     "Правки живут\nв системе",
     "Объём виден обоим, история согласований\nсуществует. Это уже не порядок ради порядка,\nа защита, если заказчик решит поспорить.",
     "card-03-pravki.jpg"),
    (4, "Срок назвать\nневозможно",
     "AutoCAD встал на полдня, созвон на 10 минут\nидёт полчаса. А клиент снял квартиру\nна время ремонта и планирует бюджет.",
     "Срок считается\nв рабочих часах",
     "Вопрос в пятницу вечером получает срок\nдо понедельника. Клиент видит это сразу\nпри отправке. Система не обещает быстрее\nрегламента — даже когда ответ придёт за час.",
     "card-04-sroki.jpg"),
    (5, "Заявки\nтеряются",
     "Не в блокноте — в разговоре и в переписке.\nПри нескольких проектах в год одна\nпотерянная заявка стоит заметной части\nгодовой выручки.",
     "Потеряться\nтехнически нельзя",
     "У заявки обязательное поле «дата следующего\nшага». Просроченные светятся в кабинете\nи уходят напоминанием ночью, сами.",
     "card-05-zayavki.jpg"),
    (6, "Цена — чёрный ящик",
     "Ориентир по телефону, потом пересчёт\nна бумаге. Расхождение между «посчитали»\nи «выставили» — тот самый неприятный разговор.",
     "Цена считается\nодним кодом",
     "И на сайте, и в кабинете. Цены лежат в базе:\nподнять их — поменять числа, а не вёрстку.\nВыставленные КП при этом не меняются.",
     "card-06-cena.jpg"),
    (7, "«Что там с моим\nпроектом?»",
     "Заказчик спрашивает в мессенджере, архитектор\nотвлекается от работы, чтобы ответить.\nИ так по кругу, всё время проекта.",
     "Кабинет отвечает\nза неё",
     "Заказчик заходит и видит плашку «От вас ждут».\nА если ждать нечего — честное «сейчас\nничего не нужно». Это разные экраны\nдля разных вопросов, а не урезанная копия.",
     "card-07-kabinet.jpg"),
    (8, "Всё держится\nна одном человеке",
     "«Мне влом что-то продавать, объяснять.\nХочется, чтобы просто лишний раз не трогали\nи никому ничего не доказывать»",
     "Объясняет система,\nа не человек",
     "Дарья подключается там, где незаменима —\nв творчестве и живом контакте. Пересказ\nсостава пакетов система берёт на себя.",
     "card-08-sistema.jpg"),
]


def build_carousel():
    card_01_cover()
    for n, wh, wt, nh, nt, fn in CAROUSEL_BA:
        card_ba(n, 9, wh, wt, nh, nt, fn)
    card_09_final()


if __name__ == "__main__":
    for fn in STORIES:
        fn()
    build_carousel()
    if OVERFLOW:
        print("\nСтроки, не влезшие в колонку (их перенесло автоматически):")
        for tag, line, got, limit in OVERFLOW:
            print(f"  [{tag}] {got}px > {limit}px — {line}")
    else:
        print("\nВся ручная вёрстка строк влезла.")
