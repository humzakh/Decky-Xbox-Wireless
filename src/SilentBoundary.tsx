import { Component, ReactNode } from "react";

/** Hides what we added to Steam's UI on a crash instead of letting it break Steam's page. */
export class SilentBoundary extends Component<{ name: string; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(e: unknown) {
    console.error(`[Xbox Wireless] ${this.props.name} crashed`, e);
  }

  render() {
    return this.state.failed ? null : this.props.children;
  }
}
