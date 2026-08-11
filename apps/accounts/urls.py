from django.contrib.auth import views as auth_views
from django.urls import path

from .views import LoginView

app_name = "accounts"

urlpatterns = [
    path("vhod/", LoginView.as_view(), name="login"),
    path("vyhod/", auth_views.LogoutView.as_view(), name="logout"),
]
