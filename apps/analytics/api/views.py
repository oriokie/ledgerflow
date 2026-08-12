from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.billing.plan_catalogue import PlanFeature
from apps.common.api_base import TenantScopedAPIView, require_feature
from apps.tenancy.models import Role
from apps.tenancy.permissions import IsTenantMember

from .. import reports
from ..filters import ReportFilters
from .serializers import ReportQuerySerializer


def _filters_from(query) -> ReportFilters:
    """Build the frozen filter object from validated query params."""
    s = ReportQuerySerializer(data=query)
    s.is_valid(raise_exception=True)
    v = s.validated_data
    return ReportFilters(
        period=v.get("period") or "last_12_months",
        start=v.get("start"),
        end=v.get("end"),
        # Tuples, so the filter object stays hashable and can key a cache.
        account_ids=tuple(str(i) for i in v.get("account_ids") or ()),
        category_ids=tuple(str(i) for i in v.get("category_ids") or ()),
        currency=(v.get("currency") or "").upper() or None,
        compare_previous=v.get("compare_previous", False),
    )


def _result_out(result) -> dict:
    return {
        "slug": result.slug,
        "title": result.title,
        "currency": result.currency,
        "start": result.start,
        "end": result.end,
        "totals": result.totals,
        "series": result.series,
        "rows": result.rows,
        "meta": result.meta,
    }


class ReportCatalogView(TenantScopedAPIView, APIView):
    """What reports exist, and how each wants to be drawn.

    The client renders from this rather than hard-coding fourteen layouts, so
    adding a report is a backend change alone.
    """

    permission_classes = [IsTenantMember, require_feature(PlanFeature.ADVANCED_REPORTS)]
    required_role = Role.VIEWER
    serializer_class = None

    @extend_schema(operation_id="report_catalog")
    def get(self, request):
        return Response([{"slug": slug, **meta} for slug, meta in reports.REPORT_META.items()])


class ReportView(TenantScopedAPIView, APIView):
    """Run one report.

    204 when a report has nothing to show, rather than a shape full of zeroes —
    an empty chart reads as "you earned nothing", which is a claim rather than
    an absence.
    """

    permission_classes = [IsTenantMember, require_feature(PlanFeature.ADVANCED_REPORTS)]
    required_role = Role.VIEWER
    serializer_class = ReportQuerySerializer

    @extend_schema(operation_id="report_run", parameters=[ReportQuerySerializer])
    def get(self, request, slug):
        if slug not in reports.REPORTS:
            return Response({"detail": f"Unknown report {slug!r}."}, status=status.HTTP_404_NOT_FOUND)
        result = reports.run_report(slug, _filters_from(request.query_params))
        if result.is_empty:
            return Response(status=status.HTTP_204_NO_CONTENT)
        return Response(_result_out(result))


class ReportExportView(TenantScopedAPIView, APIView):
    """A report as CSV.

    Exports whichever of `rows` or `series` the report populated: those are the
    tabular parts, and a totals dict isn't a spreadsheet. Amounts stay in minor
    units here — unlike the debt schedule, this is machine-facing data destined
    for a pivot table, and rounding on the way out would lose precision the
    caller may need.
    """

    permission_classes = [IsTenantMember, require_feature(PlanFeature.ADVANCED_REPORTS)]
    required_role = Role.VIEWER
    serializer_class = None

    @extend_schema(operation_id="report_export")
    def get(self, request, slug):
        import csv
        import io

        from django.http import HttpResponse

        if slug not in reports.REPORTS:
            return Response({"detail": f"Unknown report {slug!r}."}, status=status.HTTP_404_NOT_FOUND)

        result = reports.run_report(slug, _filters_from(request.query_params))
        table = result.rows or result.series
        if not table:
            return Response(status=status.HTTP_204_NO_CONTENT)

        # Union of keys across rows: reports may legitimately omit a field on
        # some rows, and a header taken from the first row alone would silently
        # drop those columns.
        columns: list[str] = []
        for row in table:
            for key in row:
                if key not in columns:
                    columns.append(key)

        from apps.fx.currencies import get_currency

        meta = get_currency(result.currency)
        digits = meta.digits if meta else 2
        scale = 10 ** digits

        expanded: list[str] = []
        for key in columns:
            if key.endswith("_minor"):
                expanded.append(key[:-6])
            expanded.append(key)

        def _row(raw: dict) -> dict:
            out = dict(raw)
            for key, value in raw.items():
                if key.endswith("_minor") and isinstance(value, (int, float)):
                    out[key[:-6]] = f"{value / scale:.{digits}f}"
            return out

        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=expanded, extrasaction="ignore")
        writer.writeheader()
        for row in table:
            writer.writerow(_row(row))

        response = HttpResponse(buffer.getvalue(), content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="{slug}.csv"'
        return response


class FinancialIndependenceView(TenantScopedAPIView, APIView):
    """The projection an advisor would charge a consultation for.

    Read-only and recomputed live: the answer must move with the ledger,
    because a spending change *is* an FI-date change and showing a stale one
    would bury the feedback loop the number exists to create.
    """

    permission_classes = [IsTenantMember, require_feature(PlanFeature.SMART_PLANNING)]
    required_role = Role.VIEWER
    serializer_class = None  # bespoke shape below

    @extend_schema(operation_id="financial_independence")
    def get(self, request):
        from .. import fi

        try:
            projection = fi.project()
        except fi.NotEnoughHistoryError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)

        return Response(
            {
                "currency": projection.currency,
                "as_of": projection.as_of,
                "months_measured": projection.months_measured,
                "monthly_spending_minor": projection.monthly_spending_minor,
                "monthly_savings_minor": projection.monthly_savings_minor,
                "net_worth_minor": projection.net_worth_minor,
                "fi_number_minor": projection.fi_number_minor,
                "swr": projection.swr,
                "progress_pct": projection.progress_pct,
                "band": [
                    {
                        "real_return": point.real_return,
                        "years": point.years,
                        "around_year": point.around_year,
                    }
                    for point in projection.band
                ],
                "never_at_current_pace": projection.never_at_current_pace,
                "required_monthly_for_horizon_minor": projection.required_monthly_for_horizon_minor,
                "horizon_years": fi.FALLBACK_HORIZON_YEARS,
                "caveats": projection.caveats,
            }
        )


class ScenarioPreviewView(TenantScopedAPIView, APIView):
    """What-if modelling. POST because the scenario arrives in a body, but it
    is a pure read — nothing is stored, and the same inputs against the same
    ledger give the same answer."""

    permission_classes = [IsTenantMember, require_feature(PlanFeature.SMART_PLANNING)]
    required_role = Role.VIEWER
    serializer_class = None

    def post(self, request):
        from .. import scenarios

        def _delta(name: str) -> int:
            raw = request.data.get(name, 0)
            try:
                return int(raw)
            except (TypeError, ValueError):
                raise ValueError(name) from None

        try:
            income = _delta("monthly_income_delta_minor")
            expense = _delta("monthly_expense_delta_minor")
        except ValueError as exc:
            return Response(
                {"detail": f"{exc} must be an integer amount in minor units."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        result = scenarios.preview(monthly_income_delta_minor=income, monthly_expense_delta_minor=expense)

        def leg(side) -> dict:
            return {
                "safe_to_spend_minor": side.safe_to_spend_minor,
                "first_negative_on": side.first_negative_on,
                "lowest_balance_minor": side.lowest_balance_minor,
                "fi_years": side.fi_years,
                "fi_number_minor": side.fi_number_minor,
            }

        return Response(
            {
                "currency": result.currency,
                "as_of": result.as_of,
                "monthly_income_delta_minor": result.monthly_income_delta_minor,
                "monthly_expense_delta_minor": result.monthly_expense_delta_minor,
                "baseline": leg(result.baseline),
                "scenario": leg(result.scenario),
                "notes": result.notes,
            }
        )
