import { Link } from "react-router-dom";
import { AuthBrand } from "../components/auth/AuthLayout";
import { Heading, Stack, Text } from "../ui";

const DISCLAIMER =
  "LedgerFlow is an educational decision-support tool, not licensed financial advice. Figures are calculations from the inputs and assumptions shown. They are not a recommendation to buy, sell, borrow, or invest in any specific product, and they do not replace advice from a licensed adviser, accountant, or lender.";

export function PrivacyPage() {
  return (
    <LegalShell title="Privacy policy">
      <Text as="p">
        We collect the account details and financial records you enter so we can run the
        calculations you ask for. We do not sell personal data. You can export your workspace
        data from Settings, and you can delete your account from Profile. Processing is
        intended to comply with the Kenya Data Protection Act, 2019. LedgerFlow is the data
        controller for personal accounts; registration with the Office of the Data Protection
        Commissioner (ODPC) is the operator&apos;s responsibility before a Kenya-wide launch.
      </Text>
      <Text as="p" tone="secondary">
        {DISCLAIMER}
      </Text>
    </LegalShell>
  );
}

export function ContactPage() {
  return (
    <LegalShell title="Contact">
      <Text as="p">
        LedgerFlow is decision support, not a helpline for a specific product. For account,
        billing, or data questions, write to{" "}
        <a href="mailto:support@ledgerflow.app">support@ledgerflow.app</a>. Signed-in users
        can also update their profile and request a data export from Settings.
      </Text>
      <Text as="p" tone="secondary">
        {DISCLAIMER}
      </Text>
    </LegalShell>
  );
}

export function TermsPage() {
  return (
    <LegalShell title="Terms of service">
      <Text as="p">
        By creating an account you agree that LedgerFlow is decision support, not a licensed
        financial-advisory service, and that you remain responsible for the decisions you take.
        Paid plans are billed as described on the pricing page. You may cancel at any time; we
        may suspend a workspace that is used to break the law or to abuse the service.
      </Text>
      <Text as="p" tone="secondary">
        {DISCLAIMER}
      </Text>
    </LegalShell>
  );
}

export function LegalShell({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="lf-status-page">
      <header className="lf-status-header">
        <Link to="/" aria-label="LedgerFlow home">
          <AuthBrand />
        </Link>
      </header>
      <main className="lf-status-body" id="main" style={{ maxWidth: 40 + "rem", textAlign: "left" }}>
        <Stack gap={4}>
          <Heading level={1}>{title}</Heading>
          {children}
          <Text size="sm">
            <Link to="/">Home</Link>
            {" · "}
            <Link to="/privacy">Privacy</Link>
            {" · "}
            <Link to="/terms">Terms</Link>
            {" · "}
            <Link to="/contact">Contact</Link>
          </Text>
        </Stack>
      </main>
    </div>
  );
}
