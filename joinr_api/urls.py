from django.conf import settings
from django.urls import include, path
from drf_yasg import openapi
from drf_yasg.views import get_schema_view
from rest_framework import permissions

from joinr_api.schema import OrderedTagSchemaGenerator

# Create schema view for Swagger and ReDoc
schema_view = get_schema_view(
    openapi.Info(
        title="Joinr API",
        default_version="v1",
        description="API documentation for Joinr HRMS. Click the 'Authorize' button at the top to authenticate.",
        terms_of_service="https://www.joinr.com/terms/",
        contact=openapi.Contact(email="support@joinr.com"),
        license=openapi.License(name="BSD License"),
    ),
    public=settings.DEBUG,
    permission_classes=(
        (permissions.AllowAny,) if settings.DEBUG else (permissions.IsAdminUser,)
    ),
    generator_class=OrderedTagSchemaGenerator,
)

urlpatterns = [
    # API Documentation URLs
    path(
        "swagger<format>/", schema_view.without_ui(cache_timeout=0), name="schema-json"
    ),
    path(
        "swagger/",
        schema_view.with_ui("swagger", cache_timeout=0),
        name="schema-swagger-ui",
    ),
    path("redoc/", schema_view.with_ui("redoc", cache_timeout=0), name="schema-redoc"),
    path("docs/", schema_view.with_ui("swagger", cache_timeout=0), name="schema-docs"),
    # API Endpoints (static configuration)
    path("auth/", include("joinr_api.api_urls.auth.urls")),
    path("asset/", include("joinr_api.api_urls.asset.urls")),
    path("base/", include("joinr_api.api_urls.base.urls")),
    path("employee/", include("joinr_api.api_urls.employee.urls")),
    path("notifications/", include("joinr_api.api_urls.notifications.urls")),
    path("payroll/", include("joinr_api.api_urls.payroll.urls")),
    path("attendance/", include("joinr_api.api_urls.attendance.urls")),
    path("leave/", include("joinr_api.api_urls.leave.urls")),
    path("helpdesk/", include("joinr_api.api_urls.helpdesk.urls")),
    path("project/", include("joinr_api.api_urls.project.urls")),
    path("onboarding/", include("joinr_api.api_urls.onboarding.urls")),
    path("offboarding/", include("joinr_api.api_urls.offboarding.urls")),
    path("recruitment/", include("joinr_api.api_urls.recruitment.urls")),
    path("pms/", include("joinr_api.api_urls.pms.urls")),
    # Screen-shaped aggregates for the mobile client; see api_views/mobile.
    path("mobile/", include("joinr_api.api_urls.mobile.urls")),
]
