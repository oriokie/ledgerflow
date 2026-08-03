import { FolderTree, Pencil, Trash2 } from "lucide-react";
import { useState } from "react";
import { ApiError } from "../api/client";
import type { Category } from "../api/types";
import {
  useCategories,
  useCreateCategory,
  useDeleteCategory,
  useUpdateCategory,
} from "../hooks/useFinance";
import { Banner, Button, Card, ConfirmAction, EmptyState, Heading, IconButton, Input, Modal, PageHeader, SegmentedControl, Skeleton, Stack, Table, Text } from "../ui";
import type { Column } from "../ui";

export function CategoriesPage() {
  const { data: categories, isLoading } = useCategories();
  const createCategory = useCreateCategory();
  const updateCategory = useUpdateCategory();
  const deleteCategory = useDeleteCategory();

  const [showCreate, setShowCreate] = useState(false);
  const [editing, setEditing] = useState<Category | null>(null);
  const [name, setName] = useState("");
  const [kind, setKind] = useState<"expense" | "income">("expense");
  const [error, setError] = useState<string | null>(null);
  const [banner, setBanner] = useState<string | null>(null);

  const expense = categories?.filter((c) => c.kind === "expense") ?? [];
  const income = categories?.filter((c) => c.kind === "income") ?? [];

  const openCreate = () => {
    setName("");
    setKind("expense");
    setError(null);
    setShowCreate(true);
  };

  const submitCreate = async () => {
    setError(null);
    if (!name.trim()) return setError("Name the category.");
    try {
      await createCategory.mutateAsync({ name, kind, currency: "USD" });
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
      await updateCategory.mutateAsync({ categoryId: editing.id, payload: { name } });
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
      key: "name",
      header: "Name",
      render: (c) => <span className="lf-cell-primary">{c.name}</span>,
    },
    {
      key: "path",
      header: "Path",
      hideMobile: true,
      render: (c) => <span className="lf-cell-meta">{c.path}</span>,
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

  const renderGroup = (title: string, list: Category[]) => (
    <section style={{ marginBottom: "var(--lf-space-8)" }}>
      <Heading level={2}>{title}</Heading>
      {list.length === 0 ? (
        <Text tone="tertiary" size="sm" style={{ marginTop: "var(--lf-space-2)" }}>
          No {title.toLowerCase()} yet.
        </Text>
      ) : (
        <Table columns={columns} rows={list} rowKey={(c) => c.id} responsive={false} caption={title} />
      )}
    </section>
  );

  return (
    <>
      <PageHeader
        eyebrow="Organize your spending & income"
        title="Categories"
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
        <>
          {renderGroup("Expense categories", expense)}
          {renderGroup("Income categories", income)}
        </>
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
            onChange={setKind}
            options={[
              { value: "expense", label: "Expense" },
              { value: "income", label: "Income" },
            ]}
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
        <Stack gap={3}>
          <Text tone="tertiary" size="sm">
            A category's type can't change once created (it would invalidate past postings). Rename freely.
          </Text>
          <Input label="Name" value={name} onChange={(e) => setName(e.target.value)} autoFocus />
          {error && <Banner tone="danger">{error}</Banner>}
        </Stack>
      </Modal>
    </>
  );
}
