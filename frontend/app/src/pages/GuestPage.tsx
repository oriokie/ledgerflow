import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { AuthBrand } from "../components/auth/AuthLayout";
import { CURRENCIES } from "../lib/currencies";
import type { Position } from "../api/projections";
import { DecisionAssistant } from "./projections/DecisionAssistant";
import { Input, Select, Stack, Text } from "../ui";

function toMinor(raw: string): number {
  const n = Number(raw);
  if (raw.trim() === "" || Number.isNaN(n) || n < 0) return 0;
  return Math.round(n * 100);
}

/**
 * A decision, with no account.
 *
 * The figures live in this page until the request, and the request does not
 * store them. The same form the workspace uses is rendered here so a try and
 * a signed-in answer cannot look like two products.
 */
export function GuestPage() {
  const [currency, setCurrency] = useState("KES");
  const [income, setIncome] = useState("");
  const [expenses, setExpenses] = useState("");
  const [cash, setCash] = useState("");

  const position = useMemo<Position>(
    () => ({
      currency,
      as_of: new Date().toISOString().slice(0, 10),
      liquid_minor: toMinor(cash),
      investment_minor: 0,
      other_assets_minor: 0,
      monthly_net_income_minor: toMinor(income),
      monthly_expenses_minor: toMinor(expenses),
      net_worth_minor: toMinor(cash),
      debts: [],
    }),
    [currency, income, expenses, cash],
  );

  return (
    <div className="lf-landing lf-guest">
      <header className="lf-landing-header">
        <Link to="/" className="lf-landing-brand" aria-label="LedgerFlow home">
          <AuthBrand />
        </Link>
        <div className="lf-landing-header-actions">
          <Link className="lf-btn lf-btn--ghost lf-btn--sm" to="/login">
            Sign in
          </Link>
          <Link className="lf-btn lf-btn--primary lf-btn--sm" to="/register">
            Get started
          </Link>
        </div>
      </header>
      <main id="main" className="lf-guest-main">
        <p className="lf-hero-eyebrow">
          <span aria-hidden="true" />
          No account
        </p>
        <h1 className="lf-guest-title">Ask one question.</h1>
        <p className="lf-guest-lead">
          State what you take home, what you spend, and what you hold in cash. The answer is
          computed from those figures and then forgotten. Nothing is saved.
        </p>
        <div className="lf-guest-layout">
          <section className="lf-guest-position" aria-labelledby="guest-position-title">
            <Stack gap={3}>
              <div>
                <h2 id="guest-position-title" className="lf-guest-position-title">
                  Your picture, stated
                </h2>
                <Text size="sm" tone="secondary">
                  Whole units, the way you would say them. A workspace replaces this with your
                  own records.
                </Text>
              </div>
              <Select
                id="guest-currency"
                label="Currency"
                value={currency}
                onChange={(e) => setCurrency(e.target.value)}
                options={CURRENCIES.map((c) => ({ value: c.code, label: `${c.code} — ${c.name}` }))}
              />
              <Input
                id="guest-income"
                label="Monthly take-home"
                hint="After tax"
                type="number"
                min={0}
                step="any"
                amount
                value={income}
                onChange={(e) => setIncome(e.target.value)}
              />
              <Input
                id="guest-expenses"
                label="Monthly spending"
                type="number"
                min={0}
                step="any"
                amount
                value={expenses}
                onChange={(e) => setExpenses(e.target.value)}
              />
              <Input
                id="guest-cash"
                label="Cash on hand"
                hint="What you could use this week"
                type="number"
                min={0}
                step="any"
                amount
                value={cash}
                onChange={(e) => setCash(e.target.value)}
              />
            </Stack>
          </section>
          <DecisionAssistant position={position} stated />
        </div>
      </main>
    </div>
  );
}
