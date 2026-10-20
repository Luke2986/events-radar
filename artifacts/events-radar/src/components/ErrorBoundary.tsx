import { Component } from "react";
import type { ReactNode, ErrorInfo } from "react";

interface Props {
  children: ReactNode;
  fallbackMessage: string;
  resetKey?: string;
}

interface State {
  hasError: boolean;
}

export default class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(): State {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("[ErrorBoundary]", error, info.componentStack);
  }

  componentDidUpdate(prevProps: Props): void {
    if (this.state.hasError && prevProps.resetKey !== this.props.resetKey) {
      this.setState({ hasError: false });
    }
  }

  reset = (): void => {
    this.setState({ hasError: false });
  };

  render() {
    if (this.state.hasError) {
      return (
        <div className="error-fallback">
          <span className="error-fallback-icon">⚠️</span>
          <p className="error-fallback-message">{this.props.fallbackMessage}</p>
          <button className="error-fallback-retry" onClick={this.reset}>
            Riprova
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
