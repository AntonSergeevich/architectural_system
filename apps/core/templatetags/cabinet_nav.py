from django import template
from django.utils import timezone

register = template.Library()


@register.simple_tag
def overdue_leads_count():
    """Сколько заявок с просроченным шагом — цифра на вкладке «Заявки».

    Один запрос COUNT на страницу кабинета Дарьи. Цифра на вкладке
    видна из любого раздела: просрочка не должна ждать, пока Дарья
    сама зайдёт на стол «Сегодня».
    """
    from apps.crm.models import Lead

    return (
        Lead.objects.real()
        .exclude(status__in=[Lead.Status.WON, Lead.Status.LOST])
        .filter(next_action_at__lt=timezone.now())
        .count()
    )
