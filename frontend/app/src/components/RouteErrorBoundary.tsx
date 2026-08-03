import { AlertTriangle, RefreshCw } from "lucide-react";
import { Component, type ErrorInfo, type ReactNode } from "react";
import { Button, Card, EmptyState } from "../ui";

interface Props {
  children: ReactNode;
}

/**
 * To reset the boundary on route change, mount it with `key={pathname}`
 * (done in AppShell) rather than diffing props internally — React unmounts
 * and remounts a component whenever its `key` changes, which trivially gives
 * a fresh `state = { error: null }` through the ordinary mount lifecycle. The
 * alternative (comparing props in `componentDidUpdate` and calling
 * `setState`) works too, but it is a well-known React footgun in general —
 * an unconditioned version causes an infinite render loop — and every
 * linter flags it on sight even when correctly guarded, for exactly that
 * reason. `key`-based remounting needs no guard and trips no rule.
 */

interface State {
  error: Error | null;
}

/**
 * Catches render-time exceptions from whatever it wraps and shows a real
 * fallback instead of a blank screen.
 *
 * This did not exist anywhere in the app before. Its absence is a serious
 * failure mode in its own right: React unmounts the entire tree on an
 * uncaught render error, and without a boundary that takes the page header,
 * navigation, and every button down with it — a crash in one chart or one
 * hook is indistinguishable from the whole page simply not having any
 * controls. A boundary at the route level means a single broken component
 * degrades to a card-sized error, not a blank tab.
 *
 * Deliberately class-based: `componentDidCatch` / `getDerivedStateFromError`
 * are still the only way to catch a render error in React — there is no
 * hook equivalent, by design (a component cannot safely handle its own
 * unmount from inside itself).
 */
export class RouteErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Surfaced to the console with the component stack, which
    // getDerivedStateFromError's return value alone doesn't carry — this is
    // the only lifecycle that sees `info`.
    console.error("Route crashed:", error, info.componentStack);
  }

  private retry = () => this.setState({ error: null });

  render() {
    if (this.state.error) {
      return (
        <Card>
          <EmptyState
            icon={AlertTriangle}
            title="Something went wrong on this page"
            body="The rest of LedgerFlow is fine — this page hit an error while loading. Your data hasn't been affected."
            action={
              <Button variant="primary" onClick={this.retry} icon={<RefreshCw size={15} aria-hidden="true" />}>
                Try again
              </Button>
            }
          />
        </Card>
      );
    }
    return this.props.children;
  }
}
