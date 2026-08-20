from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from .models import Article, LegalDocument, PortfolioProject


class StaticSitemap(Sitemap):
    changefreq = "monthly"
    priority = 0.8

    def items(self):
        return [
            "public:home",
            "public:about",
            "public:publications",
            "public:services",
            "public:constructor",
            "public:how",
            "public:objections",
            "public:portfolio",
            "public:contacts",
            "public:articles",
        ]

    def location(self, item):
        return reverse(item)


class PortfolioSitemap(Sitemap):
    changefreq = "monthly"
    priority = 0.7

    def items(self):
        return PortfolioProject.objects.filter(is_published=True)


class ArticleSitemap(Sitemap):
    changefreq = "monthly"
    priority = 0.5

    def items(self):
        return Article.objects.filter(is_published=True)


class LegalSitemap(Sitemap):
    changefreq = "yearly"
    priority = 0.2

    def items(self):
        return LegalDocument.objects.filter(is_published=True)


SITEMAPS = {
    "static": StaticSitemap,
    "portfolio": PortfolioSitemap,
    "articles": ArticleSitemap,
    "legal": LegalSitemap,
}
