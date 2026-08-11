"""Поле формы одной строкой в шаблоне.

Кабинет — это два десятка мелких форм. Расписывать у каждой label,
input, ошибку и подсказку значит гарантированно где-нибудь забыть вывод
ошибки, и человек будет жать «Сохранить», не понимая, почему ничего
не сохраняется.
"""

from django import template

register = template.Library()


@register.inclusion_tag("components/field.html")
def field(bound_field, placeholder=""):
    if placeholder:
        bound_field.field.widget.attrs.setdefault("placeholder", placeholder)
    return {"field": bound_field}
