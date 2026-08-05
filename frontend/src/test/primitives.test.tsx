import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { Badge, Button, EmptyState, Skeleton } from "../components/ui/primitives";

describe("Badge", () => {
  it("renders children", () => {
    render(<Badge>Live</Badge>);
    expect(screen.getByText("Live")).toBeInTheDocument();
  });
});

describe("Button", () => {
  it("renders and responds to click", () => {
    const onClick = vi.fn();
    render(<Button onClick={onClick}>Run Audit</Button>);
    fireEvent.click(screen.getByText("Run Audit"));
    expect(onClick).toHaveBeenCalledOnce();
  });

  it("respects the disabled prop", () => {
    const onClick = vi.fn();
    render(
      <Button onClick={onClick} disabled>
        Run Audit
      </Button>
    );
    fireEvent.click(screen.getByText("Run Audit"));
    expect(onClick).not.toHaveBeenCalled();
  });
});

describe("EmptyState", () => {
  it("renders title and description", () => {
    render(<EmptyState title="No audits yet" description="Run one to get started." />);
    expect(screen.getByText("No audits yet")).toBeInTheDocument();
    expect(screen.getByText("Run one to get started.")).toBeInTheDocument();
  });

  it("renders an action when provided", () => {
    render(<EmptyState title="Empty" action={<button>Do something</button>} />);
    expect(screen.getByText("Do something")).toBeInTheDocument();
  });
});

describe("Skeleton", () => {
  it("renders without crashing", () => {
    const { container } = render(<Skeleton className="h-4 w-4" />);
    expect(container.firstChild).not.toBeNull();
  });
});
