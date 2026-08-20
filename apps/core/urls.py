from django.urls import path

from . import views

app_name = "public"

urlpatterns = [
    path("", views.home, name="home"),
    path("obo-mne/", views.about, name="about"),
    path("uslugi/", views.services, name="services"),
    path("konstruktor/", views.constructor, name="constructor"),
    path("konstruktor/raschet/", views.calculate_api, name="calculate"),
    path("konstruktor/sohranit/", views.save_quote, name="save_quote"),
    path("kak-ya-rabotayu/", views.how, name="how"),
    path("voprosy/", views.objections, name="objections"),
    path("portfolio/", views.portfolio, name="portfolio"),
    path("portfolio/<slug:slug>/", views.portfolio_detail, name="portfolio_detail"),
    path("publikacii/", views.publications, name="publications"),
    path("poleznoe/", views.articles, name="articles"),
    path("poleznoe/<slug:slug>/", views.article, name="article"),
    path("kontakty/", views.contacts, name="contacts"),
    path("spasibo/", views.thanks, name="thanks"),
    path("kp/<str:token>/", views.quote, name="quote"),
    path("dogovor/<str:token>/", views.contract, name="contract"),
    path("dokumenty/<str:kind>/", views.legal, name="legal"),
    path("cookies/soglasie/", views.cookie_consent, name="cookie_consent"),
]
