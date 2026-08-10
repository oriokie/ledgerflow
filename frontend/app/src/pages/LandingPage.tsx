import { ArrowRight, Check, Minus } from "lucide-react";
import { useMemo } from "react";
import { Link } from "react-router-dom";
import { usePlans } from "../hooks/useBilling";
import { formatAmount } from "../lib/money";
import { AuthBrand } from "../components/auth/AuthLayout";
import { Illustration } from "../ui/illustration";
import { Banner, Figure } from "../ui";
import { AppPreview } from "./landing/AppPreview";
import { AdvisorShowcase } from "./landing/AdvisorShowcase";
import { LandingHeroArt } from "./landing/LandingHeroArt";
import { FAQ, FEATURES, TESTIMONIALS } from "./landing/marketingCopy";

const DOODLE = { style: "doodle" as const };

/**
 * The product's front door.
 *
 * Built from the same tokens and components as the application, so it is the
 * product speaking rather than a marketing site that happens to link to one.
 * That is also the honest version of the pitch: if the landing page needed its
 * own design language to look good, the application's would not be good enough.
 *
 * Two things it deliberately does not do. It shows no figures — the preview is
 * abstract, because any number on a finance landing page is either someone's
 * real data or invented data dressed as real. And its pricing is fetched from
 * the same public endpoint the billing page uses, so it cannot drift from what
 * a visitor is actually charged.
 */
export function LandingPage() {
  return (
    <div className="lf-landing">
      <LandingHeader />
      <main id="main">
        <Hero />
        <Preview />
        <Features />
        <Intelligence />
        <AdvisorShowcase />
        <Testimonials />
        <Pricing />
        <Faq />
        <ClosingCta />
      </main>
      <LandingFooter />
    </div>
  );
}

function LandingHeader() {
  return (
    <header className="lf-landing-header">
      <a className="lf-skip-link" href="#main">
        Skip to content
      </a>
      <Link to="/" className="lf-landing-brand" aria-label="LedgerFlow home">
        <AuthBrand />
      </Link>
      <nav className="lf-landing-nav" aria-label="Page sections">
        <a href="#features">Features</a>
        <a href="#pricing">Pricing</a>
        <a href="#faq">FAQ</a>
      </nav>
      <div className="lf-landing-header-actions">
        <Link className="lf-btn lf-btn--ghost lf-btn--sm" to="/login">
          Sign in
        </Link>
        <Link className="lf-btn lf-btn--primary lf-btn--sm" to="/register">
          Get started
        </Link>
      </div>
    </header>
  );
}

function Hero() {
  return (
    <section className="lf-hero-shell">
      <div className="lf-hero">
        <div className="lf-hero-copy">
          <p className="lf-hero-eyebrow">Personal finance, kept properly</p>
          <h1 className="lf-hero-title">
            Know exactly where you stand.
            <span className="lf-hero-title-accent"> And why.</span>
          </h1>
          <p className="lf-hero-sub">
            A double-entry ledger with the planning tools on top: budgets, goals, debt payoff and a
            day-by-day cash-flow projection. Every figure shows what it was measured from, so you can
            check it instead of trusting it.
          </p>
          <div className="lf-hero-actions">
            <Link className="lf-btn lf-btn--primary lf-btn--lg" to="/register">
              Start your free week
              <ArrowRight size={16} strokeWidth={2} aria-hidden="true" />
            </Link>
            <a className="lf-btn lf-btn--secondary lf-btn--lg" href="#preview">
              See how it looks
            </a>
          </div>
          <p className="lf-hero-note">Seven days free — no card asked for. Export everything, always.</p>
          <ul className="lf-hero-trust" aria-label="What you get on every plan">
            <li>
              <Check size={15} strokeWidth={2.4} aria-hidden="true" />
              Double-entry ledger
            </li>
            <li>
              <Check size={15} strokeWidth={2.4} aria-hidden="true" />
              Full data export
            </li>
            <li>
              <Check size={15} strokeWidth={2.4} aria-hidden="true" />
              No bank credentials stored
            </li>
          </ul>
        </div>

        <div className="lf-hero-art">
          <div className="lf-illus-frame lf-landing-hero-art" data-size="hero" data-style="doodle">
            <LandingHeroArt />
          </div>
        </div>
      </div>
    </section>
  );
}

function Preview() {
  return (
    <section className="lf-landing-section lf-landing-section--tight" id="preview">
      <SectionHead
        eyebrow="The interface"
        title="Dense where it matters, quiet everywhere else"
        body="The screens that hold your money are data-first — no decoration competing with the numbers. Certainty is drawn into the type itself: a settled balance and a projection never look the same."
      />

      {/* The claim above, shown rather than asserted: the four ways the
          product draws a number, exactly as the app draws them — this is the
          same Figure component every screen uses. A type specimen, not data;
          the labels say what each treatment means. */}
      <div className="lf-landing-certainty" aria-label="How certainty is drawn">
        <Figure label="Settled" amountMinor={4228381} currency="KES" neutral certainty="settled" hint="Posted and reconciled" />
        <Figure label="Pending" amountMinor={120400} currency="KES" neutral certainty="pending" hint="Authorised, not yet cleared" />
        <Figure label="Projected" amountMinor={540000} currency="KES" neutral certainty="projected" hint="From a known recurrence" />
        <Figure
          label="Speculative"
          amountMinor={10000}
          currency="KES"
          neutral
          certainty="speculative"
          confidence="An estimate on thin data — never drawn like a fact."
        />
      </div>

      <AppPreview />
    </section>
  );
}

function Features() {
  return (
    <section className="lf-landing-section" id="features">
      <SectionHead
        eyebrow="What you get"
        title="Built to be checked, not just looked at"
      />
      <div className="lf-feature-grid">
        {FEATURES.map((feature) => (
          <article key={feature.title} className="lf-feature">
            <Illustration name={feature.illustration} size="spot" {...DOODLE} />
            <h3>{feature.title}</h3>
            <p>{feature.body}</p>
          </article>
        ))}
      </div>
    </section>
  );
}

function Intelligence() {
  return (
    <div className="lf-landing-band">
    <section className="lf-landing-section lf-landing-split">
      <div>
        <SectionHead
          eyebrow="Intelligence"
          title="An assistant that never states a number it made up"
          body="Ask a question in plain words and it builds a filter over your ledger — the arithmetic stays the product's, and the filter is shown to you so you can check it. Insights arrive with the evidence attached, and every one has a deterministic fallback, so nothing breaks when the model is unavailable or switched off."
        />
        <ul className="lf-landing-points">
          <li>
            <Check size={16} strokeWidth={2.4} aria-hidden="true" />
            Works fully with no AI provider configured
          </li>
          <li>
            <Check size={16} strokeWidth={2.4} aria-hidden="true" />
            The model cannot read your ledger or write to it
          </li>
          <li>
            <Check size={16} strokeWidth={2.4} aria-hidden="true" />
            Every insight carries the figures it came from
          </li>
        </ul>
      </div>
      <Illustration name="insight" size="panel" {...DOODLE} />
    </section>
    </div>
  );
}

function Testimonials() {
  const anySample = TESTIMONIALS.some((t) => t.sample);
  if (TESTIMONIALS.length === 0) return null;

  return (
    <section className="lf-landing-section">
      <SectionHead eyebrow="In their words" title="What people say" />

      {/* The notice is tied to the data, not written into the page: it appears
          while any quote is flagged `sample` and disappears by itself once real
          ones replace them. Shipping invented endorsements on a page arguing
          this product tells you the truth would undercut the whole argument. */}
      {anySample && (
        <p className="lf-landing-sample-note" role="note">
          <strong>Sample copy.</strong> These are written examples, not customer
          endorsements — here so the section can be seen and adapted. Replace them in{" "}
          <code>marketingCopy.ts</code> and this notice goes away.
        </p>
      )}

      <div className="lf-landing-quotes">
        {TESTIMONIALS.map((t) => (
          <figure key={t.attribution} className="lf-landing-quote">
            <div className="lf-landing-quote-mark" aria-hidden="true">
              <Illustration name="welcome" size="spot" {...DOODLE} />
            </div>
            <blockquote>{t.quote}</blockquote>
            <figcaption>
              <span>{t.attribution}</span>
              {t.sample && <span className="lf-landing-quote-tag">Example</span>}
            </figcaption>
          </figure>
        ))}
      </div>
    </section>
  );
}

function Pricing() {
  const { data: plans, isLoading, isError, refetch } = usePlans("USD");

  /* Monthly only, one row per tier. The annual variants exist in the catalogue
     but doubling the cards to show "two months free" is a worse trade than a
     line of copy. */
  const monthly = useMemo(
    () => (plans ?? []).filter((p) => p.interval === "monthly"),
    [plans],
  );

  /* What each tier ADDS over the one before it, from the plans' own resolved
     features. A pricing table that repeats every feature at every level is
     unreadable — the reader's question is "what do I get by moving up". The
     subtraction runs over the previous card's set, so a feature granted to a
     plan as a one-off override shows on that card exactly like a tier feature:
     the cards render whatever the catalogue actually says, which is the point
     of syncing them. */
  const addsByPlan = useMemo(() => {
    const map = new Map<string, { key: string; label: string }[]>();
    let previous = new Set<string>();
    for (const plan of monthly) {
      const current = plan.resolved_features ?? [];
      map.set(
        plan.id,
        current.filter((f) => !previous.has(f.key)),
      );
      previous = new Set(current.map((f) => f.key));
    }
    return map;
  }, [monthly]);

  return (
    <section className="lf-landing-section" id="pricing">
      <SectionHead
        eyebrow="Pricing"
        title="Two plans, one question"
        body="Do you want the product to think with you, or just keep the books? Every new workspace starts with seven days free on Basic — no card asked for. Reconciliation, the audit trail, two-factor authentication and data export are on both plans; leaving with your books is never a paid feature."
      />

      {isError ? (
        <Banner tone="danger">
          Couldn't load the current plans. Try again in a moment.
          <button
            type="button"
            className="lf-btn lf-btn--ghost lf-btn--sm"
            style={{ marginLeft: "auto" }}
            onClick={() => void refetch()}
          >
            Retry
          </button>
        </Banner>
      ) : monthly.length === 0 ? (
        <p className="lf-landing-muted">
          {isLoading === false ? "No plans available right now." : "Loading the current plans…"}
        </p>
      ) : (
        <div className="lf-price-grid">
          {monthly.map((plan) => (
            <article
              key={plan.id}
              className="lf-price-card"
              data-featured={plan.tier === "plus" || undefined}
            >
              {plan.tier === "plus" && <span className="lf-price-badge">Most chosen</span>}
              <h3>{plan.name}</h3>
              <p className="lf-price-amount">
                {plan.price_minor === 0 ? (
                  "Free"
                ) : (
                  <>
                    {formatAmount(plan.price_minor, plan.currency)}
                    <span className="lf-price-period">/month</span>
                  </>
                )}
              </p>
              <p className="lf-price-pitch">{plan.description}</p>
              <ul className="lf-price-limits">
                <li>
                  {plan.max_accounts} accounts
                </li>
                <li>
                  {plan.max_members} {plan.max_members === 1 ? "person" : "people"}
                </li>
                <li data-off={!plan.ai_insights || undefined}>
                  {plan.ai_insights ? (
                    <Check size={14} strokeWidth={2.4} aria-hidden="true" />
                  ) : (
                    <Minus size={14} strokeWidth={2.4} aria-hidden="true" />
                  )}
                  AI insights
                </li>
              </ul>
              {(addsByPlan.get(plan.id)?.length ?? 0) > 0 && (
                <>
                  <p className="lf-price-adds-label">
                    {plan.price_minor === 0 ? "Includes" : "Everything before it, plus"}
                  </p>
                  <ul className="lf-price-adds">
                    {addsByPlan.get(plan.id)!.map((feature) => (
                      <li key={feature.key}>
                        <Check size={13} strokeWidth={2.4} aria-hidden="true" />
                        {feature.label}
                      </li>
                    ))}
                  </ul>
                </>
              )}
              <Link
                className={`lf-btn ${plan.tier === "plus" ? "lf-btn--primary" : "lf-btn--secondary"}`}
                to="/register"
              >
                {plan.price_minor === 0 ? "Start free" : `Choose ${plan.name}`}
              </Link>
            </article>
          ))}
        </div>
      )}
      <p className="lf-landing-muted">Annual billing is ten months' price — two months free.</p>
    </section>
  );
}

function Faq() {
  return (
    <section className="lf-landing-section" id="faq">
      <SectionHead eyebrow="Questions" title="The things worth asking first" />
      <div className="lf-faq">
        {FAQ.map((item) => (
          <details key={item.q}>
            <summary>{item.q}</summary>
            <p>{item.a}</p>
          </details>
        ))}
      </div>
    </section>
  );
}

function ClosingCta() {
  return (
    <section className="lf-landing-cta">
      <Illustration name="welcome" size="spot" {...DOODLE} />
      <h2>Start with one account and a week of transactions.</h2>
      <p>That is enough for the projection to say something useful.</p>
      <Link className="lf-btn lf-btn--primary" to="/register">
        Create your workspace
        <ArrowRight size={16} strokeWidth={2} aria-hidden="true" />
      </Link>
    </section>
  );
}

function LandingFooter() {
  return (
    <footer className="lf-landing-footer">
      <div className="lf-landing-footer-brand">
        <AuthBrand />
        <p>Clarity for every account, budget, and goal.</p>
      </div>
      <nav aria-label="Footer">
        <div>
          <h2>Product</h2>
          <a href="#features">Features</a>
          <a href="#pricing">Pricing</a>
          <a href="#faq">FAQ</a>
        </div>
        <div>
          <h2>Account</h2>
          <Link to="/login">Sign in</Link>
          <Link to="/register">Create account</Link>
          <Link to="/forgot-password">Reset password</Link>
        </div>
      </nav>
      <p className="lf-landing-copyright">
        © {new Date().getFullYear()} LedgerFlow
      </p>
    </footer>
  );
}

function SectionHead({
  eyebrow,
  title,
  body,
}: {
  eyebrow: string;
  title: string;
  body?: string;
}) {
  return (
    <div className="lf-landing-head">
      <p className="lf-landing-eyebrow">{eyebrow}</p>
      <h2>{title}</h2>
      {body && <p className="lf-landing-lede">{body}</p>}
    </div>
  );
}
