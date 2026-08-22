import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { WorkNotePreparation } from "./work-note-preparation";

const clientId = "00000000-0000-4000-8000-000000000002";
const candidate = {
  status: "PREPARED",
  execution_id: "00000000-0000-4000-8000-000000000201",
  problem: null,
  candidate: {
    client_id: clientId,
    execution_id: "00000000-0000-4000-8000-000000000201",
    task_id: "ai.prepare_work_note",
    task_version: "1",
    output_hash: "a".repeat(64),
    draft: "A provisional client work-note draft.",
    suggested_follow_up: "Verify the supporting evidence.",
    caveat: "Professional review is required.",
    review_required: true,
    authoritative: false,
  },
} as const;
const availableCapability = {
  task_id: "ai.prepare_work_note",
  state: "AVAILABLE",
  available: true,
  retryable: false,
  retry_after_seconds: null,
} as const;

function aiFetch(post: () => Promise<Response>) {
  return vi.fn((...args: [RequestInfo | URL, RequestInit?]) =>
    String(args[0]).endsWith("/api/ai/capability")
      ? Promise.resolve(Response.json(availableCapability))
      : post(),
  );
}

function postCallCount(fetchMock: ReturnType<typeof vi.fn>) {
  return fetchMock.mock.calls.filter(
    ([input]) => !String(input).endsWith("/api/ai/capability"),
  ).length;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("WorkNotePreparation", () => {
  it("forwards only the selected stored-file IDs with the manual note", async () => {
    const sourceFileId = "00000000-0000-4000-8000-000000000301";
    const fetchMock = aiFetch(async () => Response.json(candidate));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(
      <WorkNotePreparation
        activeClientId={clientId}
        sourceFileIds={[sourceFileId]}
      />,
    );

    await user.type(screen.getByRole("textbox"), "Synthetic note");
    await user.click(
      screen.getByRole("button", { name: "Prepare with Privexa" }),
    );
    await screen.findByText("A provisional client work-note draft.");

    const postCall = fetchMock.mock.calls.find(
      ([input]) => !String(input).endsWith("/api/ai/capability"),
    );
    expect(postCall).toBeDefined();
    expect(JSON.parse(String(postCall?.[1]?.body))).toEqual({
      note: "Synthetic note",
      source_file_ids: [sourceFileId],
    });
  });

  it("degrades only the AI action while preserving manual work", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      if (String(input).endsWith("/api/ai/capability")) {
        return Promise.resolve(
          Response.json({
            ...availableCapability,
            state: "UNAVAILABLE",
            available: false,
          }),
        );
      }
      throw new Error("the unavailable action must not call execution");
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<WorkNotePreparation activeClientId={clientId} />);

    const note = screen.getByRole("textbox", { name: "Client work note" });
    await user.type(note, "Manual work remains editable during an AI outage.");

    expect(
      await screen.findByText(
        "Privexa assistance is temporarily unavailable. You can continue working normally.",
      ),
    ).toBeInTheDocument();
    expect(note).toBeEnabled();
    expect(note).toHaveValue(
      "Manual work remains editable during an AI outage.",
    );
    const unavailableAction = screen.getByRole("button", {
      name: "Prepare with Privexa · unavailable",
    });
    expect(unavailableAction).toBeDisabled();
    expect(unavailableAction).toHaveAttribute(
      "aria-describedby",
      "ai-availability-notice",
    );
    expect(document.getElementById("ai-availability-notice")).toHaveAttribute(
      "aria-live",
      "polite",
    );
    expect(postCallCount(fetchMock)).toBe(0);
  });

  it("preserves manual content while preparing and requires explicit acceptance", async () => {
    let resolveResponse: ((value: Response) => void) | undefined;
    const fetchMock = aiFetch(
      () =>
        new Promise<Response>((resolve) => {
          resolveResponse = resolve;
        }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<WorkNotePreparation activeClientId={clientId} />);

    const note = screen.getByRole("textbox", { name: "Client work note" });
    await user.type(
      note,
      "Ananya Sharma can be reached at ananya.sharma@example.test.",
    );
    await user.click(
      screen.getByRole("button", { name: "Prepare with Privexa" }),
    );

    expect(screen.getByRole("button", { name: "Preparing…" })).toBeDisabled();
    expect(note).toHaveValue(
      "Ananya Sharma can be reached at ananya.sharma@example.test.",
    );
    resolveResponse?.(Response.json(candidate));

    expect(
      await screen.findByRole("heading", {
        name: "Review this provisional draft",
      }),
    ).toBeInTheDocument();
    expect(screen.getByText("Review required")).toBeInTheDocument();
    expect(note).toHaveValue(
      "Ananya Sharma can be reached at ananya.sharma@example.test.",
    );

    await user.click(screen.getByRole("button", { name: "Use draft" }));
    expect(
      screen.getByRole("heading", { name: "Draft selected for your work" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Human accepted")).toBeInTheDocument();
    expect(note).toHaveValue("A provisional client work-note draft.");
    expect(
      screen.queryByRole("button", { name: "Use draft" }),
    ).not.toBeInTheDocument();
  });

  it("dismisses without a new request and retries as a distinct request", async () => {
    const fetchMock = aiFetch(async () => Response.json(candidate));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<WorkNotePreparation activeClientId={clientId} />);

    await user.type(screen.getByRole("textbox"), "Synthetic note");
    await user.click(
      screen.getByRole("button", { name: "Prepare with Privexa" }),
    );
    await screen.findByText("A provisional client work-note draft.");
    await user.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(
      screen.queryByText("A provisional client work-note draft."),
    ).not.toBeInTheDocument();
    expect(postCallCount(fetchMock)).toBe(1);

    await user.click(
      screen.getByRole("button", { name: "Prepare with Privexa" }),
    );
    await screen.findByText("A provisional client work-note draft.");
    await user.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(postCallCount(fetchMock)).toBe(3));
  });

  it("shows a restrained restricted state and keeps manual work available", async () => {
    vi.stubGlobal(
      "fetch",
      aiFetch(async () =>
        Response.json({
          status: "RESTRICTED",
          execution_id: "00000000-0000-4000-8000-000000000202",
          candidate: null,
          problem: {
            code: "AI_CONTEXT_RESTRICTED",
            detail:
              "Preparation is unavailable for this context. Continue manually.",
            retryable: false,
            retry_after_seconds: null,
          },
        }),
      ),
    );
    const user = userEvent.setup();
    render(<WorkNotePreparation activeClientId={clientId} />);

    const note = screen.getByRole("textbox");
    await user.type(note, "Manual work remains here");
    await user.click(
      screen.getByRole("button", { name: "Prepare with Privexa" }),
    );

    expect(
      await screen.findByRole("heading", {
        name: "Preparation unavailable for this context",
      }),
    ).toBeInTheDocument();
    expect(note).toHaveValue("Manual work remains here");
    expect(
      screen.getByRole("button", {
        name: "Prepare with Privexa · unavailable",
      }),
    ).toBeDisabled();
  });

  it("treats stale available state as advisory when the backend disables AI", async () => {
    const fetchMock = aiFetch(async () =>
      Response.json({
        status: "FAILED",
        execution_id: "00000000-0000-4000-8000-000000000203",
        candidate: null,
        problem: {
          code: "AI_GATEWAY_DISABLED",
          detail:
            "Privexa assistance is unavailable. Your manual note is unchanged.",
          retryable: false,
          retry_after_seconds: null,
        },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<WorkNotePreparation activeClientId={clientId} />);

    const note = screen.getByRole("textbox", { name: "Client work note" });
    await user.type(note, "Manual analysis must survive stale capability state.");
    await screen.findByRole("button", { name: "Prepare with Privexa" });
    await user.click(
      screen.getByRole("button", { name: "Prepare with Privexa" }),
    );

    expect(
      await screen.findByText(
        "Privexa assistance is unavailable. Your manual note is unchanged.",
      ),
    ).toBeInTheDocument();
    expect(note).toHaveValue(
      "Manual analysis must survive stale capability state.",
    );
    expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
    expect(
      screen.getByRole("button", {
        name: "Prepare with Privexa · unavailable",
      }),
    ).toBeDisabled();
    expect(postCallCount(fetchMock)).toBe(1);
  });

  it("terminates a retryable failure and preserves manual work", async () => {
    vi.stubGlobal(
      "fetch",
      aiFetch(async () =>
        Response.json({
          status: "FAILED",
          execution_id: "00000000-0000-4000-8000-000000000204",
          candidate: null,
          problem: {
            code: "AI_TIMEOUT",
            detail:
              "Preparation is temporarily unavailable. Your manual note is unchanged.",
            retryable: true,
            retry_after_seconds: 30,
          },
        }),
      ),
    );
    const user = userEvent.setup();
    render(<WorkNotePreparation activeClientId={clientId} />);

    const note = screen.getByRole("textbox", { name: "Client work note" });
    await user.type(note, "Manual timeout-safe note");
    await user.click(
      screen.getByRole("button", { name: "Prepare with Privexa" }),
    );

    expect(await screen.findByRole("button", { name: "Try again" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Preparing…" })).toBeNull();
    expect(note).toBeEnabled();
    expect(note).toHaveValue("Manual timeout-safe note");
  });

  it("rejects a candidate bound to another active client", async () => {
    vi.stubGlobal(
      "fetch",
      aiFetch(async () =>
        Response.json({
          ...candidate,
          candidate: { ...candidate.candidate, client_id: "other-client" },
        }),
      ),
    );
    const user = userEvent.setup();
    render(<WorkNotePreparation activeClientId={clientId} />);

    await user.type(screen.getByRole("textbox"), "Synthetic note");
    await user.click(
      screen.getByRole("button", { name: "Prepare with Privexa" }),
    );

    expect(
      await screen.findByRole("heading", {
        name: "Privexa assistance unavailable",
      }),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("A provisional client work-note draft."),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Try again" }),
    ).not.toBeInTheDocument();
  });

  it("discards manual and prepared state when the authoritative client changes", async () => {
    vi.stubGlobal(
      "fetch",
      aiFetch(async () => Response.json(candidate)),
    );
    const user = userEvent.setup();
    const { rerender } = render(
      <WorkNotePreparation activeClientId={clientId} />,
    );

    await user.type(screen.getByRole("textbox"), "Client A manual note");
    await user.click(
      screen.getByRole("button", { name: "Prepare with Privexa" }),
    );
    expect(
      await screen.findByText("A provisional client work-note draft."),
    ).toBeInTheDocument();

    rerender(
      <WorkNotePreparation activeClientId="00000000-0000-4000-8000-000000000099" />,
    );

    expect(screen.getByRole("textbox")).toHaveValue("");
    expect(
      screen.queryByText("A provisional client work-note draft."),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Use draft" }),
    ).not.toBeInTheDocument();
  });

  it("discards an in-flight Client A result after switching to Client B", async () => {
    let resolveResponse: ((value: Response) => void) | undefined;
    vi.stubGlobal(
      "fetch",
      aiFetch(
        () =>
          new Promise<Response>((resolve) => {
            resolveResponse = resolve;
          }),
      ),
    );
    const user = userEvent.setup();
    const { rerender } = render(
      <WorkNotePreparation activeClientId={clientId} />,
    );

    await user.type(screen.getByRole("textbox"), "Client A manual note");
    await user.click(
      screen.getByRole("button", { name: "Prepare with Privexa" }),
    );
    expect(screen.getByRole("button", { name: "Preparing…" })).toBeDisabled();

    rerender(
      <WorkNotePreparation activeClientId="00000000-0000-4000-8000-000000000099" />,
    );
    resolveResponse?.(Response.json(candidate));

    await waitFor(() => expect(screen.getByRole("textbox")).toHaveValue(""));
    expect(
      screen.queryByText("A provisional client work-note draft."),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Use draft" }),
    ).not.toBeInTheDocument();
  });

  it("bounds duplicate submission while one preparation is pending", async () => {
    const fetchMock = aiFetch(() => new Promise<Response>(() => undefined));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<WorkNotePreparation activeClientId={clientId} />);

    await user.type(screen.getByRole("textbox"), "Synthetic note");
    await user.dblClick(
      screen.getByRole("button", { name: "Prepare with Privexa" }),
    );

    expect(postCallCount(fetchMock)).toBe(1);
    expect(screen.getByRole("button", { name: "Preparing…" })).toBeDisabled();
  });

  it("renders hostile provider strings as inert text", async () => {
    vi.stubGlobal(
      "fetch",
      aiFetch(async () =>
        Response.json({
          ...candidate,
          candidate: {
            ...candidate.candidate,
            draft: '<script>alert("synthetic")</script>',
            suggested_follow_up: '[click](javascript:alert("synthetic"))',
          },
        }),
      ),
    );
    const user = userEvent.setup();
    const { container } = render(
      <WorkNotePreparation activeClientId={clientId} />,
    );

    await user.type(screen.getByRole("textbox"), "Synthetic note");
    await user.click(
      screen.getByRole("button", { name: "Prepare with Privexa" }),
    );

    expect(
      await screen.findByText('<script>alert("synthetic")</script>'),
    ).toBeInTheDocument();
    expect(
      screen.getByText('[click](javascript:alert("synthetic"))'),
    ).toBeInTheDocument();
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector('a[href^="javascript:"]')).toBeNull();
  });
});
