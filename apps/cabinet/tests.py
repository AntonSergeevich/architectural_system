"""Кабинет: доступ, этапы, задачи, деньги, договоры, переписка.

Проверяем не «страница открылась», а границы: заказчик не должен видеть
чужой проект, не должен закрывать задачи Дарьи и не должен терять
переписку. Всё остальное — детали интерфейса, они меняются.
"""

from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Role, User
from apps.contracts.models import Contract, ContractTemplate
from apps.crm.models import Client, Property
from apps.projects.models import BudgetChange, Message, Project, ProjectPayment, Stage, StageTask


class CabinetTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_catalog", verbosity=0)
        call_command("seed_legal", verbosity=0)
        call_command("seed_tasks", verbosity=0)

        cls.owner = User.objects.create_user(
            email="darya@example.com", password="owner-pass-123", role=Role.OWNER
        )
        cls.client_user = User.objects.create_user(
            email="mariya@example.com", password="client-pass-123", full_name="Мария"
        )
        cls.customer = Client.objects.create(
            name="Мария", phone="+79130000001", email="mariya@example.com", user=cls.client_user
        )
        cls.estate = Property.objects.create(client=cls.customer, area=Decimal("84"), rooms=3)
        cls.project = Project.objects.create(
            client=cls.customer,
            estate=cls.estate,
            title="Квартира на Мира",
            agreed_amount=Decimal("300000"),
            status=Project.Status.ACTIVE,
        )
        from apps.cabinet import services

        services.create_stages(cls.project)
        cls.stage = cls.project.stages.order_by("number").first()

        from apps.contracts.models import ContractTemplate
        from apps.crm.models import Lead

        cls.lead = Lead.objects.create(client=cls.customer, source="сайт")
        cls.contract = ContractTemplate.objects.first()

    def login_owner(self):
        self.client.login(email="darya@example.com", password="owner-pass-123")

    def login_client(self):
        self.client.login(email="mariya@example.com", password="client-pass-123")


class AccessTests(CabinetTestCase):
    def test_cabinet_requires_login(self):
        response = self.client.get(reverse("cabinet:my_project"))
        self.assertEqual(response.status_code, 302)

    def test_client_cannot_open_owner_screens(self):
        self.login_client()
        for name in ["cabinet:dashboard", "cabinet:clients", "cabinet:projects", "cabinet:prices"]:
            with self.subTest(page=name):
                response = self.client.get(reverse(name))
                self.assertNotEqual(response.status_code, 200)

    def test_client_cannot_open_someone_elses_project(self):
        """Самая дорогая ошибка кабинета — показать чужой проект."""
        other = Client.objects.create(name="Пётр", phone="+79130000002")
        other_estate = Property.objects.create(client=other, area=Decimal("50"), rooms=2)
        other_project = Project.objects.create(client=other, estate=other_estate)

        self.login_client()
        response = self.client.post(
            reverse("cabinet:message_send", args=[other_project.pk]), {"text": "подсмотрю"}
        )
        self.assertEqual(response.status_code, 404)
        self.assertFalse(Message.objects.filter(project=other_project).exists())

    def test_owner_pages_open(self):
        self.login_owner()
        pages = [
            ("cabinet:dashboard", []),
            ("cabinet:clients", []),
            ("cabinet:client_detail", [self.customer.pk]),
            ("cabinet:projects", []),
            ("cabinet:project_detail", [self.project.pk]),
        ]
        for name, args in pages:
            with self.subTest(page=name):
                response = self.client.get(reverse(name, args=args))
                self.assertEqual(response.status_code, 200)

    def test_every_owner_page_opens(self):
        """Все экраны Дарьи, без исключений.

        Список страниц собирается из маршрутов, а не пишется руками:
        рукописный список неизбежно отстаёт от кода — именно так две
        страницы уехали на боевой сервер с «Server Error (500)»
        из-за шаблона, удалённого при переезде на общую рамку.
        """
        from django.urls import get_resolver

        self.login_owner()
        skip = {"home", "my_project"}  # редиректы и кабинет заказчика
        args_for = {
            "lead_detail": [self.lead.pk],
            "client_detail": [self.customer.pk],
            "project_detail": [self.project.pk],
            "contract_edit": [self.contract.pk],
        }

        checked = 0
        for pattern in get_resolver().url_patterns:
            if getattr(pattern, "namespace", None) != "cabinet":
                continue
            for route in pattern.url_patterns:
                name = route.name
                if name in skip or not name:
                    continue
                # POST-обработчики проверяются своими тестами.
                if name in args_for or not route.pattern.converters:
                    args = args_for.get(name, [])
                    url = reverse(f"cabinet:{name}", args=args)
                    with self.subTest(page=name):
                        response = self.client.get(url)
                        self.assertIn(
                            response.status_code,
                            (200, 302, 405),
                            f"{name} ({url}) ответил {response.status_code}",
                        )
                    checked += 1
        self.assertGreater(checked, 8, "проверено подозрительно мало страниц")

    def test_client_project_page_opens(self):
        self.login_client()
        response = self.client.get(reverse("cabinet:my_project"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Квартира на Мира")


class TelegramPanelTests(CabinetTestCase):
    """Кнопка привязки должна быть на всех экранах, где стоит панель.

    Панель включается в шаблон, а данные для неё приходят из вида —
    и забыть их можно ровно в одном месте, после чего кабинет честно
    сообщает «бот не настроен» при полностью настроенном боте.
    """

    def test_button_is_shown_wherever_the_panel_is(self):
        pages = [
            ("cabinet:dashboard", [], "darya@example.com", "owner-pass-123"),
            ("cabinet:project_detail", [self.project.pk], "darya@example.com", "owner-pass-123"),
            ("cabinet:my_project", [], "mariya@example.com", "client-pass-123"),
        ]
        with self.settings(TELEGRAM_BOT_TOKEN="токен", TELEGRAM_BOT_USERNAME="daarch_bot"):
            for name, args, email, password in pages:
                with self.subTest(page=name):
                    self.client.login(email=email, password=password)
                    body = self.client.get(reverse(name, args=args)).content.decode()
                    self.assertIn("t.me/daarch_bot?start=", body)
                    self.assertNotIn("Бот пока не настроен", body)


class ClientAccessIssueTests(CabinetTestCase):
    def test_owner_creates_client_and_issues_password(self):
        """Дарья заводит карточку и выдаёт доступ сама, без разработчика."""
        self.login_owner()
        self.client.post(
            reverse("cabinet:clients"),
            {"name": "Новый заказчик", "phone": "8 913 555 44 33", "email": "new@example.com"},
        )
        created = Client.objects.get(name="Новый заказчик")
        self.assertIsNone(created.user)

        response = self.client.post(
            reverse("cabinet:client_access", args=[created.pk]),
            {"email": "new@example.com", "full_name": "Новый заказчик"},
            follow=True,
        )
        created.refresh_from_db()
        self.assertIsNotNone(created.user)
        self.assertEqual(created.user.role, Role.CLIENT)

        # Пароль показывается ровно один раз — и он должен работать.
        shown = response.context["issued_password"]
        self.assertTrue(self.client.login(email="new@example.com", password=shown["password"]))

    def test_project_gets_stages_automatically(self):
        self.login_owner()
        self.client.post(
            reverse("cabinet:client_project", args=[self.customer.pk]),
            {
                "estate": self.estate.pk,
                "title": "Второй объект",
                "agreed_amount": "150000",
                "status": Project.Status.QUEUED,
            },
        )
        project = Project.objects.get(title="Второй объект")
        self.assertEqual(project.stages.count(), 8)


class TaskTests(CabinetTestCase):
    def test_owner_adds_task_from_preset(self):
        from apps.projects.models import TaskPreset

        preset = TaskPreset.objects.filter(stage_number=1).first()
        self.login_owner()
        self.client.post(
            reverse("cabinet:task_add", args=[self.project.pk]),
            {"stage": self.stage.pk, "preset": preset.pk},
        )
        task = StageTask.objects.get(stage=self.stage)
        self.assertEqual(task.title, preset.title)

    def test_owner_adds_custom_task(self):
        self.login_owner()
        self.client.post(
            reverse("cabinet:task_add", args=[self.project.pk]),
            {"stage": self.stage.pk, "title": "Прислать фото розеток", "who": "client"},
        )
        self.assertTrue(StageTask.objects.filter(title="Прислать фото розеток").exists())

    def test_client_closes_own_task_but_not_daryas(self):
        mine = StageTask.objects.create(stage=self.stage, title="Моё", who=StageTask.Owner.CLIENT)
        hers = StageTask.objects.create(stage=self.stage, title="Её", who=StageTask.Owner.OWNER)

        self.login_client()
        url = reverse("cabinet:task_toggle", args=[self.project.pk])
        self.client.post(url, {"task": mine.pk}, headers={"x-requested-with": "XMLHttpRequest"})
        mine.refresh_from_db()
        self.assertTrue(mine.is_done)

        response = self.client.post(
            url, {"task": hers.pk}, headers={"x-requested-with": "XMLHttpRequest"}
        )
        hers.refresh_from_db()
        self.assertEqual(response.status_code, 403)
        self.assertFalse(hers.is_done)

    def test_toggle_without_javascript_returns_a_page(self):
        """Кабинет обязан работать и без JS — форма, а не JSON в лицо."""
        task = StageTask.objects.create(stage=self.stage, title="Что-то", who=StageTask.Owner.OWNER)
        self.login_owner()
        response = self.client.post(
            reverse("cabinet:task_toggle", args=[self.project.pk]), {"task": task.pk}
        )
        self.assertEqual(response.status_code, 302)
        task.refresh_from_db()
        self.assertTrue(task.is_done)


class MoneyTests(CabinetTestCase):
    def test_payments_add_up_and_leave_remainder(self):
        self.login_owner()
        self.client.post(
            reverse("cabinet:payment_add", args=[self.project.pk]),
            {"kind": "prepay", "amount": "100000", "paid_on": "2026-08-01"},
        )
        self.project.refresh_from_db()
        self.assertEqual(self.project.paid_amount, Decimal("100000"))
        self.assertEqual(self.project.left_to_pay, Decimal("200000"))
        self.assertEqual(self.project.paid_percent, 33)

    def test_budget_change_counts_only_after_the_client_agrees(self):
        """Сумма проекта не может вырасти молча — это главное правило."""
        self.login_owner()
        self.client.post(
            reverse("cabinet:budget_add", args=[self.project.pk]),
            {
                "title": "Перенос мокрой зоны",
                "amount": "40000",
                "reason": "Согласование перепланировки требует отдельного проекта",
                "consequence": "Без него узаконить перенос не получится",
            },
        )
        change = BudgetChange.objects.get()
        self.project.refresh_from_db()
        self.assertEqual(self.project.total_amount, Decimal("300000"))

        self.login_client()
        self.client.post(reverse("cabinet:budget_decide", args=[change.pk]), {"decision": "accept"})
        change.refresh_from_db()
        self.project.refresh_from_db()
        self.assertEqual(change.status, BudgetChange.Status.ACCEPTED)
        self.assertEqual(self.project.total_amount, Decimal("340000"))
        self.assertTrue(change.decided_by)

    def test_declined_change_does_not_count(self):
        change = BudgetChange.objects.create(
            project=self.project, title="Доп", amount=Decimal("50000"), reason="потому что"
        )
        self.login_client()
        self.client.post(reverse("cabinet:budget_decide", args=[change.pk]), {"decision": "decline"})
        self.project.refresh_from_db()
        self.assertEqual(self.project.total_amount, Decimal("300000"))

    def test_negative_payment_rejected(self):
        self.login_owner()
        self.client.post(
            reverse("cabinet:payment_add", args=[self.project.pk]),
            {"kind": "stage", "amount": "-5000", "paid_on": "2026-08-01"},
        )
        self.assertFalse(ProjectPayment.objects.exists())


class ContractTests(CabinetTestCase):
    def _contract(self):
        template = ContractTemplate.objects.first()
        return Contract.objects.create(
            template=template,
            project=self.project,
            client=self.customer,
            status=Contract.Status.SENT,
        )

    def test_client_uploads_signed_copy(self):
        contract = self._contract()
        self.login_client()
        self.client.post(
            reverse("cabinet:contract_sign", args=[contract.pk]),
            {"signed_file": SimpleUploadedFile("dogovor.pdf", b"%PDF-1.4 signed")},
        )
        contract.refresh_from_db()
        self.assertTrue(contract.signed_file)
        self.assertEqual(contract.status, Contract.Status.SIGNED)
        self.assertTrue(contract.is_signed)
        self.assertTrue(contract.signed_by)

    def test_signed_upload_is_recorded_in_the_chat(self):
        """Загрузка договора — событие проекта, а не тихая замена файла."""
        contract = self._contract()
        self.login_client()
        self.client.post(
            reverse("cabinet:contract_sign", args=[contract.pk]),
            {"signed_file": SimpleUploadedFile("dogovor.pdf", b"%PDF-1.4 signed")},
        )
        self.assertTrue(Message.objects.filter(project=self.project).exists())

    def test_client_cannot_sign_someone_elses_contract(self):
        other = Client.objects.create(name="Пётр", phone="+79130000003")
        other_estate = Property.objects.create(client=other, area=Decimal("40"), rooms=1)
        other_project = Project.objects.create(client=other, estate=other_estate)
        contract = Contract.objects.create(
            template=ContractTemplate.objects.first(), project=other_project, client=other
        )

        self.login_client()
        response = self.client.post(
            reverse("cabinet:contract_sign", args=[contract.pk]),
            {"signed_file": SimpleUploadedFile("chужой.pdf", b"data")},
        )
        self.assertEqual(response.status_code, 404)
        contract.refresh_from_db()
        self.assertFalse(contract.signed_file)


class ChatTests(CabinetTestCase):
    def test_both_sides_write_and_see_each_other(self):
        self.login_owner()
        self.client.post(
            reverse("cabinet:message_send", args=[self.project.pk]), {"text": "Планировки готовы"}
        )
        self.login_client()
        self.client.post(
            reverse("cabinet:message_send", args=[self.project.pk]), {"text": "Спасибо, смотрю"}
        )

        texts = list(Message.objects.values_list("text", flat=True))
        self.assertEqual(texts, ["Планировки готовы", "Спасибо, смотрю"])
        self.assertTrue(Message.objects.get(text="Планировки готовы").author_is_owner)
        self.assertFalse(Message.objects.get(text="Спасибо, смотрю").author_is_owner)

    def test_message_keeps_the_author_name_for_the_record(self):
        """Аккаунт можно переименовать, а переписка обязана остаться читаемой."""
        self.login_client()
        self.client.post(
            reverse("cabinet:message_send", args=[self.project.pk]), {"text": "вопрос"}
        )
        self.assertEqual(Message.objects.get().author_name, "Мария")

    def test_file_can_be_sent_without_text(self):
        self.login_client()
        self.client.post(
            reverse("cabinet:message_send", args=[self.project.pk]),
            {"text": "", "files": SimpleUploadedFile("plan.pdf", b"%PDF-1.4")},
        )
        message = Message.objects.get()
        self.assertEqual(message.files.count(), 1)
        self.assertEqual(message.files.first().name, "plan.pdf")

    def test_empty_message_is_rejected(self):
        self.login_client()
        self.client.post(reverse("cabinet:message_send", args=[self.project.pk]), {"text": "   "})
        self.assertFalse(Message.objects.exists())

    def test_own_messages_are_marked_as_mine_for_each_side(self):
        """«Своё справа» считается на сервере — иначе стороны разойдутся.

        Заказчик должен видеть свои реплики там же, где видит их в любом
        мессенджере, и Дарья — свои.
        """
        from apps.cabinet import services

        self.login_owner()
        self.client.post(
            reverse("cabinet:message_send", args=[self.project.pk]), {"text": "от Дарьи"}
        )
        message = Message.objects.get()

        self.assertTrue(services.message_json(message, viewer_is_owner=True)["mine"])
        self.assertFalse(services.message_json(message, viewer_is_owner=False)["mine"])

    def test_new_messages_arrive_without_reloading(self):
        """Обе стороны сидят и ждут ответа — обновлять страницу не должен никто."""
        self.login_client()
        self.client.post(
            reverse("cabinet:message_send", args=[self.project.pk]), {"text": "первое"}
        )
        first = Message.objects.get().pk

        self.login_owner()
        url = reverse("cabinet:messages_since", args=[self.project.pk])
        payload = self.client.get(f"{url}?after={first}").json()
        self.assertEqual(payload["messages"], [])

        self.login_client()
        self.client.post(
            reverse("cabinet:message_send", args=[self.project.pk]), {"text": "второе"}
        )

        self.login_owner()
        payload = self.client.get(f"{url}?after={first}").json()
        self.assertEqual(len(payload["messages"]), 1)
        self.assertEqual(payload["messages"][0]["text"], "второе")
        self.assertFalse(payload["messages"][0]["mine"])

    def test_polling_someone_elses_project_is_refused(self):
        other = Client.objects.create(name="Пётр", phone="+79130000009")
        estate = Property.objects.create(client=other, area=Decimal("40"), rooms=1)
        stranger = Project.objects.create(client=other, estate=estate)

        self.login_client()
        response = self.client.get(reverse("cabinet:messages_since", args=[stranger.pk]))
        self.assertEqual(response.status_code, 404)

    def test_opening_the_project_marks_the_other_sides_messages_read(self):
        self.login_client()
        self.client.post(reverse("cabinet:message_send", args=[self.project.pk]), {"text": "вопрос"})
        self.assertIsNone(Message.objects.get().read_at)

        self.login_owner()
        self.client.get(reverse("cabinet:project_detail", args=[self.project.pk]))
        self.assertIsNotNone(Message.objects.get().read_at)


class StageTests(CabinetTestCase):
    def test_stage_status_moves_and_marks_who_we_wait_for(self):
        self.login_owner()
        self.client.post(
            reverse("cabinet:stage_update", args=[self.project.pk]),
            {"stage": self.stage.pk, "status": Stage.Status.REVIEW},
        )
        self.stage.refresh_from_db()
        self.assertEqual(self.stage.waiting_on, Stage.WaitingOn.CLIENT)

    def test_client_approves_stage_and_it_is_recorded(self):
        self.stage.status = Stage.Status.REVIEW
        self.stage.save(update_fields=["status"])

        self.login_client()
        self.client.post(reverse("cabinet:approve_stage", args=[self.stage.pk]))
        self.stage.refresh_from_db()
        self.assertEqual(self.stage.status, Stage.Status.DONE)
        self.assertTrue(hasattr(self.stage, "approval"))
