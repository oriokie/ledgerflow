"""Tag service layer. `set_transaction_tags` is set-based (diff against
current tags), not append-only — calling it twice with the same tag list is
a no-op, and it's the one place TransactionTag rows are ever written, so the
soft-delete history stays a true audit trail of what was added/removed and
when."""

from __future__ import annotations

from django.db import transaction

from apps.common import audit

from .models import Tag, Transaction, TransactionTag


class TagError(Exception): ...


@transaction.atomic
def create_tag(*, name: str, color: str = "") -> Tag:
    name = name.strip()
    if not name:
        raise TagError("Tag name cannot be blank.")
    if Tag.objects.filter(name=name).exists():
        raise TagError(f"A tag named {name!r} already exists.")
    return Tag.objects.create(name=name, color=color)


@transaction.atomic
def set_transaction_tags(*, txn: Transaction, tags: list[Tag]) -> list[Tag]:
    desired_ids = {t.id for t in tags}
    current_links = {link.tag_id: link for link in TransactionTag.objects.filter(transaction=txn)}

    for tag_id, link in current_links.items():
        if tag_id not in desired_ids:
            link.delete()  # soft delete

    existing_ids = set(current_links.keys())
    TransactionTag.objects.bulk_create(
        [
            TransactionTag(transaction=txn, tenant_id=txn.tenant_id, tag_id=tag_id)
            for tag_id in desired_ids - existing_ids
        ]
    )
    return list(tags)


@transaction.atomic
def update_tag(*, tag: Tag, name: str | None = None, color: str | None = None) -> Tag:
    """Rename or recolour a tag.

    Tags were create-only, so a typo was permanent and the list only ever grew.
    The name collision check mirrors `create_tag` — renaming onto an existing
    tag should fail the same way creating a duplicate does, rather than
    surfacing a raw IntegrityError.
    """
    if name is not None:
        cleaned = name.strip()
        if not cleaned:
            raise TagError("A tag needs a name.")
        if Tag.objects.filter(name__iexact=cleaned).exclude(pk=tag.pk).exists():
            raise TagError(f"A tag called '{cleaned}' already exists.")
        tag.name = cleaned
    if color is not None:
        tag.color = color
    tag.save()
    audit.record(action="tag.updated", target=tag, changes={"name": [None, tag.name]})
    return tag


@transaction.atomic
def delete_tag(*, tag: Tag) -> None:
    """Soft-delete a tag and detach it from transactions.

    Detaching rather than refusing: a tag is a label, not a financial record, so
    removing one should not be blocked by the transactions carrying it — the
    transactions are unchanged, they simply lose a label the user no longer
    wants. The unique constraint is scoped to live rows, so the same name can be
    used again immediately.
    """
    TransactionTag.objects.filter(tag=tag).delete()
    audit.record(action="tag.deleted", target=tag, changes={"name": [tag.name, None]})
    tag.delete()
