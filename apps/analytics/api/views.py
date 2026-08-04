from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.api_base import TenantScopedAPIView
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

    permission_classes = [IsTenantMember]
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

    permission_classes = [IsTenantMember]
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

    permission_classes = [IsTenantMember]
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

        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in table:
            writer.writerow(row)

        response = HttpResponse(buffer.getvalue(), content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="{slug}.csv"'
        return response
