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
def richtext(value):
    if not value:
        return ""

    html = []
    list_open = False
    # Экранируем сразу: дальше в строке уже не может появиться чужой тег.
    for raw in escape(value).splitlines():
        line = raw.strip()

        if line.startswith("- "):
            if not list_open:
                html.append("<ul>")
                list_open = True
            html.append(f"<li>{_inline(line[2:])}</li>")
            continue

        if list_open:
            html.append("</ul>")
            list_open = False

        if not line:
            continue
        if line.startswith("### "):
            html.append(f"<h4>{_inline(line[4:])}</h4>")
        elif line.startswith("## "):
            html.append(f"<h3>{_inline(line[3:])}</h3>")
        elif line.startswith("# "):
            html.append(f"<h2>{_inline(line[2:])}</h2>")
        else:
            html.append(f"<p>{_inline(line)}</p>")

    if list_open:
        html.append("</ul>")
    return mark_safe("\n".join(html))


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
