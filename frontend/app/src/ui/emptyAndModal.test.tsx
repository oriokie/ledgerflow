import { render, screen } from "@testing-library/react";
import { Wallet } from "lucide-react";
import { describe, expect, it } from "vitest";
import { Button, EmptyState, Modal } from ".";

describe("EmptyState", () => {
  it("renders the title, body and recommended action", () => {
    render(
      <EmptyState
        icon={Wallet}
        title="Add your first account"
        body="Accounts hold your money."
        action={<Button>Add an account</Button>}
      />,
    );
    expect(screen.getByRole("heading", { name: "Add your first account" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add an account" })).toBeInTheDocument();
  });

  it("lists onboarding tips when supplied", () => {
    render(
      <EmptyState
        icon={Wallet}
        title="No budgets yet"
        body="Create one to set limits."
        tips={["Set a limit per category.", "Budgets roll forward each period."]}
      />,
    );
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByText("Set a limit per category.")).toBeInTheDocument();
  });

  it("omits the tips list entirely when there are none", () => {
    render(<EmptyState icon={Wallet} title="Nothing due" body="No upcoming bills." />);
    expect(screen.queryByRole("list")).not.toBeInTheDocument();
  });

  it("supports a secondary action alongside the primary one", () => {
    render(
      <EmptyState
        icon={Wallet}
        title="No transactions yet"
        body="Record one to begin."
        action={<Button>Add transaction</Button>}
        secondaryAction={<Button variant="secondary">Import CSV</Button>}
      />,
    );
    expect(screen.getByRole("button", { name: "Add transaction" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Import CSV" })).toBeInTheDocument();
  });
});

describe("Modal", () => {
  it("labels itself from the title and describes itself from the description", () => {
    render(
      <Modal open onClose={() => {}} title="New account" description="Accounts hold your money.">
        <p>Body</p>
      </Modal>,
    );
    const dialog = screen.getByRole("dialog", { hidden: true });
    expect(dialog).toHaveAccessibleName("New account");
    expect(screen.getByText("Accounts hold your money.")).toBeInTheDocument();
  });

  it("places the cancel action ahead of the primary one in the footer", () => {
    render(
      <Modal
        open
        onClose={() => {}}
        title="New account"
        footerStart={<Button variant="secondary">Cancel</Button>}
        footer={<Button variant="primary">Create account</Button>}
      >
        <p>Body</p>
      </Modal>,
    );
    const buttons = screen.getAllByRole("button", { hidden: true }).map((b) => b.textContent);
    expect(buttons.indexOf("Cancel")).toBeLessThan(buttons.indexOf("Create account"));
  });

  it("renders no footer when neither slot is used", () => {
    const { container } = render(
      <Modal open onClose={() => {}} title="Statement">
        <p>Body</p>
      </Modal>,
    );
    expect(container.querySelector(".lf-modal-footer")).toBeNull();
  });
});
