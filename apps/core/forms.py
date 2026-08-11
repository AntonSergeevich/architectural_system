"""Формы публичного сайта."""

from django import forms
from django.core.exceptions import ValidationError

from apps.catalog.models import ComplexityFactor, ServiceModule
from apps.crm.models import Property

from .utils import normalize_phone


class ConsentMixin(forms.Form):
    """Согласие на обработку персональных данных.

    Отдельно от куки: это разные согласия с разными основаниями, и одной
    галочкой их закрывать нельзя.
    """

    personal_data_consent = forms.BooleanField(
        label="Согласен на обработку персональных данных",
        error_messages={"required": "Без согласия отправить заявку нельзя"},
    )


class LeadForm(ConsentMixin, forms.Form):
    """Заявка с квалификационной анкетой.

    Вопросы про объект задаются здесь, а не голосом на созвоне: тогда
    к разговору Дарья приходит подготовленной, а не собирает вводные заново.
    Часть вопросов заодно показывает, её это человек или нет.
    """

    name = forms.CharField(label="Как вас зовут", max_length=150)
    phone = forms.CharField(label="Телефон", max_length=32, required=False)
    email = forms.EmailField(label="Email", required=False)
    messenger = forms.CharField(label="Telegram или WhatsApp", max_length=100, required=False)

    city = forms.CharField(label="Город", max_length=80, required=False, initial="Красноярск")
    kind = forms.ChoiceField(label="Объект", choices=Property.Kind.choices, required=False)
    area = forms.DecimalField(label="Площадь, м²", max_digits=7, decimal_places=1, required=False, min_value=1)
    rooms = forms.IntegerField(label="Сколько помещений", required=False, min_value=1, max_value=50)
    keys_received = forms.BooleanField(label="Ключи уже получены", required=False)
    has_builders = forms.BooleanField(label="Строители свои", required=False)
    desired_move_in = forms.CharField(label="Когда хотите заехать", max_length=100, required=False)

    complexity = forms.ModelChoiceField(
        label="Какой интерьер хотите",
        queryset=ComplexityFactor.objects.all(),
        required=False,
        empty_label="Пока не знаю",
    )
    decides_alone = forms.BooleanField(
        label="Решение принимаю я (или мы вдвоём), без большого совета",
        required=False,
    )

    message = forms.CharField(label="Что хотите рассказать", widget=forms.Textarea, required=False)
    quote_token = forms.CharField(widget=forms.HiddenInput, required=False)

    # Ловушка для ботов: поле спрятано стилями, человек его не заполнит.
    website = forms.CharField(required=False, widget=forms.HiddenInput)

    def clean_phone(self):
        return normalize_phone(self.cleaned_data.get("phone"))

    def clean_website(self):
        if self.cleaned_data.get("website"):
            raise ValidationError("Не удалось отправить заявку")
        return ""

    def clean(self):
        data = super().clean()
        if not data.get("phone") and not data.get("email") and not data.get("messenger"):
            raise ValidationError("Оставьте хотя бы один способ связи — иначе я не смогу ответить")
        return data


class CalculatorForm(forms.Form):
    """Расчёт из конструктора.

    Работает и без JavaScript: тот же набор полей приходит обычным POST,
    и считает его тот же код. Страница остаётся рабочей всегда, а не только
    когда всё загрузилось.
    """

    area = forms.DecimalField(label="Площадь, м²", max_digits=7, decimal_places=1, min_value=1, max_value=10000)
    rooms = forms.IntegerField(label="Помещений", min_value=1, max_value=50, initial=1)
    complexity = forms.ModelChoiceField(
        label="Характер интерьера", queryset=ComplexityFactor.objects.all(), required=False
    )
    modules = forms.ModelMultipleChoiceField(
        label="Что входит",
        queryset=ServiceModule.objects.filter(is_active=True),
        required=False,
    )
    supervision_months = forms.IntegerField(required=False, min_value=1, max_value=60)
    procurement_stages = forms.IntegerField(required=False, min_value=1, max_value=20)


class ClauseQuestionForm(forms.Form):
    """Отметка «по этому пункту есть вопрос»."""

    clause_id = forms.IntegerField(widget=forms.HiddenInput)
    question = forms.CharField(label="Что непонятно", widget=forms.Textarea, required=False)


class RevisionForm(forms.Form):
    room = forms.CharField(label="Помещение", max_length=120, required=False)
    text = forms.CharField(label="Что поменять", widget=forms.Textarea)
