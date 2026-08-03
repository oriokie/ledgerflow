from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.api_base import TenantScopedAPIView, WriteRequiresMemberMixin
from apps.finance.models import FinancialAccount
from apps.tenancy.models import Role
from apps.tenancy.permissions import IsTenantMember

from .. import payoff, selectors, services
from .serializers import (
    ConsolidationSerializer,
    DebtTermsSerializer,
    OffsetAccountsSerializer,
    PayoffQuerySerializer,
    RateChangeSerializer,
    RefinanceSerializer,
    ScenarioComparisonSerializer,
)


def _view_out(v) -> dict:
    return {
        "account_id": v.account_id,
        "name": v.name,
        "currency": v.currency,
        "debt_kind": v.debt_kind,
        "balance_minor": v.balance_minor,
        "apr": float(v.apr),
        "minimum_payment_minor": v.minimum_payment_minor,
        "payment_day": v.payment_day,
        "monthly_interest_minor": v.monthly_interest_minor,
        # The single most important boolean here: paying on time and still
        # owing more.
        "minimum_covers_interest": v.minimum_covers_interest,
        "original_principal_minor": v.original_principal_minor,
        # Null when the original principal isn't known — a balance alone can't
        # say how far through you are.
        "percent_repaid": v.percent_repaid,
        "include_in_payoff": v.include_in_payoff,
        "has_terms": v.profile_id is not None,
        "compounding": v.compounding,
        "offset_minor": v.offset_minor,
        # Countdown so the UI can warn before a promotional rate expires.
        "promo_days_remaining": v.promo_days_remaining,
        "promo_ends_on": v.promo_ends_on,
        "next_rate_change_on": v.next_rate_change_on,
        "next_rate_apr": float(v.next_rate_apr) if v.next_rate_apr is not None else None,
        "rate_schedule": [
            {"effective_from": p.effective_from, "apr": float(p.apr)} for p in v.rate_schedule
        ],
        "fees": (
            {
                "monthly_minor": v.fees.monthly_minor,
                "annual_minor": v.fees.annual_minor,
                "origination_minor": v.fees.origination_minor,
            }
            if v.fees
            else None
        ),
    }


class DebtListView(TenantScopedAPIView, APIView):
    """Every outstanding liability, with terms where they've been recorded."""

    permission_classes = [IsTenantMember]
    required_role = Role.VIEWER
    serializer_class = None

    @extend_schema(operation_id="debts_list")
    def get(self, request):
        return Response([_view_out(v) for v in selectors.debt_views()])


class DebtTermsView(WriteRequiresMemberMixin, TenantScopedAPIView, APIView):
    """Set or clear the repayment terms on a liability account."""

    permission_classes = [IsTenantMember]
    serializer_class = DebtTermsSerializer

    def put(self, request, account_id):
        account = FinancialAccount.objects.filter(id=account_id).first()
        if account is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        s = DebtTermsSerializer(data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        try:
            services.set_debt_terms(financial_account=account, **s.validated_data)
        except services.DebtError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        view = next(
            (v for v in selectors.debt_views() if v.account_id == str(account.id)), None
        )
        return Response(_view_out(view) if view else {}, status=status.HTTP_200_OK)

    def delete(self, request, account_id):
        account = FinancialAccount.objects.filter(id=account_id).first()
        if account is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        services.clear_debt_terms(financial_account=account)
        return Response(status=status.HTTP_204_NO_CONTENT)


class TrackedLiabilitiesView(TenantScopedAPIView, APIView):
    """Liability accounts that exist, whether or not anything is owed on them.

    Returns a list (possibly empty) rather than 204: "you have two cards, both
    at zero" and "you have no cards" are different answers, and the page needs
    to tell them apart to know whether the user's setup worked.
    """

    permission_classes = [IsTenantMember]
    required_role = Role.VIEWER
    serializer_class = None

    @extend_schema(operation_id="debt_tracked_liabilities")
    def get(self, request):
        return Response(selectors.tracked_liabilities())


class DebtSummaryView(TenantScopedAPIView, APIView):
    """Headline debt figures, alerts, and a suggested strategy.

    204 when nothing is owed — a row of zeroes is a worse answer than "you have
    no debt".
    """

    permission_classes = [IsTenantMember]
    required_role = Role.VIEWER
    serializer_class = None

    @extend_schema(operation_id="debt_summary")
    def get(self, request):
        summary = selectors.debt_summary()
        if summary is None:
            return Response(status=status.HTTP_204_NO_CONTENT)

        extra = int(request.query_params.get("extra_monthly_minor", 0) or 0)
        return Response(
            {
                "currency": summary.currency,
                "total_balance_minor": summary.total_balance_minor,
                "total_minimum_minor": summary.total_minimum_minor,
                "total_monthly_interest_minor": summary.total_monthly_interest_minor,
                # The number that actually persuades: monthly interest is easy
                # to shrug off, the annual figure much less so.
                "annual_interest_minor": summary.annual_interest_minor,
                "debt_count": summary.debt_count,
                "weighted_apr": summary.weighted_apr,
                "highest_apr_name": summary.highest_apr_name,
                "highest_apr": summary.highest_apr,
                "unplannable_count": summary.unplannable_count,
                "growing_count": summary.growing_count,
                # Debts the rate and interest figures were derived from. The UI
                # needs this to tell a measured zero from an unmeasured one.
                "priced_count": summary.priced_count,
                "alerts": [
                    {
                        "severity": a.severity,
                        "title": a.title,
                        "body": a.body,
                        "account_id": a.account_id,
                    }
                    for a in selectors.debt_alerts()
                ],
                "recommendation": selectors.debt_recommendation(extra_monthly_minor=extra),
            }
        )


class PayoffPlanView(TenantScopedAPIView, APIView):
    """A full payoff simulation, plus how it compares to the alternatives."""

    permission_classes = [IsTenantMember]
    required_role = Role.VIEWER
    serializer_class = PayoffQuerySerializer

    @extend_schema(operation_id="debt_payoff_plan", parameters=[PayoffQuerySerializer])
    def get(self, request):
        q = PayoffQuerySerializer(data=request.query_params)
        q.is_valid(raise_exception=True)
        v = q.validated_data

        plan = selectors.payoff_plan(
            strategy=v["strategy"], extra_monthly_minor=v["extra_monthly_minor"]
        )
        if plan is None:
            return Response(status=status.HTTP_204_NO_CONTENT)

        return Response(
            {
                "strategy": plan.strategy,
                "currency": plan.currency,
                "monthly_budget_minor": plan.monthly_budget_minor,
                "extra_monthly_minor": plan.extra_monthly_minor,
                "months_to_debt_free": plan.months_to_debt_free,
                "debt_free_on": plan.debt_free_on,
                "total_interest_minor": plan.total_interest_minor,
                "total_paid_minor": plan.total_paid_minor,
                "is_complete": plan.is_complete,
                # Non-empty means the plan can't finish: some debt's payment
                # doesn't cover its interest.
                "stuck_debt_ids": plan.stuck_debt_ids,
                "per_debt": [
                    {
                        "debt_id": p.debt_id,
                        "name": p.name,
                        "starting_balance_minor": p.starting_balance_minor,
                        "interest_paid_minor": p.interest_paid_minor,
                        "total_paid_minor": p.total_paid_minor,
                        "months_to_clear": p.months_to_clear,
                        "cleared_on": p.cleared_on,
                        "never_clears": p.never_clears,
                    }
                    for p in plan.per_debt
                ],
                "calendar": selectors.payoff_calendar(
                    strategy=v["strategy"],
                    extra_monthly_minor=v["extra_monthly_minor"],
                    months=v["months"],
                ),
                "comparison": [
                    {
                        "strategy": c.strategy,
                        "months_to_debt_free": c.months_to_debt_free,
                        "debt_free_on": c.debt_free_on,
                        "total_interest_minor": c.total_interest_minor,
                        "interest_saved_minor": c.interest_saved_minor,
                        "months_saved": c.months_saved,
                        "first_cleared_name": c.first_cleared_name,
                        "first_cleared_months": c.first_cleared_months,
                    }
                    for c in selectors.strategy_comparison(
                        extra_monthly_minor=v["extra_monthly_minor"]
                    )
                ],
            }
        )


class ExtraPaymentCurveView(TenantScopedAPIView, APIView):
    """What each additional monthly amount would buy.

    Returned as a curve because the returns are steeply non-linear: seeing that
    the first small increment saves disproportionately more than the next is
    what actually changes behaviour.
    """

    permission_classes = [IsTenantMember]
    required_role = Role.VIEWER
    serializer_class = None

    @extend_schema(operation_id="debt_extra_payment_curve")
    def get(self, request):
        strategy = request.query_params.get("strategy", "avalanche")
        return Response(selectors.extra_payment_curve(strategy=strategy))


class RateHistoryView(WriteRequiresMemberMixin, TenantScopedAPIView, APIView):
    """A debt's rate timeline.

    Append-only by intent: posting a change never rewrites an earlier entry, so
    a projection run last March still reflects the rate in force then.
    """

    permission_classes = [IsTenantMember]
    serializer_class = RateChangeSerializer

    @extend_schema(operation_id="debt_rate_history")
    def get(self, request, account_id):
        view = next(
            (v for v in selectors.debt_views() if v.account_id == str(account_id)), None
        )
        if view is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        history = [
            {"effective_from": p.effective_from, "apr": float(p.apr)} for p in view.rate_schedule
        ]
        # Balance-weighted is meaningless across time; a plain mean of the
        # recorded rates is what "historical average" honestly means here.
        average = round(sum(h["apr"] for h in history) / len(history), 2) if history else None
        return Response(
            {
                "current_apr": float(view.apr),
                "history": history,
                "historical_average_apr": average,
                "next_change_on": view.next_rate_change_on,
                "next_apr": float(view.next_rate_apr) if view.next_rate_apr is not None else None,
            }
        )

    def post(self, request, account_id):
        account = FinancialAccount.objects.filter(id=account_id).first()
        if account is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        s = RateChangeSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            entry = services.record_rate_change(financial_account=account, **s.validated_data)
        except services.DebtError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        return Response(
            {"id": entry.id, "apr": float(entry.apr), "effective_from": entry.effective_from},
            status=status.HTTP_201_CREATED,
        )


class OffsetAccountsView(WriteRequiresMemberMixin, TenantScopedAPIView, APIView):
    """Link accounts that reduce the interest charged on a debt.

    Changes no balance on either side — offsetting is an arrangement about how
    interest is computed, not a transfer, so nothing posts to the ledger.
    """

    permission_classes = [IsTenantMember]
    serializer_class = OffsetAccountsSerializer

    def put(self, request, account_id):
        account = FinancialAccount.objects.filter(id=account_id).first()
        if account is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        s = OffsetAccountsSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            services.set_offset_accounts(
                financial_account=account, account_ids=s.validated_data["account_ids"]
            )
        except services.DebtError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        view = next(
            (v for v in selectors.debt_views() if v.account_id == str(account.id)), None
        )
        return Response(_view_out(view) if view else {})


class DebtStressView(TenantScopedAPIView, APIView):
    """The Debt Stress Score with its full derivation."""

    permission_classes = [IsTenantMember]
    required_role = Role.VIEWER
    serializer_class = None

    @extend_schema(operation_id="debt_stress_score")
    def get(self, request):
        result = selectors.debt_stress()
        if result is None:
            return Response(status=status.HTTP_204_NO_CONTENT)
        return Response(result)


class BorrowingCostView(TenantScopedAPIView, APIView):
    """Annual cost of carrying debt, split into interest and fees."""

    permission_classes = [IsTenantMember]
    required_role = Role.VIEWER
    serializer_class = None

    @extend_schema(operation_id="debt_borrowing_cost")
    def get(self, request):
        cost = selectors.borrowing_cost()
        if cost is None:
            return Response(status=status.HTTP_204_NO_CONTENT)
        return Response(
            {
                "currency": cost.currency,
                "annual_interest_minor": cost.annual_interest_minor,
                "annual_fees_minor": cost.annual_fees_minor,
                "annual_total_minor": cost.annual_total_minor,
                "monthly_interest_minor": cost.monthly_interest_minor,
                "monthly_fees_minor": cost.monthly_fees_minor,
                # Reported separately so a card whose real cost is mostly a fee
                # can't hide behind a modest rate.
                "fee_share": cost.fee_share,
                # How much of the picture these figures were computed from. A
                # zero cost across debts with no terms recorded is missing
                # data, not a free loan, and the two must not look alike.
                "priced_count": cost.priced_count,
                "debt_count": cost.debt_count,
            }
        )


class RefinanceSimulationView(TenantScopedAPIView, APIView):
    """Simulate refinancing one debt. Read-only: nothing is modified."""

    permission_classes = [IsTenantMember]
    required_role = Role.VIEWER
    serializer_class = RefinanceSerializer

    @extend_schema(operation_id="debt_simulate_refinance", request=RefinanceSerializer)
    def post(self, request, account_id):
        views = [v for v in selectors.debt_views() if v.account_id == str(account_id)]
        if not views:
            return Response(status=status.HTTP_404_NOT_FOUND)
        inputs = selectors.to_debt_inputs(views)
        if not inputs:
            return Response(
                {"detail": "Add a minimum payment before simulating a refinance."},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        s = RefinanceSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data
        result = payoff.simulate_refinance(
            inputs[0],
            payoff.RefinanceQuote(
                new_apr=v["new_apr"],
                new_minimum_payment_minor=v["new_minimum_payment_minor"],
                closing_costs_minor=v["closing_costs_minor"],
                capitalise_costs=v["capitalise_costs"],
                compounding=v["compounding"],
            ),
        )
        return Response(
            {
                "current_total_cost_minor": result.current_total_cost_minor,
                "new_total_cost_minor": result.new_total_cost_minor,
                "lifetime_saving_minor": result.lifetime_saving_minor,
                "current_months": result.current_months,
                "new_months": result.new_months,
                "months_saved": result.months_saved,
                "current_monthly_minor": result.current_monthly_minor,
                "new_monthly_minor": result.new_monthly_minor,
                # The number that decides it: a saving that arrives after the
                # user expects to have moved or repaid never arrives at all.
                "breakeven_month": result.breakeven_month,
                "closing_costs_minor": result.closing_costs_minor,
                "is_worthwhile": result.is_worthwhile,
            }
        )


class ConsolidationSimulationView(TenantScopedAPIView, APIView):
    """Simulate combining several debts. Read-only."""

    permission_classes = [IsTenantMember]
    required_role = Role.VIEWER
    serializer_class = ConsolidationSerializer

    @extend_schema(operation_id="debt_simulate_consolidation", request=ConsolidationSerializer)
    def post(self, request):
        s = ConsolidationSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data

        wanted = {str(i) for i in v["account_ids"]}
        views = [x for x in selectors.debt_views() if x.account_id in wanted]
        inputs = selectors.to_debt_inputs(views)
        result = payoff.simulate_consolidation(
            inputs,
            payoff.ConsolidationQuote(
                new_apr=v["new_apr"],
                new_minimum_payment_minor=v["new_minimum_payment_minor"],
                fees_minor=v["fees_minor"],
                compounding=v["compounding"],
            ),
        )
        if result is None:
            return Response(
                {"detail": "Consolidation needs at least two debts with terms recorded."},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        return Response(
            {
                "debt_count": result.debt_count,
                "combined_balance_minor": result.combined_balance_minor,
                "current_total_cost_minor": result.current_total_cost_minor,
                "new_total_cost_minor": result.new_total_cost_minor,
                "lifetime_saving_minor": result.lifetime_saving_minor,
                "current_months": result.current_months,
                "new_months": result.new_months,
                "months_saved": result.months_saved,
                "current_monthly_minor": result.current_monthly_minor,
                "new_monthly_minor": result.new_monthly_minor,
                "current_weighted_apr": result.current_weighted_apr,
                "new_apr": result.new_apr,
                # Judged on lifetime cost, never the monthly payment — a
                # cheaper-looking option is not the cheaper one.
                "is_worthwhile": result.is_worthwhile,
            }
        )


class ScenarioComparisonView(TenantScopedAPIView, APIView):
    """Compare several extra-payment scenarios side by side.

    Real repayment money is lumpy — a bonus, a refund, a raise — so scenarios
    accept a schedule rather than one flat monthly figure.
    """

    permission_classes = [IsTenantMember]
    required_role = Role.VIEWER
    serializer_class = ScenarioComparisonSerializer

    @extend_schema(operation_id="debt_compare_scenarios", request=ScenarioComparisonSerializer)
    def post(self, request):
        s = ScenarioComparisonSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        views = selectors.debt_views()
        inputs = selectors.to_debt_inputs(views)
        if not inputs:
            return Response(status=status.HTTP_204_NO_CONTENT)

        # Doing nothing is the baseline every scenario is measured against.
        baseline = payoff.simulate(inputs, strategy="avalanche")

        out = []
        for scenario in s.validated_data["scenarios"]:
            extra = payoff.ExtraPayments(
                monthly_minor=scenario["monthly_minor"],
                lump_sums=tuple((int(a), int(b)) for a, b in scenario["lump_sums"]),
                step_ups=tuple((int(a), int(b)) for a, b in scenario["step_ups"]),
            )
            plan = payoff.simulate(inputs, strategy=scenario["strategy"], extra=extra)
            out.append(
                {
                    "label": scenario["label"],
                    "strategy": scenario["strategy"],
                    "months_to_debt_free": plan.months_to_debt_free,
                    "debt_free_on": plan.debt_free_on,
                    "total_interest_minor": plan.total_interest_minor,
                    "total_fees_minor": plan.total_fees_minor,
                    "total_paid_minor": plan.total_paid_minor,
                    "interest_saved_minor": max(
                        0, baseline.total_interest_minor - plan.total_interest_minor
                    ),
                    "months_saved": (
                        baseline.months_to_debt_free - plan.months_to_debt_free
                        if baseline.months_to_debt_free is not None
                        and plan.months_to_debt_free is not None
                        else None
                    ),
                    "is_complete": plan.is_complete,
                }
            )

        return Response(
            {
                "baseline": {
                    "months_to_debt_free": baseline.months_to_debt_free,
                    "total_interest_minor": baseline.total_interest_minor,
                    "total_paid_minor": baseline.total_paid_minor,
                },
                "scenarios": out,
            }
        )


class DebtAnalyticsView(TenantScopedAPIView, APIView):
    """Series for the debt dashboards, all from one simulation."""

    permission_classes = [IsTenantMember]
    required_role = Role.VIEWER
    serializer_class = None

    @extend_schema(operation_id="debt_analytics")
    def get(self, request):
        data = selectors.debt_analytics(
            strategy=request.query_params.get("strategy", "avalanche"),
            extra_monthly_minor=int(request.query_params.get("extra_monthly_minor", 0) or 0),
            months=min(int(request.query_params.get("months", 24) or 24), 120),
        )
        if data is None:
            return Response(status=status.HTTP_204_NO_CONTENT)
        return Response(data)


class PayoffExportView(TenantScopedAPIView, APIView):
    """The payoff schedule as a CSV download.

    Exported in major units because a spreadsheet is where this is going, and a
    column of minor-unit integers is a trap for anyone who sums it.
    """

    permission_classes = [IsTenantMember]
    required_role = Role.VIEWER
    serializer_class = None

    @extend_schema(operation_id="debt_payoff_export")
    def get(self, request):
        from django.http import HttpResponse

        csv_text = selectors.payoff_timeline_csv(
            strategy=request.query_params.get("strategy", "avalanche"),
            extra_monthly_minor=int(request.query_params.get("extra_monthly_minor", 0) or 0),
        )
        if not csv_text:
            return Response(status=status.HTTP_204_NO_CONTENT)

        response = HttpResponse(csv_text, content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="payoff-schedule.csv"'
        return response


class PayoffPdfView(TenantScopedAPIView, APIView):
    """The payoff schedule as a printable PDF — a document to file or take to
    a lender, so it leads with the summary that makes the table meaningful."""

    permission_classes = [IsTenantMember]
    required_role = Role.VIEWER
    serializer_class = None

    @extend_schema(operation_id="debt_payoff_pdf")
    def get(self, request):
        from django.http import HttpResponse

        pdf = selectors.payoff_timeline_pdf(
            strategy=request.query_params.get("strategy", "avalanche"),
            extra_monthly_minor=int(request.query_params.get("extra_monthly_minor", 0) or 0),
        )
        if not pdf:
            return Response(status=status.HTTP_204_NO_CONTENT)

        response = HttpResponse(pdf, content_type="application/pdf")
        response["Content-Disposition"] = 'attachment; filename="payoff-schedule.pdf"'
        return response
