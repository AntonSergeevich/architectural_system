from django.urls import path

from . import client as client_views
from . import owner as owner_views
from . import views

app_name = "cabinet"

urlpatterns = [
    path("", views.home, name="home"),
    # Дарья
    path("zayavki/", owner_views.leads, name="leads"),
    path("zayavki/<int:pk>/", owner_views.lead_detail, name="lead_detail"),
    path("proekty/", owner_views.projects, name="projects"),
    path("proekty/<int:pk>/", owner_views.project_detail, name="project_detail"),
    path("proekty/<int:pk>/etap/", owner_views.move_stage, name="move_stage"),
    path("ceny/", owner_views.prices, name="prices"),
    path("dogovory/", owner_views.contracts, name="contracts"),
    path("dogovory/<int:pk>/", owner_views.contract_edit, name="contract_edit"),
    path("scheta/", owner_views.invoices, name="invoices"),
    # Заказчик
    path("moy-proekt/", client_views.project, name="my_project"),
    path("moy-proekt/pravka/", client_views.add_revision, name="add_revision"),
    path("moy-proekt/soglasovat/<int:stage_id>/", client_views.approve_stage, name="approve_stage"),
]
