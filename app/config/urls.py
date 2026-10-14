from django.contrib import admin
from django.urls import include, path

from core import views_saude
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health/", views_saude.liveness, name="health"),
    path("api/health/ready/", views_saude.readiness, name="health_ready"),
    path("api/v1/", include("core.urls")),
    # documentacao da API (OpenAPI)
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
]
