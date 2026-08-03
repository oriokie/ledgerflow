"""Create the first Platform Owner.

The one privilege grant that cannot come from the API, because the API
requires an existing staff member to authorise it — the bootstrap problem. It
is therefore restricted to the server console, where access is already
governed by infrastructure controls rather than application ones.

Usage:
    python manage.py bootstrap_platform_owner --email ops@example.com
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.platform_admin.models import PlatformStaff
from apps.platform_admin.rbac import PlatformRole
from apps.platform_admin.services import staff as staff_service
from apps.users.models import User


class Command(BaseCommand):
    help = "Grant a user the Platform Owner role (bootstrap; console only)."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True)
        parser.add_argument(
            "--allow-additional",
            action="store_true",
            help="Appoint another owner even though one already exists.",
        )
        parser.add_argument(
            "--no-mfa",
            action="store_true",
            help="Skip the MFA requirement. Development only — never in production.",
        )

    def handle(self, *args, **options):
        email = options["email"].strip().lower()
        user = User.objects.filter(email__iexact=email).first()
        if user is None:
            raise CommandError(f"No user with email {email}. Have them register first.")

        existing = PlatformStaff.objects.filter(role=PlatformRole.OWNER, is_active=True)
        if existing.exists() and not options["allow_additional"]:
            # Appointing a second owner should normally happen through the
            # audited API, where it is attributable to a person.
            raise CommandError(
                "A platform owner already exists. Appoint further staff through the "
                "console UI so the grant is audited, or pass --allow-additional."
            )

        try:
            member = staff_service.appoint(
                user=user,
                role=PlatformRole.OWNER,
                actor=None,  # bootstrap: no existing staff member to authorise it
                require_mfa=not options["no_mfa"],
                note="Bootstrapped from the server console.",
            )
        except staff_service.StaffError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.SUCCESS(f"{email} is now a Platform Owner."))
        if member.require_mfa:
            self.stdout.write(
                "They must enable two-factor authentication before the platform "
                "workspace will let them in."
            )
