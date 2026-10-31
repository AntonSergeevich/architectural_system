"""Простая разметка для текстов, которые Дарья пишет сама.

Полноценный редактор здесь был бы лишним: тексты правятся редко, а любой
визуальный редактор рано или поздно приносит в базу чужую вёрстку. Поэтому
поддерживаем минимум — заголовки, списки, жирный, абзацы — и обязательно
экранируем ввод перед разбором.
"""

import re

from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe

register = template.Library()

_BOLD = re.compile(r"\*\*(.+?)\*\*", re.S)


def _inline(text):
    return _BOLD.sub(r"<strong>\1</strong>", text)


@register.filter(name="richtext")
def richtext(value, mode=""):
    if not value:
        return ""

    html = []
    list_open = False
    part = 0
    # Экранируем сразу: дальше в строке уже не может появиться чужой тег.
    for raw in escape(value).splitlines():
        line = raw.strip()

        # «• » и «– » — так выглядят списки, скопированные из Телеграма
        # и Ворда. Дарья вставляет текст оттуда, а не пишет дефисы.
        bullet = next((m for m in BULLETS if line.startswith(m)), None)
        if bullet:
            if not list_open:
                html.append("<ul>")
                list_open = True
            item = line[len(bullet):].strip()
            if mode == "page":
                item = _term(item)
            html.append(f"<li>{_inline(item)}</li>")
            continue

        if list_open:
            html.append("</ul>")
            list_open = False

        if not line:
            continue
        if line.startswith("### "):
            html.append(f"<h4>{_inline(line[4:])}</h4>")
        elif line.startswith("## "):
            if mode == "page":
                part += 1
                html.append(f'<h3 id="part-{part}">{_inline(line[3:])}</h3>')
            else:
                html.append(f"<h3>{_inline(line[3:])}</h3>")
        elif line.startswith("# "):
            html.append(f"<h2>{_inline(line[2:])}</h2>")
        else:
            html.append(f"<p>{_inline(line)}</p>")

    if list_open:
        html.append("</ul>")
    return mark_safe("\n".join(html))


_NUMBERED = re.compile(r"^(\S+\s+\d+)[.:]\s*(.+)$")


@register.filter(name="richtext_parts")
def richtext_parts(value):
    """Оглавление страницы: подзаголовки «## » по порядку.

    «Этап 1. Базовые материалы» делится на номер и название — так полоска
    наверху страницы показывает путь, а не повторяет заголовки целиком.
    """
    parts = []
    for raw in (value or "").splitlines():
        line = raw.strip()
        if not line.startswith("## "):
            continue
        title = line[3:].replace("**", "").strip()
        match = _NUMBERED.match(title)
        number, name = (match.group(1), match.group(2)) if match else ("", title)
        parts.append({"anchor": f"part-{len(parts) + 1}", "number": number, "title": name})
    return parts


BULLETS = ("- ", "• ", "– ", "•", "* ")


def _term(item):
    """«Окна — с запасом по срокам» → **Окна** — с запасом по срокам.

    Список «что — когда» читается глазами по левому краю. Жирный при
    копировании из Телеграма теряется, поэтому возвращаем его сами —
    но только если человек не расставил его руками.
    """
    if "**" in item or " — " not in item:
        return item
    term, rest = item.split(" — ", 1)
    return f"**{term}** — {rest}"


def plural(number, one, few, many):
    """Русский счёт: 1 день, 2 дня, 5 дней, 21 день, 111 дней."""
    tail, hundred = number % 10, number % 100
    if tail == 1 and hundred != 11:
        return one
    if tail in (2, 3, 4) and hundred not in (12, 13, 14):
        return few
    return many


def _count(value, one, few, many):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return value
    return f"{number} {plural(number, one, few, many)}"


@register.filter(name="workdays")
def workdays(value):
    """7 → «7 рабочих дней», 21 → «21 рабочий день».

    Русский счёт требует трёх форм, и `pluralize` их не умеет. «21 рабочих
    дней» на экране заказчика читается как небрежность — а небрежность
    в мелочах переносят на работу целиком.
    """
    return _count(value, "рабочий день", "рабочих дня", "рабочих дней")


@register.filter(name="stages")
def stages(value):
    """1 → «1 этап», 3 → «3 этапа». В КП стояло «1 этапа»."""
    try:
        value = int(float(value))
    except (TypeError, ValueError):
        return value
    return _count(value, "этап", "этапа", "этапов")


@register.filter(name="days")
def days(value):
    """1 → «1 день», 3 → «3 дня», 22 → «22 дня». Так было «Ваши
    согласования: 1 дней» на странице, которую читает каждый заказчик."""
    return _count(value, "день", "дня", "дней")


@register.filter(name="overdue")
def overdue(days_late):
    """0 → «сегодня», 1 → «со вчера», 3 → «3 дня» — сколько висит касание."""
    try:
        number = int(days_late)
    except (TypeError, ValueError):
        return ""
    if number <= 0:
        return "сегодня"
    if number == 1:
        return "со вчера"
    return f"{number} {plural(number, 'день', 'дня', 'дней')}"


@register.filter(name="rooms")
def rooms(value):
    """1 → «1 помещение», 3 → «3 помещения», 5 → «5 помещений»."""
    return _count(value, "помещение", "помещения", "помещений")


@register.filter(name="money")
def money(value):
    """15000 → «15 000 ₽», с неразрывными пробелами."""
    if value in (None, ""):
        return "—"
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        return value
    return mark_safe(f"{number:,}".replace(",", "&nbsp;") + "&nbsp;₽")
