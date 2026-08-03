import { Component, type ErrorInfo, type ReactNode } from "react";
import { ServerErrorPage } from "../pages/StatusPage";

/**
 * The last boundary, around everything.
 *
 * `RouteErrorBoundary` deliberately degrades to a card so the shell — the rail,
 * the topbar, every escape route — survives a broken screen. But it sits
 * *inside* the shell, so a crash in the shell itself, in the router, or in a
 * provider still takes the whole tree down to a blank tab, which is the one
 * outcome with no way out of it.
 *
 * This catches that case and gives the user a page rather than nothing. It is
 * deliberately dependency-free: anything it imports is code that could be the
 * thing that just failed.
 */
export class AppErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Console rather than a reporter: there is no error-reporting service
    // configured, and inventing a silent one would be worse than the log.
    console.error("Unrecoverable render error", error, info.componentStack);
  }

  render() {
    if (this.state.failed) {
      return <ServerErrorPage onRetry={() => window.location.reload()} />;
    }
    return this.props.children;
  }
}
