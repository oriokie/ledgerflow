import { Bell, CreditCard, Plus, Trash2, Wallet } from "lucide-react";
import { useState } from "react";
import {
  Badge,
  Banner,
  Button,
  Card,
  Checkbox,
  Chip,
  Divider,
  EmptyState,
  Eyebrow,
  Figure,
  FigureRow,
  FormField,
  Grid,
  Heading,
  IconButton,
  Inline,
  Input,
  LoadingBlock,
  Meter,
  PasswordInput,
  Modal,
  Money,
  SegmentedControl,
  Select,
  Skeleton,
  SkeletonCard,
  Spinner,
  Stack,
  Switch,
  Table,
  Tabs,
  Text,
  Textarea,
} from "../ui";
import type { Column } from "../ui";
import { Illustration, ILLUSTRATION_NAMES, ILLUSTRATION_STYLES } from "../ui/illustration";

/**
 * Living documentation for the UI component library. Not a feature page — a
 * visual reference that renders every component in its states, so we can QA
 * design consistency and onboard contributors. Reachable at /_ui in dev.
 */

interface DemoRow {
  id: string;
  name: string;
  kind: string;
  amount: number;
}

const DEMO_ROWS: DemoRow[] = [
  { id: "1", name: "Groceries", kind: "expense", amount: -8450 },
  { id: "2", name: "Salary", kind: "income", amount: 650000 },
  { id: "3", name: "Transfer to Savings", kind: "transfer", amount: -20000 },
];

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section style={{ marginBottom: "var(--lf-space-12)" }}>
      <Heading level={2}>{title}</Heading>
      <Divider />
      {children}
    </section>
  );
}

export function ComponentShowcase() {
  const [seg, setSeg] = useState<"expense" | "income" | "transfer">("expense");
  const [tab, setTab] = useState<"overview" | "activity" | "settings">("overview");
  const [modalOpen, setModalOpen] = useState(false);
  const [switchOn, setSwitchOn] = useState(true);
  const [checked, setChecked] = useState(false);
  const [sort, setSort] = useState<{ key: string; direction: "asc" | "desc" }>({
    key: "name",
    direction: "asc",
  });

  const columns: Column<DemoRow>[] = [
    { key: "name", header: "Name", render: (r) => r.name, sortable: true },
    { key: "kind", header: "Kind", render: (r) => <Badge tone="neutral">{r.kind}</Badge>, hideMobile: true },
    {
      key: "amount",
      header: "Amount",
      align: "right",
      sortable: true,
      render: (r) => <Money amountMinor={r.amount} currency="USD" isTransfer={r.kind === "transfer"} />,
    },
  ];

  const sortedRows = [...DEMO_ROWS].sort((a, b) => {
    const dir = sort.direction === "asc" ? 1 : -1;
    if (sort.key === "amount") return (a.amount - b.amount) * dir;
    return a.name.localeCompare(b.name) * dir;
  });

  return (
    <div style={{ maxWidth: "var(--lf-content-max)", margin: "0 auto", padding: "var(--lf-space-8)" }}>
      <Eyebrow>Design system</Eyebrow>
      <Heading level={1}>UI component library</Heading>
      <Text tone="secondary" style={{ marginTop: "var(--lf-space-2)", marginBottom: "var(--lf-space-8)" }}>
        Every reusable component, in its states. Living documentation for the LedgerFlow design system.
      </Text>

      <Section title="Illustrations">
        {/* The whole set on one page, which is the only way to judge whether a
            new motif actually matches the others' lighting and weight. */}
        {ILLUSTRATION_STYLES.map((style) => (
          <div key={style} style={{ marginBottom: "var(--lf-space-6)" }}>
            <Text size="sm" tone="secondary">
              {style}
            </Text>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))",
                gap: "var(--lf-space-4)",
              }}
            >
              {ILLUSTRATION_NAMES.map((name) => (
                <div key={name} style={{ textAlign: "center" }}>
                  <Illustration name={name} size="panel" style={style} />
                  <Text size="xs" tone="tertiary">
                    {name}
                  </Text>
                </div>
              ))}
            </div>
          </div>
        ))}
      </Section>

      <Section title="Typography">
        <Stack gap={2}>
          <Heading level={1}>Heading level 1 — page title</Heading>
          <Heading level={2}>Heading level 2 — section</Heading>
          <Heading level={3}>Heading level 3 — card</Heading>
          <Eyebrow>Eyebrow / kicker</Eyebrow>
          <Text>Body text — the default paragraph tone and size.</Text>
          <Text tone="secondary">Secondary text for supporting detail.</Text>
          <Text tone="tertiary" size="sm">Tertiary, small — meta and captions.</Text>
        </Stack>
      </Section>

      <Section title="Buttons">
        <Stack gap={4}>
          <Inline gap={2}>
            <Button variant="primary">Primary</Button>
            <Button variant="secondary">Secondary</Button>
            <Button variant="ghost">Ghost</Button>
            <Button variant="danger">Danger</Button>
          </Inline>
          <Inline gap={2}>
            <Button size="sm">Small</Button>
            <Button size="md">Medium</Button>
            <Button size="lg">Large</Button>
          </Inline>
          <Inline gap={2}>
            <Button icon={<Plus size={15} />}>With icon</Button>
            <Button loading>Loading</Button>
            <Button disabled>Disabled</Button>
            <IconButton label="Notifications" icon={<Bell size={17} />} />
            <IconButton label="Delete" icon={<Trash2 size={17} />} variant="danger" />
          </Inline>
          <Button block variant="primary">Block button</Button>
        </Stack>
      </Section>

      <Section title="Form controls">
        <Grid cols={2} gap={4}>
          <Input label="Text input" placeholder="e.g. Groceries" hint="A short helper line." />
          <Input label="With error" defaultValue="oops" error="This field has a problem." />
          <PasswordInput label="Password" defaultValue="hunter2hunter2" hint="Toggle visibility with the eye." />
          <Input label="Amount" amount placeholder="0.00" />
          <Select label="Select" placeholder="Choose…" options={[{ value: "a", label: "Option A" }, { value: "b", label: "Option B" }]} />
          <Textarea label="Textarea" placeholder="Longer text…" />
          <FormField label="Toggles">
            <Inline gap={4}>
              <Switch label="Switch" checked={switchOn} onChange={(e) => setSwitchOn(e.target.checked)} />
              <Checkbox label="Checkbox" checked={checked} onChange={(e) => setChecked(e.target.checked)} />
            </Inline>
          </FormField>
          <FormField label="Segmented control">
            <SegmentedControl
              legend="Type"
              value={seg}
              onChange={setSeg}
              options={[
                { value: "expense", label: "Expense" },
                { value: "income", label: "Income" },
                { value: "transfer", label: "Transfer" },
              ]}
            />
          </FormField>
        </Grid>
      </Section>

      <Section title="Cards">
        <Grid cols={3} gap={4}>
          <Card eyebrow="Checking" title="Everyday" action={<Badge>USD</Badge>}>
            <Money amountMinor={128400} currency="USD" neutral hero />
          </Card>
          <Card title="Plain card">
            <Text tone="secondary">A card with just a title and content.</Text>
          </Card>
          <Card highlight eyebrow="Current" title="Highlighted">
            <Text tone="secondary">Emphasized with a colored border.</Text>
          </Card>
        </Grid>
      </Section>

      <Section title="Badges & chips">
        <Stack gap={3}>
          <Inline gap={2}>
            <Badge tone="success">Active</Badge>
            <Badge tone="warning">Pending</Badge>
            <Badge tone="danger">Failed</Badge>
            <Badge tone="neutral">Draft</Badge>
          </Inline>
          <Inline gap={2}>
            <Chip>vacation</Chip>
            <Chip active>selected</Chip>
            <Chip onClick={() => {}}>clickable</Chip>
          </Inline>
        </Stack>
      </Section>

      <Section title="Money">
        <Inline gap={6}>
          <Money amountMinor={650000} currency="USD" />
          <Money amountMinor={-8450} currency="USD" />
          <Money amountMinor={-20000} currency="USD" isTransfer />
          <Money amountMinor={128400} currency="USD" neutral hero />
        </Inline>
      </Section>

      <Section title="Figure — sizes">
        <FigureRow lead>
          <Figure label="Net worth" size="hero" amountMinor={3914931} currency="KES" delta="▲ 154%" />
          <Figure label="Assets" size="secondary" amountMinor={4228381} currency="KES" />
          <Figure label="Liabilities" size="secondary" amountMinor={313450} currency="KES" />
          <Figure label="Achieved" size="secondary" value="0 of 2" />
        </FigureRow>
      </Section>

      <Section title="Figure — certainty">
        <FigureRow>
          <Figure label="Settled" amountMinor={4228381} currency="KES" hint="posted and reconciled" />
          <Figure label="Pending" amountMinor={120400} currency="KES" certainty="pending" hint="authorised, not cleared" />
          <Figure label="Projected" amountMinor={540000} currency="KES" certainty="projected" hint="from a known recurrence" />
          <Figure
            label="Debt health"
            value="100"
            certainty="speculative"
            confidence="Based on 45% of the usual inputs. Add interest rates for a real score."
          />
        </FigureRow>
      </Section>

      <Section title="Figure — tone (rationed: meaning only)">
        <FigureRow>
          <Figure label="Income" amountMinor={540000} currency="KES" tone="positive" />
          <Figure label="Days below zero" value="3" tone="critical" />
          <Figure label="Unreconciled" value="12" tone="warning" />
          <Figure label="Accounts" value="4" />
        </FigureRow>
      </Section>

      <Section title="Meter / progress">
        <Stack gap={4}>
          <Meter value={45} label="Groceries" caption="45%" />
          <Meter value={82} label="Dining" caption="82%" />
          <Meter value={112} over label="Transport" caption="Over budget" />
        </Stack>
      </Section>

      <Section title="Tabs">
        <Tabs
          label="Demo tabs"
          value={tab}
          onChange={setTab}
          tabs={[
            { value: "overview", label: "Overview" },
            { value: "activity", label: "Activity" },
            { value: "settings", label: "Settings" },
          ]}
        />
        <Text tone="secondary">Selected tab: {tab}</Text>
      </Section>

      <Section title="Table">
        <Table
          columns={columns}
          rows={sortedRows}
          rowKey={(r) => r.id}
          sort={sort}
          onSort={(key) =>
            setSort((s) => ({ key, direction: s.key === key && s.direction === "asc" ? "desc" : "asc" }))
          }
          caption="Demo data"
        />
      </Section>

      <Section title="Feedback & loading">
        <Stack gap={4}>
          <Banner tone="danger">Something went wrong with that request.</Banner>
          <Banner tone="success" onDismiss={() => {}}>Your changes were saved.</Banner>
          <Banner tone="warning">Your plan renews in 3 days.</Banner>
          <Banner tone="info">A neutral, informational message.</Banner>
          <Inline gap={4}>
            <Spinner size="sm" />
            <Spinner size="md" />
            <Spinner size="lg" />
          </Inline>
          <Skeleton width="60%" />
          <Grid cols={3} gap={4}>
            <SkeletonCard />
            <SkeletonCard lines={3} />
            <SkeletonCard />
          </Grid>
          <LoadingBlock />
        </Stack>
      </Section>

      <Section title="Empty state">
        <Card>
          <EmptyState
            icon={Wallet}
            title="No accounts yet"
            body="Accounts hold your money — checking, savings, cash, credit cards."
            action={<Button icon={<Plus size={15} />}>Add an account</Button>}
          />
        </Card>
      </Section>

      <Section title="Modal">
        <Button onClick={() => setModalOpen(true)} icon={<CreditCard size={15} />}>
          Open modal
        </Button>
        <Modal
          open={modalOpen}
          onClose={() => setModalOpen(false)}
          title="Example dialog"
          footer={
            <>
              <Button variant="ghost" onClick={() => setModalOpen(false)}>Cancel</Button>
              <Button variant="primary" onClick={() => setModalOpen(false)}>Confirm</Button>
            </>
          }
        >
          <Stack gap={3}>
            <Text tone="secondary">
              A native &lt;dialog&gt; with focus containment, Esc-to-close, and a footer action slot.
            </Text>
            <Input label="A field inside the modal" placeholder="Type here…" />
          </Stack>
        </Modal>
      </Section>
    </div>
  );
}
