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
from django.utils import timezone

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
            email="mariya@example.com",
            password="client-pass-123",
            full_name="Мария",
            # Согласие на обработку данных заказчик даёт при первом входе.
            # Здесь оно проставлено сразу: остальные тесты про другое,
            # а экран согласия проверяется отдельно в ConsentTests.
            data_consent_at=timezone.now(),
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


class ConsentTests(CabinetTestCase):
    """Согласие на обработку данных при первом входе заказчика.

    Доступ выдала Дарья, форму на сайте заказчик не заполнял — а в кабинете
    лежат его телефон, адрес объекта и переписка. Значит, спросить нужно
    здесь, один раз, и записать в тот же журнал, что и согласия с сайта.
    """

    def setUp(self):
        self.client_user.data_consent_at = None
        self.client_user.save(update_fields=["data_consent_at"])

    def test_cabinet_asks_before_it_opens(self):
        self.login_client()
        response = self.client.get(reverse("cabinet:my_project"))
        self.assertRedirects(response, reverse("cabinet:consent"))

    def test_agreement_is_written_down_and_cabinet_opens(self):
        from apps.core.models import PersonalDataConsent

        self.login_client()
        response = self.client.post(reverse("cabinet:consent"), {"agree": "1"})
        self.assertRedirects(response, reverse("cabinet:my_project"))

        self.client_user.refresh_from_db()
        self.assertIsNotNone(self.client_user.data_consent_at)

        record = PersonalDataConsent.objects.latest("id")
        self.assertEqual(record.name, "Мария")
        self.assertIn("кабинет", record.source)
        self.assertTrue(record.document_version)

        self.assertEqual(self.client.get(reverse("cabinet:my_project")).status_code, 200)

    def test_without_the_checkbox_nothing_is_recorded(self):
        from apps.core.models import PersonalDataConsent

        self.login_client()
        response = self.client.post(reverse("cabinet:consent"), {})
        self.assertEqual(response.status_code, 200)
        self.client_user.refresh_from_db()
        self.assertIsNone(self.client_user.data_consent_at)
        self.assertFalse(PersonalDataConsent.objects.filter(name="Мария").exists())

    def test_owner_is_never_asked(self):
        """У Дарьи нет «первого входа»: это её собственные данные."""
        self.login_owner()
        self.assertEqual(self.client.get(reverse("cabinet:dashboard")).status_code, 200)
        response = self.client.get(reverse("cabinet:consent"))
        self.assertRedirects(
            response, reverse("cabinet:home"), target_status_code=302
        )

    def test_page_has_one_form_per_button(self):
        """Вложенный <form> браузер выбрасывает — кнопка «Выйти» тогда
        отправляла бы согласие."""
        self.login_client()
        body = self.client.get(reverse("cabinet:consent")).content.decode()
        self.assertEqual(body.count("<form"), body.count("</form>"))
        self.assertIn('form="consent-form"', body)


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


class ClientNotesTests(CabinetTestCase):
    """Заметки о заказчике: сохраняются отдельно и не видны заказчику."""

    def test_notes_are_saved_on_their_own(self):
        self.login_owner()
        self.client.post(
            reverse("cabinet:client_notes", args=[self.customer.pk]),
            {"notes": "Звонить после десяти. Решения принимает муж."},
        )
        self.customer.refresh_from_db()
        self.assertIn("после десяти", self.customer.notes)

    def test_saving_the_card_does_not_wipe_the_notes(self):
        """Форма карточки заметок не касается — иначе их стирало бы
        каждое сохранение телефона."""
        self.customer.notes = "Не трогать старый паркет"
        self.customer.save(update_fields=["notes"])

        self.login_owner()
        self.client.post(
            reverse("cabinet:client_edit", args=[self.customer.pk]),
            {"name": "Мария", "phone": "+79130000001", "email": "mariya@example.com"},
        )
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.notes, "Не трогать старый паркет")

    def test_client_never_sees_them(self):
        self.customer.notes = "Торгуется, к цене возвращаться не будем"
        self.customer.save(update_fields=["notes"])

        self.login_client()
        body = self.client.get(reverse("cabinet:my_project")).content.decode()
        self.assertNotIn("Торгуется", body)

        self.assertEqual(
            self.client.post(
                reverse("cabinet:client_notes", args=[self.customer.pk]), {"notes": "своё"}
            ).status_code,
            302,  # редирект на вход, а не сохранение
        )
        self.customer.refresh_from_db()
        self.assertIn("Торгуется", self.customer.notes)


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


class StageFilesTests(CabinetTestCase):
    """Этап сохраняется одной кнопкой — вместе с файлами."""

    def test_status_note_and_files_go_together(self):
        """Раньше форм было две, и половина сделанного пропадала."""
        self.login_owner()
        self.client.post(
            reverse("cabinet:stage_update", args=[self.project.pk]),
            {
                "stage": self.stage.pk,
                "status": Stage.Status.IN_PROGRESS,
                "note": "созвон во вторник",
                "files": [
                    SimpleUploadedFile("plan.pdf", b"%PDF-1.4"),
                    SimpleUploadedFile("foto.jpg", b"\xff\xd8\xff"),
                ],
            },
        )
        self.stage.refresh_from_db()
        self.assertEqual(self.stage.status, Stage.Status.IN_PROGRESS)
        self.assertEqual(self.stage.note, "созвон во вторник")
        self.assertEqual(self.stage.files.count(), 2)

    def test_file_can_be_removed(self):
        """Перепутанный файл должен убираться, а не висеть у заказчика."""
        self.login_owner()
        self.client.post(
            reverse("cabinet:stage_update", args=[self.project.pk]),
            {"stage": self.stage.pk, "files": SimpleUploadedFile("oshibka.jpg", b"\xff\xd8\xff")},
        )
        item = self.stage.files.get()

        self.client.post(
            reverse("cabinet:stage_file_delete", args=[self.project.pk]), {"file": item.pk}
        )
        self.assertEqual(self.stage.files.count(), 0)

    def test_client_cannot_remove_stage_files(self):
        from apps.projects.models import StageFile

        item = StageFile.objects.create(
            stage=self.stage, file=SimpleUploadedFile("plan.jpg", b"\xff\xd8\xff")
        )
        self.login_client()
        response = self.client.post(
            reverse("cabinet:stage_file_delete", args=[self.project.pk]), {"file": item.pk}
        )
        self.assertNotEqual(response.status_code, 200)
        self.assertTrue(self.stage.files.filter(pk=item.pk).exists())

    def test_file_label_is_a_name_not_a_path(self):
        from apps.projects.models import StageFile

        item = StageFile.objects.create(
            stage=self.stage, file=SimpleUploadedFile("438.JPG", b"\xff\xd8\xff")
        )
        self.assertNotIn("/", item.label)
        self.assertTrue(item.is_image)


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


class RailTests(CabinetTestCase):
    """Шкала этапов: доля срока и договор, который ждёт подписи."""

    def test_share_of_the_whole_term_is_counted(self):
        """Восемь равных точек врут: этапы разной длины.

        Доля считается от суммы плановых дней и в сумме даёт примерно
        сотню — «примерно», потому что каждая доля округляется. На шкалу
        она больше не выводится, но остаётся внутри карточки этапа.
        """
        self.login_client()
        response = self.client.get(reverse("cabinet:my_project"))
        shares = [stage.share for stage in response.context["stages"]]
        self.assertEqual(len(shares), 8)
        self.assertAlmostEqual(sum(shares), 100, delta=4)

    def test_rail_is_split_into_three_blocks(self):
        """Три блока по 30, 40 и 30 — так же, как деньги в договоре."""
        self.login_client()
        response = self.client.get(reverse("cabinet:my_project"))
        blocks = response.context["blocks"]

        self.assertEqual([b["share"] for b in blocks], [30, 40, 30])
        self.assertEqual([b["span"] for b in blocks], [3, 3, 2])
        self.assertEqual(sum(b["span"] for b in blocks), 8)
        for block in blocks:
            self.assertContains(response, block["title"])

    def test_stage_percent_is_not_on_the_rail(self):
        """Доля этапа — обещание, которого никто не давал.

        Подбор материалов бывает и десять дней, и месяц: усреднённые
        проценты на шкале превращаются в спор, а не в понимание.
        """
        self.login_client()
        response = self.client.get(reverse("cabinet:my_project"))
        self.assertNotContains(response, "rail__share")

    def test_odd_stage_number_still_lands_in_a_block(self):
        """Нетиповой этап не должен выпасть: скобки стоят над точками."""
        from apps.cabinet import services

        stages = services.stage_shares(self.project.stages.order_by("number"))
        stages.append(Stage(project=self.project, number=42, title="Особый", planned_days=1))
        blocks = services.stage_blocks(stages)
        self.assertEqual(sum(b["span"] for b in blocks), len(stages))

    def test_contract_waiting_marks_its_stage(self):
        contract = Contract.objects.create(
            template=ContractTemplate.objects.first(),
            project=self.project,
            client=self.customer,
            stage=self.stage,
            status=Contract.Status.SENT,
        )

        self.login_client()
        response = self.client.get(reverse("cabinet:my_project"))
        stages = {stage.pk: stage for stage in response.context["stages"]}
        self.assertEqual(stages[self.stage.pk].waiting_contract, [contract])
        self.assertContains(response, "договор ждёт подписи")

        # И он не задваивается: договор этапа живёт на этапе, а в боковой
        # панели остаётся ссылка на него.
        self.assertNotIn(contract, response.context["open_contracts"])
        self.assertIn(contract, response.context["stage_contracts"])

        contract.signed_file = SimpleUploadedFile("d.pdf", b"%PDF-1.4")
        contract.status = Contract.Status.SIGNED
        contract.save(update_fields=["signed_file", "status"])
        response = self.client.get(reverse("cabinet:my_project"))
        stages = {stage.pk: stage for stage in response.context["stages"]}
        self.assertEqual(stages[self.stage.pk].waiting_contract, [])

    def test_stage_payments_are_shown_on_the_stage(self):
        ProjectPayment.objects.create(
            project=self.project, stage=self.stage, amount=Decimal("50000")
        )
        self.login_client()
        response = self.client.get(reverse("cabinet:my_project"))
        stages = {stage.pk: stage for stage in response.context["stages"]}
        self.assertEqual(stages[self.stage.pk].paid, Decimal("50000"))


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

        self.assertTrue(services.message_json(message, self.owner)["mine"])
        self.assertFalse(services.message_json(message, self.client_user)["mine"])

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


class AsyncTests(CabinetTestCase):
    """Действия в кабинете отвечают куском страницы, а не перезагрузкой."""

    def ajax(self, url, data):
        return self.client.post(url, data, HTTP_X_REQUESTED_WITH="XMLHttpRequest")

    def test_task_add_returns_the_stage_card(self):
        self.login_owner()
        response = self.ajax(
            reverse("cabinet:task_add", args=[self.project.pk]),
            {"stage": self.stage.pk, "title": "Прислать фото розеток", "who": "client"},
        )
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertIn("Прислать фото розеток", payload["stage"])
        self.assertIn("rail__items", payload["rail"])
        self.assertEqual(payload["stage_id"], f"stage-{self.stage.pk}")

    def test_task_is_edited_in_place(self):
        task = StageTask.objects.create(stage=self.stage, title="Старое", who="owner")
        self.login_owner()
        payload = self.ajax(
            reverse("cabinet:task_edit", args=[self.project.pk]),
            {"task": task.pk, "title": "Новое", "who": "client"},
        ).json()
        task.refresh_from_db()
        self.assertEqual(task.title, "Новое")
        self.assertEqual(task.who, "client")
        self.assertIn("Новое", payload["stage"])

    def test_line_breaks_do_not_become_part_of_the_task(self):
        """Поле многострочное, чтобы Enter не отправлял форму с телефона.
        Сама задача при этом остаётся одной строкой."""
        self.login_owner()
        self.ajax(
            reverse("cabinet:task_add", args=[self.project.pk]),
            {"stage": self.stage.pk, "title": "Прислать фото\nрозеток  и выводов", "who": "client"},
        )
        task = StageTask.objects.latest("id")
        self.assertEqual(task.title, "Прислать фото розеток и выводов")

    def test_without_javascript_everything_still_redirects(self):
        self.login_owner()
        response = self.client.post(
            reverse("cabinet:task_add", args=[self.project.pk]),
            {"stage": self.stage.pk, "title": "Без скриптов", "who": "owner"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(StageTask.objects.filter(title="Без скриптов").exists())

    def test_payment_form_gives_the_browser_a_date_it_understands(self):
        """Календарь браузера принимает только ГГГГ-ММ-ДД.

        С русской локалью Django подставлял «13.08.2026», браузер такое
        значение выбрасывал, поле оставалось пустым — и обязательная дата
        молча запрещала отправить форму. «Записать оплату» не записывала
        ничего, без единого сообщения.
        """
        from apps.cabinet.forms import PaymentForm

        html = str(PaymentForm(project=self.project)["paid_on"])
        self.assertIn(timezone.localdate().strftime("%Y-%m-%d"), html)


class ArchiveTests(CabinetTestCase):
    """Заказчик не удаляется одной кнопкой.

    За карточкой стоят проекты, договоры, переписка и оплаты — то есть
    доказательная база. Кнопка убирает её в архив, и вернуть можно месяц.
    """

    def test_archive_needs_the_name_typed(self):
        self.login_owner()
        response = self.client.post(
            reverse("cabinet:client_archive", args=[self.customer.pk]), {"confirm": "не то имя"}
        )
        self.assertEqual(response.status_code, 302)
        self.customer.refresh_from_db()
        self.assertFalse(self.customer.is_archived)

    def test_archived_card_hides_and_access_stops(self):
        self.login_owner()
        self.client.post(
            reverse("cabinet:client_archive", args=[self.customer.pk]),
            {"confirm": self.customer.name},
        )
        self.customer.refresh_from_db()
        self.assertTrue(self.customer.is_archived)
        self.assertEqual(self.customer.days_left, Client.ARCHIVE_DAYS)

        # Доступ в кабинет закрывается сразу.
        self.client_user.refresh_from_db()
        self.assertFalse(self.client_user.is_active)
        self.assertFalse(self.client.login(email="mariya@example.com", password="client-pass-123"))

        page = self.client.get(reverse("cabinet:clients"))
        self.assertIn(self.customer, page.context["archived"])
        self.assertNotIn(self.customer, page.context["clients"])

    def test_restore_brings_everything_back(self):
        self.customer.archive()
        self.login_owner()
        self.client.post(
            reverse("cabinet:client_archive", args=[self.customer.pk]), {"restore": "1"}
        )
        self.customer.refresh_from_db()
        self.client_user.refresh_from_db()
        self.assertFalse(self.customer.is_archived)
        self.assertTrue(self.client_user.is_active)
        self.assertTrue(Project.objects.filter(client=self.customer).exists())

    def test_purge_waits_out_the_month(self):
        from django.core.management import call_command

        self.customer.archive()
        call_command("purge_archive", verbosity=0)
        self.assertTrue(Client.objects.filter(pk=self.customer.pk).exists())

        Client.objects.filter(pk=self.customer.pk).update(
            archived_at=timezone.now() - timezone.timedelta(days=Client.ARCHIVE_DAYS + 1)
        )
        call_command("purge_archive", verbosity=0)
        self.assertFalse(Client.objects.filter(pk=self.customer.pk).exists())
        self.assertFalse(User.objects.filter(pk=self.client_user.pk).exists())


class MessageEditTests(CabinetTestCase):
    """Правка сообщения — минута и только своё."""

    def send(self, text="сумма 120 000"):
        self.login_owner()
        self.client.post(reverse("cabinet:message_send", args=[self.project.pk]), {"text": text})
        return Message.objects.latest("id")

    def test_own_message_can_be_fixed_within_a_minute(self):
        message = self.send()
        response = self.client.post(
            reverse("cabinet:message_edit", args=[self.project.pk]),
            {"message": message.pk, "text": "сумма 130 000"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertTrue(response.json()["ok"])
        message.refresh_from_db()
        self.assertEqual(message.text, "сумма 130 000")
        self.assertIsNotNone(message.edited_at)

    def test_after_a_minute_the_history_is_locked(self):
        message = self.send()
        Message.objects.filter(pk=message.pk).update(
            created_at=timezone.now() - timezone.timedelta(minutes=2)
        )
        response = self.client.post(
            reverse("cabinet:message_edit", args=[self.project.pk]),
            {"message": message.pk, "text": "переписываю прошлое"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 403)
        message.refresh_from_db()
        self.assertEqual(message.text, "сумма 120 000")

    def test_someone_elses_message_is_untouchable(self):
        message = self.send()
        self.login_client()
        response = self.client.post(
            reverse("cabinet:message_edit", args=[self.project.pk]),
            {"message": message.pk, "text": "не моё, но поправлю"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 403)
        message.refresh_from_db()
        self.assertEqual(message.text, "сумма 120 000")

    def test_decision_mark_works_from_both_sides(self):
        message = self.send("Договорились: кухня без верхних шкафов")
        self.login_client()
        payload = self.client.post(
            reverse("cabinet:message_decision", args=[self.project.pk]),
            {"message": message.pk},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        ).json()
        self.assertTrue(payload["message"]["decision"])

        page = self.client.get(reverse("cabinet:my_project"))
        self.assertEqual(len(page.context["decisions"]), 1)

        self.client.post(
            reverse("cabinet:message_decision", args=[self.project.pk]),
            {"message": message.pk},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        message.refresh_from_db()
        self.assertFalse(message.is_decision)


class PartnerTests(CabinetTestCase):
    """Пара работает в одном кабинете, но каждый под своим именем."""

    def setUp(self):
        self.partner = User.objects.create_user(
            email="petr@example.com",
            password="partner-pass-1",
            full_name="Пётр",
            data_consent_at=timezone.now(),
        )
        self.customer.partner = self.partner
        self.customer.save(update_fields=["partner"])

    def test_partner_sees_the_same_project(self):
        self.client.login(email="petr@example.com", password="partner-pass-1")
        response = self.client.get(reverse("cabinet:my_project"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Квартира на Мира")

    def test_partner_writes_under_his_own_name(self):
        self.client.login(email="petr@example.com", password="partner-pass-1")
        self.client.post(
            reverse("cabinet:message_send", args=[self.project.pk]), {"text": "а если сдвинуть кухню"}
        )
        message = Message.objects.latest("id")
        self.assertEqual(message.author_name, "Пётр")
        self.assertFalse(message.author_is_owner)

    def test_notifications_reach_both(self):
        from apps.core import notify

        self.assertEqual(
            {u.pk for u in notify._project_users(self.project)},
            {self.client_user.pk, self.partner.pk},
        )


class RoomTests(CabinetTestCase):
    """Файлы этапа разложены по помещениям.

    На одном этапе подбираются обои в гостиную и плитка в санузел,
    и в общей куче миниатюр через месяц не разобрать, где что.
    """

    def upload(self, name="oboi.jpg", room_new="", room="", caption=""):
        return self.client.post(
            reverse("cabinet:stage_update", args=[self.project.pk]),
            {
                "stage": self.stage.pk,
                "status": self.stage.status,
                "note": self.stage.note,
                "room_new": room_new,
                "room": room,
                "caption": caption,
                "files": SimpleUploadedFile(name, b"\x89PNG\r\n"),
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

    def test_new_room_is_created_by_the_same_action(self):
        """Спросить список помещений заранее нельзя: он выясняется
        на обмере, а половина проектов частичные."""
        from apps.projects.models import Room, StageFile

        self.login_owner()
        self.upload(room_new="Гостиная", caption="Обои Loymina Geometrica")

        room = Room.objects.get(project=self.project, title="Гостиная")
        item = StageFile.objects.latest("id")
        self.assertEqual(item.room, room)
        self.assertEqual(item.title, "Обои Loymina Geometrica")

    def test_same_room_is_not_duplicated(self):
        from apps.projects.models import Room

        self.login_owner()
        self.upload(room_new="Санузел")
        self.upload(room_new="Санузел")
        self.assertEqual(Room.objects.filter(project=self.project, title="Санузел").count(), 1)

    def test_files_are_grouped_by_room(self):
        from apps.cabinet import services

        self.login_owner()
        self.upload(name="pol.jpg", room_new="Кухня")
        self.upload(name="obshee.jpg")

        stages = services.stage_shares(self.project.stages.order_by("number"))
        stage = next(s for s in stages if s.pk == self.stage.pk)
        titles = [room.title if room else None for room, _ in stage.file_groups]
        # Без помещения — первым: это «про проект целиком».
        self.assertEqual(titles, [None, "Кухня"])

    def test_caption_can_be_fixed_later(self):
        from apps.projects.models import StageFile

        self.login_owner()
        self.upload(caption="")
        item = StageFile.objects.latest("id")
        self.assertEqual(item.title, "")

        self.client.post(
            reverse("cabinet:stage_file_edit", args=[self.project.pk]),
            {"file": item.pk, "title": "Плитка Kerama на пол", "room_new": "Санузел"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        item.refresh_from_db()
        self.assertEqual(item.title, "Плитка Kerama на пол")
        self.assertEqual(item.room.title, "Санузел")


class PresetTests(CabinetTestCase):
    """Заготовки задач: Дарья правит список сама.

    Половиной готовых формулировок она не пользуется, а половины
    не хватает. Список, из которого нельзя вычеркнуть лишнее,
    перестают читать целиком.
    """

    def test_own_preset_can_be_universal_or_for_this_project_only(self):
        from apps.projects.models import Project, TaskPreset

        self.login_owner()
        self.client.post(
            reverse("cabinet:preset_add", args=[self.project.pk]),
            {"stage": self.stage.pk, "title": "Согласовать снос с УК", "who": "owner",
             "scope": "project"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        preset = TaskPreset.objects.get(title="Согласовать снос с УК")
        self.assertEqual(preset.project, self.project)
        self.assertEqual(preset.stage_number, self.stage.number)

        # В чужом проекте её быть не должно.
        other = Project.objects.create(client=self.customer, estate=self.estate, title="Другой")
        from apps.cabinet import services

        services.create_stages(other)
        other_stage = other.stages.filter(number=self.stage.number).first()
        self.assertNotIn(preset, TaskPreset.for_stage(other_stage))
        self.assertIn(preset, TaskPreset.for_stage(self.stage))

    def test_preset_is_edited_in_place(self):
        from apps.projects.models import TaskPreset

        preset = TaskPreset.objects.create(title="Старое", who="owner", stage_number=self.stage.number)
        self.login_owner()
        self.client.post(
            reverse("cabinet:preset_edit", args=[self.project.pk]),
            {"stage": self.stage.pk, "preset": preset.pk, "title": "Новое", "who": "client",
             "scope": "project"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        preset.refresh_from_db()
        self.assertEqual(preset.title, "Новое")
        self.assertEqual(preset.who, "client")
        self.assertEqual(preset.project, self.project)

    def test_universal_preset_is_hidden_not_destroyed(self):
        """Общую заготовку прячем: она нужна другим проектам, и вернуть
        её должно быть можно. Проектную удаляем совсем."""
        from apps.projects.models import TaskPreset

        shared = TaskPreset.objects.create(title="Общая", stage_number=self.stage.number)
        mine = TaskPreset.objects.create(
            title="Только тут", stage_number=self.stage.number, project=self.project
        )
        self.login_owner()
        for preset in (shared, mine):
            self.client.post(
                reverse("cabinet:preset_edit", args=[self.project.pk]),
                {"stage": self.stage.pk, "preset": preset.pk, "remove": "1"},
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            )

        shared.refresh_from_db()
        self.assertFalse(shared.is_active)
        self.assertNotIn(shared, TaskPreset.for_stage(self.stage))
        self.assertFalse(TaskPreset.objects.filter(pk=mine.pk).exists())


class SpamTests(CabinetTestCase):
    """Спам не должен занимать место в воронке и исчезать без следа."""

    def setUp(self):
        from apps.crm.models import Lead

        self.junk_client = Client.objects.create(name="Seo Master", email="seo@spam.xyz")
        self.junk = Lead.objects.create(
            client=self.junk_client,
            source="сайт",
            message="продвижение сайтов https://spam.xyz",
            is_spam=True,
            spam_reason="ссылки в сообщении",
        )

    def test_spam_is_out_of_the_funnel(self):
        self.login_owner()
        response = self.client.get(reverse("cabinet:leads"))
        self.assertNotIn(self.junk, response.context["leads"])
        self.assertIn(self.junk, response.context["spam"])

    def test_delete_removes_lead_and_its_client(self):
        """Карточка, заведённая рассылкой, уходит вместе с заявкой.

        Иначе спам оседает в списке заказчиков, и разбирать его там
        уже никто не будет.
        """
        from apps.crm.models import Lead

        self.login_owner()
        self.client.post(reverse("cabinet:lead_delete", args=[self.junk.pk]))
        self.assertFalse(Lead.objects.filter(pk=self.junk.pk).exists())
        self.assertFalse(Client.objects.filter(pk=self.junk_client.pk).exists())

    def test_delete_keeps_client_with_projects(self):
        """Заявку удаляем, живого заказчика — никогда."""
        from apps.crm.models import Lead

        self.login_owner()
        self.client.post(reverse("cabinet:lead_delete", args=[self.lead.pk]))
        self.assertFalse(Lead.objects.filter(pk=self.lead.pk).exists())
        self.assertTrue(Client.objects.filter(pk=self.customer.pk).exists())

    def test_not_spam_returns_lead_to_the_funnel(self):
        self.login_owner()
        self.client.post(reverse("cabinet:lead_spam", args=[self.junk.pk]), {"restore": "1"})
        self.junk.refresh_from_db()
        self.assertFalse(self.junk.is_spam)
        self.assertEqual(self.junk.spam_reason, "")

    def test_client_cannot_delete_leads(self):
        from apps.crm.models import Lead

        self.login_client()
        response = self.client.post(reverse("cabinet:lead_delete", args=[self.junk.pk]))
        self.assertNotEqual(response.status_code, 200)
        self.assertTrue(Lead.objects.filter(pk=self.junk.pk).exists())


class ProjectStartTests(CabinetTestCase):
    """Проект и объект заводятся одной формой.

    Двухшаговость давала тупик: у нового заказчика список объектов пуст,
    выбирать не из чего, а форма нового объекта пряталась ниже кнопки.
    """

    def setUp(self):
        self.fresh = Client.objects.create(name="Пётр", phone="+79130000009")

    def test_new_client_sees_object_fields_not_an_empty_list(self):
        self.login_owner()
        response = self.client.get(reverse("cabinet:client_detail", args=[self.fresh.pk]))
        self.assertContains(response, "new_area")
        self.assertFalse(response.context["project_form"].has_estates)

    def test_project_and_estate_are_created_together(self):
        self.login_owner()
        self.client.post(
            reverse("cabinet:client_project", args=[self.fresh.pk]),
            {
                "new_city": "Красноярск",
                "new_address": "Взлётка, 12",
                "new_kind": "new",
                "new_area": "62",
                "new_rooms": "3",
                "title": "Квартира на Взлётке",
                "agreed_amount": "250000",
                "status": Project.Status.QUEUED,
            },
        )
        project = Project.objects.get(client=self.fresh)
        self.assertEqual(project.estate.area, Decimal("62"))
        self.assertEqual(project.estate.rooms, 3)
        self.assertEqual(project.estate.client, self.fresh)
        # Этапы раскладываются сами — иначе проект заведут без них.
        self.assertEqual(project.stages.count(), 8)

    def test_existing_estate_is_reused(self):
        estate = Property.objects.create(client=self.fresh, area=Decimal("40"), rooms=2)
        self.login_owner()
        self.client.post(
            reverse("cabinet:client_project", args=[self.fresh.pk]),
            {"estate": estate.pk, "title": "Студия", "agreed_amount": "100000",
             "status": Project.Status.QUEUED},
        )
        project = Project.objects.get(client=self.fresh)
        self.assertEqual(project.estate, estate)
        self.assertEqual(Property.objects.filter(client=self.fresh).count(), 1)

    def test_without_estate_and_area_the_reason_is_named(self):
        """«Проверьте поля» без указания поля заставляет угадывать."""
        self.login_owner()
        response = self.client.post(
            reverse("cabinet:client_project", args=[self.fresh.pk]),
            {"title": "Ничего", "agreed_amount": "0", "status": Project.Status.QUEUED},
            follow=True,
        )
        self.assertFalse(Project.objects.filter(client=self.fresh).exists())
        self.assertContains(response, "нужна хотя бы площадь")

    def test_choosing_and_typing_at_once_is_refused(self):
        """Молча предпочесть одно нельзя: вместо правки вышел бы дубль."""
        estate = Property.objects.create(client=self.fresh, area=Decimal("40"), rooms=2)
        self.login_owner()
        response = self.client.post(
            reverse("cabinet:client_project", args=[self.fresh.pk]),
            {"estate": estate.pk, "new_area": "62", "new_rooms": "3",
             "title": "Спор", "agreed_amount": "0", "status": Project.Status.QUEUED},
            follow=True,
        )
        self.assertFalse(Project.objects.filter(client=self.fresh).exists())
        self.assertContains(response, "оставьте что-то одно")
