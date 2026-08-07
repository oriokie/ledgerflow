import { zodResolver } from "@hookform/resolvers/zod";
import { BookOpen, Landmark, Plus } from "lucide-react";
import { useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { useSearchParams } from "react-router-dom";
import { z } from "zod";
import { ApiError } from "../api/client";
import type { FinancialAccount, LedgerAccount } from "../api/types";
import {
  useAccounts,
  useAssignAccountToWallet,
  useCreateAccount,
  useCreateWallet,
  useWallets,
} from "../hooks/useFinance";
import { useLedgerAccounts } from "../hooks/useLedger";
import { plural } from "../lib/plural";
import {
  Badge,
  Banner,
  Button,
  Card,
  EmptyState,
  Figure,
  FigureRow,
  Grid,
  Input,
  Modal,
  Money,
  PageHeader,
  Select,
  SkeletonCard,
  Table,
  Text,
  useToast,
} from "../ui";
import type { Column } from "../ui";
import { AccountDetail, AccountList, StatementModal, WalletsSection } from "./accounts";
import { AccountTypeIcon } from "./accounts/AccountTypeIcon";
import { useOpenOnParam } from "../hooks/useOpenOnParam";
import { CURRENCY_OPTIONS } from "../lib/currencies";
import { majorToMinor } from "../lib/money";
import { useAuth } from "../lib/AuthContext";
import { groupAccounts, primaryCurrency, summarizeByCurrency } from "./accounts/summary";

const ACCOUNT_TYPES = [
  { value: "checking", label: "Checking" },
  { value: "savings", label: "Savings" },
  { value: "cash", label: "Cash" },
  { value: "credit_card", label: "Credit card" },
  { value: "loan", label: "Loan" },
  { value: "investment", label: "Investment" },
];

const accountSchema = z.object({
  name: z.string().min(1, "Name this account."),
  account_type: z.string().min(1),
  currency: z.string().length(3, "3-letter code, e.g. USD."),
  // Optional, but if given it must be exactly the last four digits — a
  // partial mask is worse than none for telling two cards apart.
  mask: z
    .string()
    .regex(/^\d{4}$/, "Four digits, or leave blank.")
    .optional()
    .or(z.literal("")),
  // Always a positive magnitude in the account's own direction — what you hold
  // for an asset, what you owe for a card or loan. The server derives the
  // debit/credit direction from the account type, so the user never has to
  // think about signs.
  opening_balance: z
    .string()
    .optional()
    .refine((v) => !v || (/^\d*\.?\d{0,2}$/.test(v) && Number(v) >= 0), {
      message: "Enter a positive amount, e.g. 3250.00",
    }),
});
type AccountForm = z.infer<typeof accountSchema>;

const walletSchema = z.object({ name: z.string().min(1, "Name this wallet.") });
type WalletForm = z.infer<typeof walletSchema>;

function SummaryBar({ accounts }: { accounts: FinancialAccount[] }) {
  const totals = summarizeByCurrency(accounts);
  const primary = totals[0];
  if (!primary) return null;
  return (
    <Card style={{ marginBottom: "var(--lf-space-4)" }}>
      {/* Net worth leads: it is the answer, and assets/liabilities are the
          working behind it. Previously the three ran left-to-right at two
          different sizes separated by rules, so the headline figure arrived
          last and nothing shared a baseline. */}
      <FigureRow lead>
        <Figure
          label="Net worth"
          size="hero"
          amountMinor={primary.net_minor}
          currency={primary.currency}
          neutral
        />
        <Figure label="Assets" amountMinor={primary.assets_minor} currency={primary.currency} neutral />
        <Figure
          label="Liabilities"
          amountMinor={primary.liabilities_minor}
          currency={primary.currency}
          neutral
        />
      </FigureRow>
      {totals.length > 1 && (
        <Text tone="tertiary" size="xs" style={{ marginTop: "var(--lf-space-3)", display: "block" }}>
          +{plural(totals.length - 1, "more currency", "more currencies")}
        </Text>
      )}
    </Card>
  );
}

export function AccountsPage() {
  const { activeWorkspace } = useAuth();
  const baseCurrency = activeWorkspace?.tenant.base_currency ?? "USD";
  const { data: accounts, isLoading } = useAccounts();
  const { data: wallets } = useWallets();
  const createAccount = useCreateAccount();
  const createWallet = useCreateWallet();
  const assign = useAssignAccountToWallet();
  const toast = useToast();

  const [searchParams, setSearchParams] = useSearchParams();
  const [mobileView, setMobileView] = useState<"list" | "detail">("list");
  const [showCreate, setShowCreate] = useOpenOnParam();
  const [showWallet, setShowWallet] = useState(false);
  const [statementFor, setStatementFor] = useState<FinancialAccount | null>(null);
  const [showLedger, setShowLedger] = useState(false);
  const { data: ledgerAccounts } = useLedgerAccounts(showLedger);
  const [serverError, setServerError] = useState<string | null>(null);

  const accountForm = useForm<AccountForm>({
    resolver: zodResolver(accountSchema),
    defaultValues: { account_type: "checking", currency: baseCurrency, mask: "", opening_balance: "" },
  });
  const walletForm = useForm<WalletForm>({ resolver: zodResolver(walletSchema) });

  // Drives the live preview in the create modal.
  const watchedName = accountForm.watch("name");
  const watchedType = accountForm.watch("account_type");
  const watchedCurrency = accountForm.watch("currency");
  const watchedMask = accountForm.watch("mask");
  const watchedOpening = accountForm.watch("opening_balance");
  // Liability accounts hold what you *owe*, so the field is labelled
  // accordingly — asking for a "balance" on a credit card is exactly how users
  // enter the wrong sign.
  const isLiabilityType = watchedType === "credit_card" || watchedType === "loan";

  // Visual order (assets then liabilities) drives prev/next stepping.
  const ordered = useMemo(() => {
    const g = groupAccounts(accounts);
    return [...g.assets, ...g.liabilities];
  }, [accounts]);
  const cur = primaryCurrency(accounts);

  const selectedId = searchParams.get("account");

  const selected = ordered.find((a) => a.id === selectedId) ?? ordered[0] ?? null;

  const selectAccount = (id: string) => {
    setSearchParams(
      (prev) => {
        const p = new URLSearchParams(prev);
        p.set("account", id);
        return p;
      },
      { replace: true },
    );
    setMobileView("detail");
  };

  const onCreateAccount = accountForm.handleSubmit(async (values) => {
    setServerError(null);
    try {
      const created = await createAccount.mutateAsync({
        name: values.name,
        account_type: values.account_type,
        currency: values.currency.toUpperCase(),
        // Omit rather than send an empty string — the field is genuinely absent.
        ...(values.mask ? { mask: values.mask } : {}),
        // Posted by the server as a real double-entry opening journal entry
        // against Opening Balance Equity — never stored as a bare column.
        ...(values.opening_balance
          ? { opening_balance_minor: majorToMinor(Number(values.opening_balance)) }
          : {}),
      });
      accountForm.reset({
        account_type: values.account_type,
        currency: values.currency,
        mask: "",
        opening_balance: "",
      });
      setShowCreate(false);
      const id = (created as { id?: string })?.id;
      if (id) selectAccount(id);
    } catch (err) {
      setServerError(err instanceof ApiError ? err.detail : "Couldn't create the account.");
    }
  });

  const onAssignWallet = async (accountId: string, walletId: string | null) => {
    try {
      await assign.mutateAsync({ accountId, walletId });
    } catch (err) {
      toast(err instanceof ApiError ? err.detail : "Couldn't move that account.", { tone: "danger" });
    }
  };

  const onCreateWallet = walletForm.handleSubmit(async (values) => {
    try {
      await createWallet.mutateAsync(values);
      walletForm.reset();
      setShowWallet(false);
    } catch (err) {
      setServerError(err instanceof ApiError ? err.detail : "Couldn't create the wallet.");
    }
  });

  const ledgerColumns: Column<LedgerAccount>[] = [
    {
      key: "name",
      header: "Account",
      render: (la) => (
        <>
          {la.name}
          {la.is_system && (
            <Badge tone="neutral">
              <span style={{ marginLeft: 8 }}>system</span>
            </Badge>
          )}
        </>
      ),
    },
    { key: "kind", header: "Kind", render: (la) => <span className="lf-cell-meta">{la.kind}</span> },
    {
      key: "balance",
      header: "Balance",
      align: "right",
      render: (la) => <Money amountMinor={la.balance_minor} currency={la.currency} neutral />,
    },
  ];

  return (
    <>
      <PageHeader
        eyebrow={accounts ? `${accounts.length} accounts · ${cur}` : undefined}
        title="Accounts"
        actions={
          <>
            <Button variant="secondary" onClick={() => setShowWallet(true)}>
              New wallet
            </Button>
            <Button variant="primary" icon={<Plus size={15} strokeWidth={2} />} onClick={() => setShowCreate(true)}>
              New account
            </Button>
          </>
        }
      />

      {isLoading && (
        <Grid cols={3} gap={4}>
          {[0, 1, 2].map((i) => (
            <SkeletonCard key={i} />
          ))}
        </Grid>
      )}

      {accounts && accounts.length === 0 && (
        <Card>
          <EmptyState
            icon={Landmark}
            title="Add your first account"
            body="Accounts hold your money — checking, savings, cash, credit cards. Everything else builds on them."
            tips={[
              "Each account keeps its own currency; reports convert to your base.",
              "Credit cards and loans are tracked as money you owe, not money you have.",
              "Group related accounts into a wallet once you have a few.",
            ]}
            action={
              <Button variant="primary" onClick={() => setShowCreate(true)}>
                Add an account
              </Button>
            }
          />
        </Card>
      )}

      {accounts && accounts.length > 0 && (
        <div className="lf-dash-section">
          <SummaryBar accounts={accounts} />
          <div className="lf-acct-layout" data-mobile-view={mobileView}>
            <div className="lf-acct-list-col">
              <AccountList
                accounts={accounts}
                selectedId={selected?.id ?? null}
                onSelect={selectAccount}
                primaryCurrency={cur}
              />
            </div>
            <div className="lf-acct-detail-col">
              {selected && (
                <AccountDetail
                  account={selected}
                  accounts={ordered}
                  wallets={wallets}
                  onSelect={selectAccount}
                  onBack={() => setMobileView("list")}
                  onAssignWallet={onAssignWallet}
                  onOpenStatement={() => setStatementFor(selected)}
                />
              )}
            </div>
          </div>
        </div>
      )}

      <WalletsSection wallets={wallets} onNewWallet={() => setShowWallet(true)} />

      <details
        className="lf-disclosure"
        open={showLedger}
        onToggle={(e) => setShowLedger((e.target as HTMLDetailsElement).open)}
      >
        <summary>
          <BookOpen size={15} strokeWidth={1.8} aria-hidden="true" style={{ verticalAlign: "-2px", marginRight: 6 }} />
          Ledger accounts (double-entry view)
        </summary>
        <div className="lf-disclosure-body">
          <Text tone="tertiary" size="sm" style={{ marginBottom: "var(--lf-space-3)" }}>
            The raw double-entry chart of accounts behind everything above. Read-only — money moves only through
            recorded transactions.
          </Text>
          {ledgerAccounts && <Table columns={ledgerColumns} rows={ledgerAccounts} rowKey={(la) => la.id} responsive={false} />}
        </div>
      </details>

      <Modal
        open={showCreate}
        onClose={() => setShowCreate(false)}
        title="New account"
        description="Accounts hold your money. Everything else in LedgerFlow — budgets, bills, reports — builds on them."
        size="xl"
        footerStart={
          <Button variant="secondary" onClick={() => setShowCreate(false)}>
            Cancel
          </Button>
        }
        footer={
          <Button variant="primary" onClick={() => onCreateAccount()} loading={accountForm.formState.isSubmitting}>
            Create account
          </Button>
        }
      >
        <form onSubmit={onCreateAccount} noValidate>
          <div className="lf-form-stack">
            {/* A live preview of the row this account will become. It costs
                one component and removes the "what will this look like?"
                uncertainty before the user commits. */}
            <div className="lf-acct-preview" aria-hidden="true">
              <AccountTypeIcon type={watchedType} size="lg" />
              <div className="lf-acct-preview-text">
                <span className="lf-acct-preview-name">{watchedName?.trim() || "Account name"}</span>
                <span className="lf-acct-preview-meta">
                  {ACCOUNT_TYPES.find((t) => t.value === watchedType)?.label ?? "Checking"}
                  {watchedMask ? ` · ••${watchedMask}` : ""}
                </span>
              </div>
              <Money
                amountMinor={watchedOpening ? majorToMinor(Number(watchedOpening) || 0) : 0}
                currency={(watchedCurrency || baseCurrency).toUpperCase()}
                neutral
              />
            </div>

            <Input
              label="Account name"
              placeholder="e.g. Everyday Checking"
              hint="What you call it day to day — this is what you'll pick from when recording a transaction."
              autoFocus
              required
              error={accountForm.formState.errors.name?.message}
              {...accountForm.register("name")}
            />

            <div className="lf-field-row">
              <Select
                label="Account type"
                required
                options={ACCOUNT_TYPES}
                hint="Credit cards and loans are tracked as money you owe."
                {...accountForm.register("account_type")}
              />
              <Select
                label="Currency"
                required
                options={CURRENCY_OPTIONS}
                hint="Fixed once set. Reports convert to your base currency."
                error={accountForm.formState.errors.currency?.message}
                {...accountForm.register("currency")}
              />
            </div>

            <div className="lf-field-row">
              <Input
                label={isLiabilityType ? "Amount owed today" : "Starting balance"}
                optional
                amount
                inputMode="decimal"
                placeholder="0.00"
                leading={watchedCurrency || baseCurrency}
                hint={
                  isLiabilityType
                    ? "What's on this card or loan today. Leave blank to start from zero."
                    : "What's in this account today. Leave blank to start from zero."
                }
                error={accountForm.formState.errors.opening_balance?.message}
                {...accountForm.register("opening_balance")}
              />
              <Input
                label="Last 4 digits"
                optional
                placeholder="4321"
                inputMode="numeric"
                maxLength={4}
                hint="Helps you tell similar accounts apart. We never store a full account number."
                error={accountForm.formState.errors.mask?.message}
                {...accountForm.register("mask")}
              />
            </div>

            {/* Opening balances are the first number a user enters and every
                figure downstream inherits them, so the mechanism is stated
                plainly rather than left to be trusted. */}
            <p className="lf-hint">
              An opening balance is recorded as a real double-entry journal entry, so your balances and
              reports reconcile from day one.
            </p>

            {serverError && <Banner tone="danger">{serverError}</Banner>}
          </div>
        </form>
      </Modal>

      <Modal
        open={showWallet}
        onClose={() => setShowWallet(false)}
        title="New wallet"
        description="Wallets group accounts — “Household” vs “Business”, or one pot holding several currencies."
        footerStart={
          <Button variant="secondary" onClick={() => setShowWallet(false)}>
            Cancel
          </Button>
        }
        footer={
          <Button variant="primary" onClick={() => onCreateWallet()} loading={walletForm.formState.isSubmitting}>
            Create wallet
          </Button>
        }
      >
        <form onSubmit={onCreateWallet} noValidate>
          <div className="lf-form-stack">
            <Input
              label="Wallet name"
              required
              autoFocus
              placeholder="e.g. Travel Fund"
              error={walletForm.formState.errors.name?.message}
              {...walletForm.register("name")}
            />
          </div>
        </form>
      </Modal>

      {statementFor && <StatementModal account={statementFor} onClose={() => setStatementFor(null)} />}
    </>
  );
}
