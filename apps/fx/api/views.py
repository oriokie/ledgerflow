"""FX endpoints: currency catalog, current rates, and ad-hoc conversion.
Currencies/rates are global reference data — auth required, no tenant scope."""

from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .. import services
from ..currencies import CURRENCIES, is_supported


class CurrencyListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(
            [{"code": c.code, "name": c.name, "symbol": c.symbol, "digits": c.digits} for c in CURRENCIES]
        )


class RatesView(APIView):
    """Latest rate from `base` to every supported currency (best-effort)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        base = (request.query_params.get("base") or "USD").upper()
        rates: dict[str, float] = {}
        for c in CURRENCIES:
            if c.code == base:
                rates[c.code] = 1.0
                continue
            r = services.latest_rate(base, c.code)
            if r is not None:
                rates[c.code] = float(r)
        return Response({"base": base, "rates": rates})


class ConvertView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            amount = int(request.query_params.get("amount_minor", "0"))
        except ValueError:
            amount = 0
        frm = (request.query_params.get("from") or "").upper()
        to = (request.query_params.get("to") or "").upper()
        if not is_supported(frm) or not is_supported(to):
            return Response({"detail": "Unsupported currency."}, status=400)
        converted = services.convert(amount_minor=amount, from_currency=frm, to_currency=to)
        return Response({"amount_minor": amount, "from": frm, "to": to, "converted_minor": converted})
