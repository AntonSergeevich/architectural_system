# ── landing/management/commands/preview_posts.py ───────────────────────────
"""Присылает автору посты, которые выйдут в ближайшие сутки.

Запускать раз в сутки, вечером:
    python manage.py preview_posts

Публикацию в канал нельзя отозвать. Опечатка, устаревшая цена, неудачно
совпавший с новостями пост — всё это чинится одним словом за сутки до
и никак не чинится после. Сутки задержки не стоят ничего, а страховка
от одного плохого поста окупает всю затею.
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from landing.models import Post
from landing.services import telegram as tg


class Command(BaseCommand):
    help = 'Шлёт автору предупреждение о постах, выходящих в ближайшие 24 часа.'

    def handle(self, *args, **options):
        now = timezone.now()
        soon = Post.objects.filter(
            status=Post.Status.QUEUED,
            publish_at__gt=now,
            publish_at__lte=now + timedelta(hours=24),
            announced_at__isnull=True,
        ).order_by('publish_at')

        if not soon.exists():
            self.stdout.write('Предупреждать не о чем.')
            return

        for post in soon:
            when = timezone.localtime(post.publish_at).strftime('%d.%m в %H:%M')
            head = post.body[:600] + ('…' if len(post.body) > 600 else '')
            sent = tg.notify(
                f'<b>Завтра выходит пост</b>\n{when}\n\n{head}\n\n'
                f'Чтобы отменить — поставьте статус «Отменён» в админке.')
            if sent:
                Post.objects.filter(pk=post.pk).update(announced_at=now)
                self.stdout.write(f'Предупредил: {post.title}')
            else:
                # Не проставляем announced_at: пусть попробует завтра снова,
                # иначе пост уйдёт молча, а именно от этого мы и страхуемся.
                self.stdout.write(self.style.ERROR(
                    f'Предупреждение не ушло: {post.title}'))
