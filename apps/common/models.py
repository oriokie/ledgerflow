"""Reusable base models + tenant-scoped, soft-delete-aware managers.

Base hierarchy (compose, don't repeat):
  UUIDModel              -> uuid7 PK
  TimeStampedModel       -> created_at / updated_at
  TenantOwnedModel       -> + tenant_id, created_by, updated_by, tenant-scoped
                            managers. Base for IMMUTABLE financial records.
  SoftDeletableModel     -> + deleted_at, deleted_by, soft-delete managers.
                            Base for MUTABLE domain / reference data.

Immutable financial records (ledger) intentionally do NOT inherit soft delete —
they are corrected by reversing entries and protected by a DB trigger.
"""

from __future__ import annotations

from django.db import models
from django.utils import timezone

from .ids import uuid7
from .tenant_context import (
    get_current_actor_id,
    get_current_tenant_id,
    require_current_tenant_id,
)


class UUIDModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)

    class Meta:
        abstract = True


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


# ---- querysets & managers -------------------------------------------------
class TenantScopedQuerySet(models.QuerySet):
    def for_tenant(self, tenant_id):
        return self.filter(tenant_id=tenant_id)


class TenantScopedManager(models.Manager):
    """Auto-scopes to the ambient tenant; hard-fails if unscoped."""

    def get_queryset(self):
        return TenantScopedQuerySet(self.model, using=self._db).filter(tenant_id=require_current_tenant_id())


class UnscopedManager(models.Manager):
    """Explicit, greppable escape hatch for system / admin / migration code."""

    def get_queryset(self):
        return TenantScopedQuerySet(self.model, using=self._db)


class SoftDeleteQuerySet(TenantScopedQuerySet):
    def alive(self):
        return self.filter(deleted_at__isnull=True)

    def dead(self):
        return self.filter(deleted_at__isnull=False)

    def delete(self):  # bulk soft delete
        return self.update(deleted_at=timezone.now(), deleted_by_id=get_current_actor_id())

    def hard_delete(self):
        return super().delete()


class SoftDeleteManager(TenantScopedManager):
    """Tenant-scoped AND hides soft-deleted rows by default."""

    def get_queryset(self):
        return SoftDeleteQuerySet(self.model, using=self._db).filter(
            tenant_id=require_current_tenant_id(), deleted_at__isnull=True
        )


class SoftDeleteAllManager(TenantScopedManager):
    """Tenant-scoped, includes soft-deleted rows (for admin / restore flows)."""

    def get_queryset(self):
        return SoftDeleteQuerySet(self.model, using=self._db).filter(tenant_id=require_current_tenant_id())


# ---- base models ----------------------------------------------------------
class TenantOwnedModel(UUIDModel, TimeStampedModel):
    """Base for tenant data. Audit stamps are UUIDs (not FKs) to avoid a hard
    cross-app import cycle with the user model; the FK + RLS live in migrations."""

    tenant_id = models.UUIDField(db_index=True, editable=False)
    created_by_id = models.UUIDField(null=True, blank=True, editable=False)
    updated_by_id = models.UUIDField(null=True, blank=True, editable=False)

    objects = TenantScopedManager()
    unscoped = UnscopedManager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        actor = get_current_actor_id()
        if not self.tenant_id:
            self.tenant_id = require_current_tenant_id()
        elif (current := get_current_tenant_id()) is not None and self.tenant_id != current:
            raise ValueError("Refusing to save a row under a different tenant than the active context.")
        if self._state.adding and actor and not self.created_by_id:
            self.created_by_id = actor
        if actor:
            self.updated_by_id = actor
        super().save(*args, **kwargs)


class SoftDeletableModel(TenantOwnedModel):
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)
    deleted_by_id = models.UUIDField(null=True, blank=True, editable=False)

    objects = SoftDeleteManager()  # alive only
    all_objects = SoftDeleteAllManager()  # incl. deleted
    unscoped = UnscopedManager()

    class Meta:
        abstract = True

    def delete(self, using=None, keep_parents=False):
        self.deleted_at = timezone.now()
        self.deleted_by_id = get_current_actor_id()
        self.save(update_fields=["deleted_at", "deleted_by_id", "updated_at"])

    def hard_delete(self, using=None, keep_parents=False):
        super().delete(using=using, keep_parents=keep_parents)

    def restore(self):
        self.deleted_at = None
        self.deleted_by_id = None
        self.save(update_fields=["deleted_at", "deleted_by_id", "updated_at"])

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None


# Register concrete models defined in sibling modules for migrations.
from .audit import AuditLog  # noqa: E402,F401
from .outbox import OutboxEvent  # noqa: E402,F401
