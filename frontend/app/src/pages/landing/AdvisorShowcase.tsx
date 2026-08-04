import { Link } from "react-router-dom";
import { ArrowRight } from "lucide-react";
import budgetsShot from "../../assets/landing/budgets.png";
import cashflowShot from "../../assets/landing/cashflow.png";
import dashboardShot from "../../assets/landing/dashboard.png";
import reviewShot from "../../assets/landing/review.png";

/**
 * The advisor layer, shown rather than claimed.
 *
 * Every image here is a real capture of the running product against the demo
 * workspace the repo ships — the same discipline as AppPreview, and the alt
 * text says so. A landing page arguing this product tells you the truth
 * cannot decorate itself with mockups of screens that do not exist.
 */
const SHOWCASE = [
  {
    src: reviewShot,
    title: "The sit-down an advisor would run — every month, from your own ledger",
    body:
      "Where you stand, what changed, and what to do next. The Financial Review catches the " +
      "things nobody watches for: in this capture it has spotted a coffee shop quietly raising " +
      "its prices 66% and priced the year of subscriptions at a glance.",
    alt:
      "The Financial Review screen for July 2026: cash flow 59.7% saved, the categories that " +
      "moved most, and a subscriptions section flagging a 66% price rise. Demo data, not a " +
      "real customer.",
  },
  {
    src: dashboardShot,
    title: "One number that answers “can I buy this?”",
    body:
      "Safe to spend is the projection's low point, not today's balance — today's balance is " +
      "the number that gets people overdrawn, because rent hasn't happened yet. When there's " +
      "history, it already assumes your normal spending continues.",
    alt:
      "The overview screen: net worth with a six-month trend, a financial health score of 73, " +
      "and a safe-to-spend figure of KES 35,945.06. Demo data, not a real customer.",
  },
  {
    src: cashflowShot,
    title: "See the month before it happens",
    body:
      "A day-by-day projection of your balance, with your scheduled bills and income on the " +
      "calendar and an uncertainty band measured from your own habits — so the one day the " +
      "balance would dip below zero is named weeks in advance.",
    alt:
      "The cash-flow screen projecting the balance two months ahead, with lowest point, " +
      "ending balance and days below zero. Demo data, not a real customer.",
  },
  {
    src: budgetsShot,
    title: "A budget it writes for you, and warns you about in time",
    body:
      "One click assembles a first draft from your history — medians, not means, with your " +
      "bills as floors and your savings goals funded first. Then pace alerts warn while " +
      "easing off still changes the outcome, not after the money is gone.",
    alt:
      "The budgets screen with per-category progress bars and a Suggest-a-budget button. " +
      "Demo data, not a real customer.",
  },
];

export function AdvisorShowcase() {
  return (
    <section className="lf-landing-section" id="advisor">
      <div className="lf-landing-head">
        <p className="lf-landing-eyebrow">The advisor layer</p>
        <h2>What people pay an advisor for, computed from your own books</h2>
        <p className="lf-landing-lede">
          Not data you lack — the hour where somebody composes it. These are real screens from the
          running product, captured against the demo workspace that ships with it.
        </p>
      </div>

      <div className="lf-showcase">
        {SHOWCASE.map((item, index) => (
          <article key={item.title} className="lf-showcase-item" data-flip={index % 2 === 1 || undefined}>
            <div className="lf-showcase-copy">
              <h3>{item.title}</h3>
              <p>{item.body}</p>
            </div>
            <div className="lf-showcase-frame">
              <img src={item.src} alt={item.alt} loading="lazy" decoding="async" />
            </div>
          </article>
        ))}
      </div>

      <p className="lf-showcase-cta">
        <Link className="lf-btn lf-btn--primary" to="/register">
          Try all of it free for a week
          <ArrowRight size={16} strokeWidth={2} aria-hidden="true" />
        </Link>
      </p>
    </section>
  );
}
