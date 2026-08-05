from __future__ import annotations

from django.urls import path

from .views import (
    DividendSummaryView,
    DividendView,
    HoldingsView,
    InterestView,
    InvestmentTransactionsView,
    PortfolioHistoryView,
    PortfolioView,
    PriceView,
    SecurityDetailView,
    SecurityView,
    SplitView,
    TradeView,
)

urlpatterns = [
    path("securities/", SecurityView.as_view(), name="inv-securities"),
    path(
        "securities/<uuid:security_id>/",
        SecurityDetailView.as_view(),
        name="inv-security-detail",
    ),
    path("holdings/", HoldingsView.as_view(), name="inv-holdings"),
    path("portfolio/", PortfolioView.as_view(), name="inv-portfolio"),
    path("portfolio/history/", PortfolioHistoryView.as_view(), name="inv-portfolio-history"),
    path("transactions/", InvestmentTransactionsView.as_view(), name="inv-transactions"),
    path("dividends/", DividendSummaryView.as_view(), name="inv-dividends"),
    path("dividends/record/", DividendView.as_view(), name="inv-dividend-record"),
    path("interest/record/", InterestView.as_view(), name="inv-interest-record"),
    path("prices/", PriceView.as_view(), name="inv-prices"),
    path("splits/", SplitView.as_view(), name="inv-splits"),
    path("trade/<str:action>/", TradeView.as_view(), name="inv-trade"),
]
