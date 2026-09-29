"use client";

import { Component, type ReactNode } from "react";
import { IconAlertCircle, IconRefresh } from "@tabler/icons-react";

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error("[ErrorBoundary]", error, info.componentStack);
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback;

      return (
        <div className="min-h-[300px] flex items-center justify-center p-8">
          <div className="text-center max-w-md">
            <div className="inline-flex w-12 h-12 rounded-full bg-error/10 border border-error/20 items-center justify-center mb-4">
              <IconAlertCircle size={20} className="text-error" />
            </div>
            <h3 className="text-base font-semibold text-text-primary mb-2">
              Something went wrong
            </h3>
            <p className="text-sm text-text-secondary mb-6">
              {this.state.error?.message || "An unexpected error occurred."}
            </p>
            <button
              onClick={() => this.setState({ hasError: false, error: null })}
              className="inline-flex items-center gap-2 px-5 py-2.5 text-sm font-medium border border-border hover:border-border-hover rounded-full transition-all text-text-primary"
            >
              <IconRefresh size={14} />
              Try again
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}

/** Inline error display for data loading failures */
export function DataError({
  message,
  onRetry,
}: {
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div className="border border-error/20 bg-error/5 p-6 text-center">
      <IconAlertCircle size={20} className="text-error mx-auto mb-3" />
      <p className="text-sm text-text-secondary mb-4">{message}</p>
      {onRetry && (
        <button
          onClick={onRetry}
          className="inline-flex items-center gap-2 px-4 py-2 text-xs font-mono border border-border hover:border-border-hover transition-colors text-text-primary"
        >
          <IconRefresh size={12} />
          Retry
        </button>
      )}
    </div>
  );
}
