"""Root URL configuration. Versioned API namespace (`/api/v1/...`) from day
one — this is a decade-scale product and v2 will happen eventually."""

from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from apps.common.health_views import liveness, readiness

# Kept as an alias so existing probes, load-balancer configs and uptime
# monitors pointing at /healthz continue to work. See
# `apps/common/health_views.py` for why liveness and readiness are separate.
health_check = liveness


api_v1_patterns = [
    path("auth/", include("apps.users.api.urls")),
    path("tenancy/", include("apps.tenancy.api.urls")),
    path("ledger/", include("apps.ledger.api.urls")),
    path("finance/", include("apps.finance.api.urls")),
    path("budgeting/", include("apps.budgeting.api.urls")),
    path("intelligence/", include("apps.intelligence.api.urls")),
    path("investments/", include("apps.investments.api.urls")),
    path("debt/", include("apps.debt.api.urls")),
    path("analytics/", include("apps.analytics.api.urls")),
    path("projections/", include("apps.projections.api.urls")),
    path("household/", include("apps.household.api.urls")),
    path("receipts/", include("apps.receipts.api.urls")),
    path("goals/", include("apps.goals.api.urls")),
    path("income/", include("apps.income.api.urls")),
    path("notifications/", include("apps.notifications.api.urls")),
    path("billing/", include("apps.billing.api.urls")),
    path("fx/", include("apps.fx.api.urls")),
    # The platform workspace. A sibling of the tenant API, never a child:
    # nothing under this prefix reads X-Tenant-ID or resolves a membership.
    path("platform/", include("apps.platform_admin.api.urls")),
]

urlpatterns = [
    # Django's own admin lives at /django-admin/, NOT /admin/: the platform
    # console is part of the SPA and owns /admin/* in the browser. With both on
    # one origin, giving Django /admin/ made every console page unreachable in
    # production — the reverse proxy sent them to Django's 404.
    path("django-admin/", admin.site.urls),
    path("healthz/", health_check, name="health-check"),
    path("readyz/", readiness, name="readiness-check"),
    path("api/v1/", include(api_v1_patterns)),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
]
