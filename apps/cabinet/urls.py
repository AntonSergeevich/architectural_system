from django.urls import path

from . import client as client_views
from . import owner as owner_views
from . import views

app_name = "cabinet"

urlpatterns = [
    path("", views.home, name="home"),
    # --- Дарья ---------------------------------------------------------------
    path("segodnya/", owner_views.dashboard, name="dashboard"),
    path("zayavki/", owner_views.leads, name="leads"),
    path("zayavki/<int:pk>/", owner_views.lead_detail, name="lead_detail"),
    path("zakazchiki/", owner_views.clients, name="clients"),
    path("zakazchiki/<int:pk>/", owner_views.client_detail, name="client_detail"),
    path("zakazchiki/<int:pk>/pravka/", owner_views.client_edit, name="client_edit"),
    path("zakazchiki/<int:pk>/obekt/", owner_views.client_estate, name="client_estate"),
    path("zakazchiki/<int:pk>/dostup/", owner_views.client_access, name="client_access"),
    path("zakazchiki/<int:pk>/proekt/", owner_views.client_project, name="client_project"),
    path("proekty/", owner_views.projects, name="projects"),
    path("proekty/<int:pk>/", owner_views.project_detail, name="project_detail"),
    path("proekty/<int:pk>/etap/", owner_views.move_stage, name="move_stage"),
    path("proekty/<int:pk>/etap/obnovit/", owner_views.stage_update, name="stage_update"),
    path("proekty/<int:pk>/etap/fayl/", owner_views.stage_file, name="stage_file"),
    path("proekty/<int:pk>/zadacha/", owner_views.task_add, name="task_add"),
    path("proekty/<int:pk>/zadacha/udalit/", owner_views.task_delete, name="task_delete"),
    path("proekty/<int:pk>/oplata/", owner_views.payment_add, name="payment_add"),
    path("proekty/<int:pk>/oplata/udalit/", owner_views.payment_delete, name="payment_delete"),
    path("proekty/<int:pk>/smeta/", owner_views.budget_add, name="budget_add"),
    path("proekty/<int:pk>/dogovor/", owner_views.contract_add, name="contract_add"),
    path("ceny/", owner_views.prices, name="prices"),
    path("dogovory/", owner_views.contracts, name="contracts"),
    path("dogovory/<int:pk>/", owner_views.contract_edit, name="contract_edit"),
    path("scheta/", owner_views.invoices, name="invoices"),
    # --- Общее для обеих сторон ----------------------------------------------
    path("proekty/<int:pk>/soobshchenie/", owner_views.message_send, name="message_send"),
    path("proekty/<int:pk>/soobshcheniya/", owner_views.messages_since, name="messages_since"),
    path("proekty/<int:pk>/zadacha/otmetit/", owner_views.task_toggle, name="task_toggle"),
    path("uvedomleniya/", owner_views.telegram_prefs, name="telegram_prefs"),
    # --- Заказчик ------------------------------------------------------------
    path("moy-proekt/", client_views.project, name="my_project"),
    path("moy-proekt/pravka/", client_views.add_revision, name="add_revision"),
    path("moy-proekt/soglasovat/<int:stage_id>/", client_views.approve_stage, name="approve_stage"),
    path("moy-proekt/dogovor/<int:pk>/", client_views.contract_sign, name="contract_sign"),
    path("moy-proekt/smeta/<int:pk>/", client_views.budget_decide, name="budget_decide"),
]
