# ── landing/management/commands/publish_posts.py ───────────────────────────
"""Публикует посты, которым подошёл срок.

Запускать раз в сутки (или чаще — команда идемпотентна):
    python manage.py publish_posts

Главное правило проекта здесь работает так же, как с заявками:
сначала помечаем в базе, потом отправляем. Если крон запустится дважды
или Telegram ответит с задержкой, пост не уйдёт в канал двумя копиями.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from landing.models import Post
from landing.services import telegram as tg


class Command(BaseCommand):
    help = 'Отправляет в канал посты со статусом «В очереди», которым подошёл срок.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help='Показать, что ушло бы, и ничего не отправлять.')

    def handle(self, *args, **options):
        dry = options['dry_run']
        now = timezone.now()
        due = Post.objects.filter(status=Post.Status.QUEUED, publish_at__lte=now) \
                          .order_by('publish_at')

        if not due.exists():
            self.stdout.write('Публиковать нечего.')
            return

        for post in list(due):
            if dry:
                self.stdout.write(f'[сухой прогон] {post.title}')
                continue

            # Захват через update: два одновременных крона не возьмут
            # один и тот же пост. Кто первый переписал строку — тот и шлёт.
            claimed = Post.objects.filter(pk=post.pk, status=Post.Status.QUEUED) \
                                  .update(status=Post.Status.SENDING)
            if not claimed:
                continue

            image_path = post.image.path if post.image else None
            message_id = tg.publish_post(post.body, image_path)

            if message_id:
                Post.objects.filter(pk=post.pk).update(
                    status=Post.Status.SENT, sent_at=timezone.now(),
                    message_id=message_id, last_error='')
                self.stdout.write(self.style.SUCCESS(f'Опубликован: {post.title}'))
                continue

            attempts = post.attempts + 1
            failed = attempts >= Post.MAX_ATTEMPTS
            Post.objects.filter(pk=post.pk).update(
                status=Post.Status.FAILED if failed else Post.Status.QUEUED,
                attempts=attempts,
                last_error='Telegram не принял сообщение, подробности в logs/app.log')
            self.stdout.write(self.style.ERROR(
                f'Не ушёл ({attempts}/{Post.MAX_ATTEMPTS}): {post.title}'))
            if failed:
                tg.notify(f'Пост «{post.title}» не ушёл {Post.MAX_ATTEMPTS} раза. '
                          f'Смотрите logs/app.log.')
