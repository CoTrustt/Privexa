// @vitest-environment node

import { afterEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ sessionToken: undefined as string | undefined }));

vi.mock("server-only", () => ({}));
vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (name: string) =>
      name === "stytch_session" && mocks.sessionToken
        ? { name, value: mocks.sessionToken }
        : undefined,
  }),
}));

import { getQuestion, listQuestions } from "./server";

const question = {
  id: "10000000-0000-4000-8000-000000000001",
  client_id: "20000000-0000-4000-8000-000000000001",
  title: "Retention question",
  question_text: "How long may the client retain this data?",
  context: null,
  status: "OPEN",
  version: 1,
  created_by_membership_id: "30000000-0000-4000-8000-000000000001",
  updated_by_membership_id: "30000000-0000-4000-8000-000000000001",
  created_at: "2026-08-22T10:00:00Z",
  updated_at: "2026-08-22T10:00:00Z",
};

afterEach(() => {
  mocks.sessionToken = undefined;
  vi.unstubAllGlobals();
});

describe("Question server reads", () => {
  it("fails closed without a session", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    await expect(listQuestions({ clientId: question.client_id })).resolves.toMatchObject({
      ok: false,
      status: 401,
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejects malformed identifiers without contacting the API", async () => {
    mocks.sessionToken = "opaque-session";
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    await expect(getQuestion(question.client_id, "not-a-question-id")).resolves.toMatchObject({
      ok: false,
      status: 400,
      problem: { code: "INVALID_IDENTIFIER" },
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("forwards the opaque session with no shared cache and validates the response", async () => {
    mocks.sessionToken = "opaque-session";
    const fetchMock = vi.fn().mockResolvedValue(Response.json(question));
    vi.stubGlobal("fetch", fetchMock);
    await expect(getQuestion(question.client_id, question.id)).resolves.toEqual({
      ok: true,
      data: question,
    });
    expect(fetchMock).toHaveBeenCalledWith(
      `http://localhost:8000/v1/clients/${question.client_id}/questions/${question.id}`,
      { cache: "no-store", headers: { Cookie: "stytch_session=opaque-session" } },
    );
  });

  it("does not serialize malformed or cross-contract upstream data", async () => {
    mocks.sessionToken = "opaque-session";
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ ...question, status: "HIDDEN" })));
    await expect(getQuestion(question.client_id, question.id)).resolves.toMatchObject({
      ok: false,
      status: 502,
      problem: { code: "UNEXPECTED_RESPONSE" },
    });
  });
});
