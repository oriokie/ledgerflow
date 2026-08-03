from django.urls import path

from .views import AccountViewSet, JournalEntryViewSet

urlpatterns = [
    path("accounts/", AccountViewSet.as_view({"get": "list", "post": "create"})),
    path("entries/", JournalEntryViewSet.as_view({"get": "list", "post": "create"})),
]
