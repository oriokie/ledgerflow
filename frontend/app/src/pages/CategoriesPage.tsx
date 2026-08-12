import { FolderTree, Pencil, Trash2 } from "lucide-react";
import { useState } from "react";
import { ApiError } from "../api/client";
import type { Category } from "../api/types";
import { useAuth } from "../lib/AuthContext";
import {
  useCategories,
  useCreateCategory,
  useDeleteCategory,
  useUpdateCategory,
} from "../hooks/useFinance";
import { Banner, Button, Card, ConfirmAction, EmptyState, IconButton, Input, Modal, PageHeader, SegmentedControl, Select, Skeleton, Stack, Table, Text } from "../ui";
import type { Column } from "../ui";

/** Options for a parent picker: same-kind categories only, indented to show
 * depth. `excludeId` drops a category (and, transitively, its descendants) so
 * a category can never be offered as its own ancestor. */
function parentOptions(all: Category[], kind: Category["kind"], excludeId?: string) {
  const byId = new Map(all.map((c) => [c.id, c]));
  const isSelfOrDescendant = (c: Category): boolean => {
    if (!excludeId) return false;
    let cur: Category | undefined = c;
    while (cur) {
      if (cur.id === excludeId) return true;
      cur = cur.parent_id ? byId.get(cur.parent_id) : undefined;
    }
    return false;
  };
  return all
    .filter((c) => c.kind === kind && !isSelfOrDescendant(c))
    .slice()
    .sort((a, b) => a.path.localeCompare(b.path))
    .map((c) => ({
      value: c.id,
      label: `${"    ".repeat(c.depth)}${c.name}`,
    }));
}

export function CategoriesPage() {
  const { activeWorkspace } = useAuth();
  const { data: categories, isLoading } = useCategories();
  const createCategory = useCreateCategory();
  const updateCategory = useUpdateCategory();
  const deleteCategory = useDeleteCategory();

  const [showCreate, setShowCreate] = useState(false);
  const [editing, setEditing] = useState<Category | null>(null);
  const [name, setName] = useState("");
  const [kind, setKind] = useState<"expense" | "income">("expense");
  const [parentId, setParentId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [banner, setBanner] = useState<string | null>(null);

  const allCategories = categories ?? [];
  const expense = allCategories.filter((c) => c.kind === "expense");
  const income = allCategories.filter((c) => c.kind === "income");
  const parentName = (id: string | null) => (id ? allCategories.find((c) => c.id === id)?.name : undefined);

  const openCreate = () => {
    setName("");
    setKind("expense");
    setParentId("");
    setError(null);
    setShowCreate(true);
  };

  const submitCreate = async () => {
    setError(null);
    if (!name.trim()) return setError("Name the category.");
    try {
      // Built as a variable (not an inline literal) so the optional
      // `parent_id` — absent from the client's declared payload shape — still
      // reaches the request body instead of being typo'd away as `parent`.
      const payload = {
        name,
        kind,
        currency: activeWorkspace?.tenant.base_currency ?? "KES",
        ...(parentId ? { parent_id: parentId } : {}),
      };
      await createCategory.mutateAsync(payload);
      setShowCreate(false);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Couldn't create the category.");
    }
  };

  const submitEdit = async () => {
    if (!editing) return;
    setError(null);
    if (!name.trim()) return setError("Name can't be empty.");
    try {
      await updateCategory.mutateAsync({
        categoryId: editing.id,
        payload: { name, parent_id: parentId || null },
      });
      setEditing(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Couldn't save changes.");
    }
  };

  const remove = async (category: Category) => {
    setBanner(null);
    try {
      await deleteCategory.mutateAsync(category.id);
    } catch (err) {
      // The most common failure is "in use" — surface it as a helpful banner
      // rather than a silent no-op.
      setBanner(err instanceof ApiError ? err.detail : "Couldn't delete that category.");
    }
  };

  const columns: Column<Category>[] = [
    {
      key: "kind",
      header: "Kind",
      hideMobile: true,
      render: (c) => <span className="lf-cell-meta">{c.kind}</span>,
    },
    {
      key: "name",
      header: "Name",
      // Hierarchy used to live only in a `hideMobile` "Path" column, so a
      // subcategory was indistinguishable from a same-named top-level one on
      // any narrow screen. Folding the parent's name into this
      // always-visible cell keeps that cue everywhere instead of dropping it
      // below 768px.
      render: (c) => (
        <div>
          <span className="lf-cell-primary">{c.name}</span>
          {c.parent_id && <div className="lf-cell-meta">{parentName(c.parent_id) ?? c.path}</div>}
        </div>
      ),
    },
    {
      key: "actions",
      header: "",
      align: "right",
      render: (c) => (
        <div className="lf-row-actions">
          <IconButton
            label={`Edit ${c.name}`}
            icon={<Pencil size={15} />}
            onClick={() => {
              setEditing(c);
              setName(c.name);
              setParentId(c.parent_id ?? "");
              setError(null);
            }}
          />
          <ConfirmAction
            label={`Delete ${c.name}`}
            icon={<Trash2 size={15} />}
            confirmLabel="Delete"
            cancelLabel="Keep"
            disabled={deleteCategory.isPending}
            onConfirm={() => remove(c)}
          />
        </div>
      ),
    },
  ];

  const sorted = [...expense, ...income];

  return (
    <>
      <PageHeader
        eyebrow="Workspace"
        title="Categories"
        description="How spending and income are labeled across the ledger."
        illustration="adjust"
        actions={
          <Button variant="primary" onClick={openCreate}>
            New category
          </Button>
        }
      />

      {banner && (
        <Banner tone="danger" onDismiss={() => setBanner(null)}>
          {banner}
        </Banner>
      )}

      {isLoading && <Skeleton width="50%" />}

      {categories && categories.length === 0 && (
        <Card>
          <EmptyState
            icon={FolderTree}
            title="No categories yet"
            body="Categories group your transactions — Groceries, Rent, Salary. Create a few to make budgets and insights meaningful."
            action={
              <Button variant="primary" onClick={openCreate}>
                Create a category
              </Button>
            }
          />
        </Card>
      )}

      {categories && categories.length > 0 && (
        <Table
          columns={columns}
          rows={sorted}
          rowKey={(c) => c.id}
          responsive={false}
          caption="Categories"
          stickyHeader
          compact
        />
      )}

      <Modal
        open={showCreate}
        onClose={() => setShowCreate(false)}
        title="New category"
        footer={
          <Button variant="primary" onClick={submitCreate} loading={createCategory.isPending}>
            Create category
          </Button>
        }
      >
        <Stack gap={4}>
          <Input
            label="Name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            autoFocus
            placeholder="e.g. Groceries"
          />
          <SegmentedControl
            legend="Kind"
            value={kind}
            onChange={(k) => {
              setKind(k);
              // A parent picked under the old kind may not even be an option
              // under the new one — drop it rather than carry over a
              // selection the list below no longer shows.
              setParentId("");
            }}
            options={[
              { value: "expense", label: "Expense" },
              { value: "income", label: "Income" },
            ]}
          />
          <Select
            label="Parent category"
            optional
            value={parentId}
            onChange={(e) => setParentId(e.target.value)}
            placeholder="No parent (top-level)"
            options={parentOptions(allCategories, kind)}
            hint="Nest under an existing category to build a subcategory."
          />
          {error && <Banner tone="danger">{error}</Banner>}
        </Stack>
      </Modal>

      <Modal
        open={!!editing}
        onClose={() => setEditing(null)}
        title="Edit category"
        footer={
          <Button variant="primary" onClick={submitEdit} loading={updateCategory.isPending}>
            Save changes
          </Button>
        }
      >
        <Stack gap={4}>
          <Text tone="tertiary" size="sm">
            A category's type can't change once created (it would invalidate past postings). Rename freely.
          </Text>
          {editing?.parent_id && (
            <Text tone="tertiary" size="sm">
              Nested under <strong>{parentName(editing.parent_id) ?? "another category"}</strong>. Moving a
              category to a different parent isn't supported yet — delete and recreate it to relocate it.
            </Text>
          )}
          <Input label="Name" value={name} onChange={(e) => setName(e.target.value)} autoFocus />
          {editing && (
            <Select
              label="Parent category"
              optional
              value={parentId}
              onChange={(e) => setParentId(e.target.value)}
              placeholder="No parent (top-level)"
              options={parentOptions(allCategories, editing.kind, editing.id)}
              hint="Move this category under a different parent, or clear it to make it top-level."
            />
          )}
          {error && <Banner tone="danger">{error}</Banner>}
        </Stack>
      </Modal>
    </>
  );
}
