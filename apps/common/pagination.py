"""Cursor pagination by default.

Offset pagination (`LIMIT/OFFSET`) degrades badly on large, high-churn tables
(the ledger, transactions) — the DB still has to walk past every skipped row.
Cursor pagination is O(1) per page regardless of how deep the client pages.
"""

from __future__ import annotations

from rest_framework.pagination import CursorPagination as DRFCursorPagination


class CursorPagination(DRFCursorPagination):
    page_size = 25
    max_page_size = 100
    page_size_query_param = "page_size"
    ordering = "-created_at"  # every base model has this; views may override
