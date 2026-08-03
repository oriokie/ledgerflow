import { useState } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "../../../api/client";
import {
  useCategories,
  useCreateCategory,
  useCreatePayee,
  useCreateTag,
  usePayees,
  useTags,
} from "../../../hooks/useFinance";
import { Banner, Button, Chip, Inline, Input, Select } from "../../../ui";
import { SettingsRow, SettingsSection } from "../components";

export function TaxonomyPanel() {
  const { data: categories } = useCategories();
  const { data: payees } = usePayees();
  const { data: tags } = useTags();
  const createCategory = useCreateCategory();
  const createPayee = useCreatePayee();
  const createTag = useCreateTag();

  const [catName, setCatName] = useState("");
  const [catKind, setCatKind] = useState("expense");
  const [payeeName, setPayeeName] = useState("");
  const [tagName, setTagName] = useState("");
  const [error, setError] = useState<string | null>(null);

  const guard = async (fn: () => Promise<unknown>, msg: string) => {
    setError(null);
    try {
      await fn();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : msg);
    }
  };

  const addCategory = () =>
    catName.trim() &&
    guard(async () => {
      await createCategory.mutateAsync({ name: catName, kind: catKind, currency: "USD" });
      setCatName("");
    }, "Couldn't create the category.");
  const addPayee = () =>
    payeeName.trim() &&
    guard(async () => {
      await createPayee.mutateAsync({ name: payeeName });
      setPayeeName("");
    }, "Couldn't create the payee.");
  const addTag = () =>
    tagName.trim() &&
    guard(async () => {
      await createTag.mutateAsync({ name: tagName });
      setTagName("");
    }, "Couldn't create the tag.");

  return (
    <SettingsSection
      title="Categories, payees & tags"
      description="The vocabulary your transactions are organized with."
      action={
        <Link className="lf-btn lf-btn--ghost lf-btn--sm" to="/categories">
          Open full manager
        </Link>
      }
    >
      <SettingsRow title="Add a category" description="Group spending or income." htmlFor="tx-cat">
        <Inline gap={2} align="start">
          <Input id="tx-cat" placeholder="New category" value={catName} onChange={(e) => setCatName(e.target.value)} />
          <Select
            value={catKind}
            onChange={(e) => setCatKind(e.target.value)}
            aria-label="Category kind"
            options={[
              { value: "expense", label: "Expense" },
              { value: "income", label: "Income" },
            ]}
          />
          <Button variant="secondary" onClick={addCategory}>
            Add
          </Button>
        </Inline>
      </SettingsRow>
      {categories && categories.length > 0 && (
        <Inline gap={2}>
          {categories.map((c) => (
            <Chip key={c.id} active={c.kind === "income"}>
              {c.name}
            </Chip>
          ))}
        </Inline>
      )}

      <SettingsRow title="Add a payee" description="Who money goes to or comes from." htmlFor="tx-payee">
        <Inline gap={2} align="start">
          <Input id="tx-payee" placeholder="New payee" value={payeeName} onChange={(e) => setPayeeName(e.target.value)} />
          <Button variant="secondary" onClick={addPayee}>
            Add
          </Button>
        </Inline>
      </SettingsRow>
      {payees && payees.length > 0 && (
        <Inline gap={2}>
          {payees.map((p) => (
            <Chip key={p.id}>{p.name}</Chip>
          ))}
        </Inline>
      )}

      <SettingsRow title="Add a tag" description="Cross-cutting labels for transactions." htmlFor="tx-tag">
        <Inline gap={2} align="start">
          <Input id="tx-tag" placeholder="New tag" value={tagName} onChange={(e) => setTagName(e.target.value)} />
          <Button variant="secondary" onClick={addTag}>
            Add
          </Button>
        </Inline>
      </SettingsRow>
      {tags && tags.length > 0 && (
        <Inline gap={2}>
          {tags.map((t) => (
            <Chip key={t.id}>{t.name}</Chip>
          ))}
        </Inline>
      )}

      {error && <Banner tone="danger">{error}</Banner>}
    </SettingsSection>
  );
}
