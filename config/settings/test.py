"""Test settings: fast, hermetic, deterministic. No network, no real broker."""

from .base import *  # noqa: F401,F403

DEBUG = False
SECRET_KEY = "test-secret-key-not-for-production"
FIELD_ENCRYPTION_KEY = "owJqH2QBsteNlIv9CmOI-9HYDS_k5Hz3MVn64Nslonw="  # noqa: S105 — test-only, not a secret

# Fast (insecure) password hashing — correctness of hashing algo is not under test.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Celery tasks execute synchronously and eagerly; no broker needed.
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

CACHES["default"]["BACKEND"] = "django.core.cache.backends.locmem.LocMemCache"  # noqa: F405

REST_FRAMEWORK["DEFAULT_THROTTLE_CLASSES"] = []  # noqa: F405

DEFAULT_FILE_STORAGE = "django.core.files.storage.InMemoryStorage"
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# Persistent connections cause connection-state bleed between tests
# (esp. transactional tests interacting with CONN_MAX_AGE). Disable in tests.
DATABASES["default"]["CONN_MAX_AGE"] = 0  # noqa: F405
