"""Формы кабинета.

Все они короткие намеренно. Кабинет — рабочий инструмент человека,
который между делом ведёт стройку: форма на пятнадцать полей не будет
заполнена никогда, а форма на три поля заполняется на ходу с телефона.
"""

import secrets
from decimal import Decimal

from django import forms
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.crm.models import Client, Property
from apps.projects.models import BudgetChange, Project, ProjectPayment, StageTask


class DateField(forms.DateInput):
    """Поле даты, которое браузер понимает.

    Календарь браузера принимает ровно один формат — ГГГГ-ММ-ДД. Django
    же под русской локалью подставляет «13.08.2026», браузер такое значение
    молча выбрасывает, и поле оказывается пустым. Если оно ещё и
    обязательное — форма перестаёт отправляться вообще, без единого
    сообщения: ровно так «Записать оплату» ничего не записывала.
    """

    def __init__(self, attrs=None):
        super().__init__(attrs={"type": "date", **(attrs or {})}, format="%Y-%m-%d")


def generate_password(length=10):
    """Пароль, который можно продиктовать голосом.

    Без похожих друг на друга символов: 0/O и 1/l/I в телефонном разговоре
    неразличимы, а заказчик получает пароль именно так.
    """
    alphabet = "abcdefghijkmnpqrstuvwxyzACDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


class ClientForm(forms.ModelForm):
    """Карточка заказчика. Заводит Дарья, до всякого доступа в кабинет."""

    class Meta:
        model = Client
        # Заметки живут отдельной формой и отдельной панелью: они нужны
        # чаще всего остального в карточке, а в общей форме их каждый раз
        # перезаписывало бы устаревшее значение из соседней вкладки.
        fields = ["name", "phone", "email", "messenger", "source"]

    def clean(self):
        data = super().clean()
        if not data.get("phone") and not data.get("email"):
            raise forms.ValidationError(
                "Нужен хотя бы один контакт: телефон или почта. "
                "Без почты не получится выдать доступ в кабинет."
            )
        return data


class ClientNotesForm(forms.ModelForm):
    """Заметки о заказчике — то, что Дарья держит в голове или в блокноте.

    «Не звонить до десяти», «муж решает всё сам», «просил не трогать
    старый паркет». Ничего из этого нельзя показывать заказчику, но
    забывать тоже нельзя: половина конфликтов растёт ровно отсюда.
    """

    class Meta:
        model = Client
        fields = ["notes"]
        widgets = {
            "notes": forms.Textarea(
                attrs={
                    "rows": 8,
                    "aria-label": "Заметки о заказчике",
                    "placeholder": "Что важно помнить об этом заказчике: "
                    "как с ним удобнее связываться, кто принимает решения, "
                    "о чём договорились на словах.",
                }
            ),
        }
        # Подпись и подсказку берёт на себя заголовок панели: «Заметки —
        # видите только вы». Повторять это ещё дважды вокруг поля незачем.
        labels = {"notes": ""}
        help_texts = {"notes": ""}


class PropertyForm(forms.ModelForm):
    class Meta:
        model = Property
        fields = ["city", "address", "kind", "area", "rooms"]


class AccessForm(forms.Form):
    """Выдача доступа заказчику.

    Логин — почта, пароль Дарья либо придумывает, либо берёт готовый.
    Показывается он ровно один раз, и это правильно: хранить пароли
    в открытом виде нельзя даже ради удобства.
    """

    email = forms.EmailField(label="Почта (это и есть логин)")
    full_name = forms.CharField(label="Имя", max_length=150, required=False)
    password = forms.CharField(
        label="Пароль",
        max_length=64,
        required=False,
        help_text="Оставьте пустым — придумаю сама",
    )

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        self.existing = User.objects.filter(email=email).first()
        return email

    def save(self, client, partner=False):
        """Создать или обновить аккаунт заказчика. Возвращает (user, пароль).

        `partner` — второй человек в паре. Проект чаще всего ведут вдвоём,
        и общий логин на двоих превращает переписку в разговор, где
        не разобрать, кто что просил.
        """
        password = self.cleaned_data.get("password") or generate_password()
        user = self.existing
        if user is None:
            user = User.objects.create_user(
                email=self.cleaned_data["email"],
                password=password,
                phone=client.phone,
                full_name=self.cleaned_data.get("full_name") or client.name,
                role=Role.CLIENT,
            )
        else:
            user.set_password(password)
            if self.cleaned_data.get("full_name"):
                user.full_name = self.cleaned_data["full_name"]
            user.save()

        if partner:
            client.partner = user
        else:
            client.user = user
        client.save(update_fields=["partner" if partner else "user"])
        return user, password


class ProjectForm(forms.ModelForm):
    """Проект: объект, сумма договорённости, дата старта.

    Этапы не спрашиваем — они раскладываются сами по нормативам
    из «Как я работаю». Просить перечислить их руками значит
    гарантировать, что проект заведут без этапов.
    """

    class Meta:
        model = Project
        fields = ["estate", "title", "agreed_amount", "starts_at", "status"]
        widgets = {"starts_at": DateField()}

    def __init__(self, *args, client=None, **kwargs):
        super().__init__(*args, **kwargs)
        if client is not None:
            self.fields["estate"].queryset = client.properties.all()
        self.fields["title"].required = False


class TaskForm(forms.ModelForm):
    """Задача этапа — «что сейчас должно быть сделано»."""

    class Meta:
        model = StageTask
        fields = ["title", "who", "due_date", "comment"]
        widgets = {
            # Поле многострочное намеренно. В однострочном input клавиша
            # Enter отправляет форму, и на телефоне, где эта клавиша
            # подписана «перенос строки», задача добавлялась на середине
            # фразы. Переносы всё равно схлопываются при сохранении:
            # заголовок задачи — одна строка, просто набирают его свободно.
            "title": forms.Textarea(attrs={"rows": 2}),
            "due_date": DateField(),
            "comment": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["title"].widget.attrs["placeholder"] = "Например: прислать фото розеток"

    def clean_title(self):
        return " ".join(self.cleaned_data["title"].split())


class PaymentForm(forms.ModelForm):
    class Meta:
        model = ProjectPayment
        fields = ["kind", "stage", "title", "amount", "paid_on", "comment"]
        widgets = {
            "paid_on": DateField(),
            "comment": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, project=None, **kwargs):
        super().__init__(*args, **kwargs)
        if project is not None:
            self.fields["stage"].queryset = project.stages.order_by("number")
        self.fields["stage"].required = False
        self.fields["title"].required = False
        self.fields["paid_on"].initial = timezone.localdate()

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if amount <= 0:
            raise forms.ValidationError("Сумма оплаты не может быть нулевой или отрицательной.")
        return amount


class BudgetChangeForm(forms.ModelForm):
    """Выход за рамки бюджета.

    Обоснование — обязательное поле, и это главное в этой форме.
    Изменение сметы без причины заказчик читает как «передумали
    и хотят денег», и он прав.
    """

    class Meta:
        model = BudgetChange
        fields = ["title", "amount", "stage", "reason", "consequence"]
        widgets = {
            "reason": forms.Textarea(attrs={"rows": 3}),
            "consequence": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, project=None, **kwargs):
        super().__init__(*args, **kwargs)
        if project is not None:
            self.fields["stage"].queryset = project.stages.order_by("number")
        self.fields["stage"].required = False

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if amount == Decimal("0"):
            raise forms.ValidationError("Изменение на ноль — это не изменение.")
        return amount


class ContractUploadForm(forms.Form):
    """Договор, который заказчик скачает и подпишет."""

    template = forms.ModelChoiceField(label="Шаблон", queryset=None)
    stage = forms.ModelChoiceField(label="Этап", queryset=None, required=False)
    number = forms.CharField(label="Номер", max_length=40, required=False)
    amount = forms.DecimalField(label="Сумма", max_digits=12, decimal_places=2, required=False)
    file = forms.FileField(label="Файл договора", required=False)

    def __init__(self, *args, project=None, **kwargs):
        from apps.contracts.models import ContractTemplate

        super().__init__(*args, **kwargs)
        self.fields["template"].queryset = ContractTemplate.objects.filter(is_active=True)
        self.fields["stage"].queryset = (
            project.stages.order_by("number") if project else None
        )


class MessageForm(forms.Form):
    """Сообщение в переписке по проекту.

    Пустое сообщение без файлов отправить нельзя — иначе в доказательной
    базе появляются пустые строки неизвестного назначения.
    """

    text = forms.CharField(label="Сообщение", widget=forms.Textarea(attrs={"rows": 2}), required=False)

    def __init__(self, *args, files_attached=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.files_attached = files_attached

    def clean_text(self):
        text = (self.cleaned_data.get("text") or "").strip()
        if not text and not self.files_attached:
            raise forms.ValidationError("Напишите сообщение или приложите файл.")
        return text
