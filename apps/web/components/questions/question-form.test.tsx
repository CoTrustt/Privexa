import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { QuestionForm } from "./question-form";

afterEach(cleanup);

describe("QuestionForm", () => {
  it("focuses the primary question and associates useful validation", async () => {
    const onSubmit = vi.fn();
    render(
      <QuestionForm
        autoFocus
        prompt="What does Apollo Finance need help with?"
        submitLabel="Add question"
        onSubmit={onSubmit}
        onCancel={vi.fn()}
      />,
    );
    const question = screen.getByLabelText("What does Apollo Finance need help with?");
    expect(question).toHaveFocus();
    await userEvent.type(question, "   ");
    await userEvent.click(screen.getByRole("button", { name: "Add question" }));
    expect(await screen.findByText("Question cannot be empty.")).toBeInTheDocument();
    expect(question).toHaveAttribute("aria-invalid", "true");
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("preserves the draft and prevents repeated submission while saving", async () => {
    let finish: ((value: { ok: false; message: string }) => void) | undefined;
    const onSubmit = vi.fn(
      () => new Promise<{ ok: false; message: string }>((resolve) => { finish = resolve; }),
    );
    render(
      <QuestionForm
        prompt="Question"
        submitLabel="Save changes"
        onSubmit={onSubmit}
        onCancel={vi.fn()}
      />,
    );
    const input = screen.getByLabelText("Question");
    await userEvent.type(input, "Can we retain support recordings?");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(screen.getByRole("button", { name: "Saving…" })).toBeDisabled();
    expect(onSubmit).toHaveBeenCalledTimes(1);
    finish?.({ ok: false, message: "Temporary save failure." });
    expect(await screen.findByRole("alert")).toHaveTextContent("Temporary save failure.");
    expect(input).toHaveValue("Can we retain support recordings?");
    await waitFor(() => expect(screen.getByRole("button", { name: "Save changes" })).toBeEnabled());
  });
});
