from django.urls import path

from . import views

app_name = "billing"

urlpatterns = [
    path("schet/<str:token>/", views.invoice, name="invoice"),
    path("schet/<str:token>/oplatit/", views.pay, name="pay"),
    path("schet/<str:token>/spasibo/", views.return_success, name="return_success"),
    path("schet/<str:token>/oshibka/", views.return_fail, name="return_fail"),
    path("getplatinum/callback/", views.webhook, name="webhook"),
]
