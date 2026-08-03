"""Local development. Convenience over strictness; never used in production."""

from .base import *  # noqa: F401,F403

DEBUG = True
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS += ["django_extensions"]  # noqa: F405 — shell_plus, etc.

# Emails print to console instead of sending.
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Loosen throttles so manual API exploration isn't rate-limited.
#
# Merged into the base rates rather than replacing them. Replacing dropped
# `mfa_verify` entirely, and a scope with no configured rate is not "unlimited"
# in a visible way — DRF finds no rate and silently stops throttling that view.
# The MFA endpoints were therefore unprotected here with nothing to indicate it.
REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"] = {  # noqa: F405
    **REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"],  # noqa: F405
    "auth": "1000/min",
    "mfa_verify": "1000/min",
    "write": "1000/min",
    "read": "10000/min",
}

CORS_ALLOW_ALL_ORIGINS = True
