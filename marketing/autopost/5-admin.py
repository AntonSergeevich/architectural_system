# ── Вставить в landing/admin.py ────────────────────────────────────────────
from django.contrib import admin, messages
from django.utils import timezone

from .models import Post
from .services import telegram as tg


@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display = ('title', 'publish_at', 'status', 'sent_at')
    list_filter = ('status',)
    search_fields = ('title', 'body')
    date_hierarchy = 'publish_at'
    actions = ('queue_posts', 'publish_now', 'cancel_posts')
    readonly_fields = ('sent_at', 'message_id', 'attempts', 'last_error', 'announced_at')

    @admin.action(description='Поставить в очередь')
    def queue_posts(self, request, queryset):
        count = queryset.filter(status__in=(Post.Status.DRAFT, Post.Status.CANCELLED)) \
                        .update(status=Post.Status.QUEUED)
        self.message_user(request, f'В очередь поставлено: {count}')

    @admin.action(description='Отменить')
    def cancel_posts(self, request, queryset):
        count = queryset.exclude(status=Post.Status.SENT) \
                        .update(status=Post.Status.CANCELLED)
        self.message_user(request, f'Отменено: {count}')

    @admin.action(description='Опубликовать сейчас')
    def publish_now(self, request, queryset):
        """Кнопка для тех случаев, когда ждать крон незачем.

        Отправляет по одному и с тем же захватом через update, что и крон:
        два человека, нажавшие кнопку одновременно, не сделают в канале
        два одинаковых поста.
        """
        for post in queryset.exclude(status=Post.Status.SENT):
            claimed = Post.objects.filter(pk=post.pk).exclude(status=Post.Status.SENT) \
                                  .update(status=Post.Status.SENDING)
            if not claimed:
                continue
            message_id = tg.publish_post(post.body, post.image.path if post.image else None)
            if message_id:
                Post.objects.filter(pk=post.pk).update(
                    status=Post.Status.SENT, sent_at=timezone.now(),
                    message_id=message_id, last_error='')
                self.message_user(request, f'Опубликован: {post.title}')
            else:
                Post.objects.filter(pk=post.pk).update(
                    status=Post.Status.FAILED,
                    last_error='Telegram не принял сообщение, см. logs/app.log')
                self.message_user(request, f'Не ушёл: {post.title}', level=messages.ERROR)
