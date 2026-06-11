import { Component, type ReactNode } from "react";

export class ErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidCatch(error: unknown) {
    console.error("UI error:", error);
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-6 text-center">
        <p className="text-lg font-medium text-red-800">Something went wrong.</p>
        <button onClick={() => location.reload()}
          className="mt-3 rounded-md bg-red-600 px-4 py-2 text-white">Reload</button>
      </div>
    );
  }
}
