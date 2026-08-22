// @vitest-environment node

import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));

import { PATCH } from "./route";

const clientId = "20000000-0000-4000-8000-000000000001";
const questionId = "10000000-0000-4000-8000-000000000001";

function request(body: unknown, origin = "http://localhost:3000") {
  return new NextRequest(`http://localhost:3000/api/clients/${clientId}/questions/${questionId}`, {
    method: "PATCH",
    headers: { origin, "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

afterEach(() => vi.unstubAllGlobals());

describe("PATCH Question BFF", () => {
  const update = {
    expected_version: 3,
    title: "May we retain this data?",
    question_text: "May we retain this data after the contract ends?",
    context: null,
  };

  it("rejects invalid origins, identifiers, and versions before upstream", async () => {
    const upstream = vi.fn();
    vi.stubGlobal("fetch", upstream);
    expect((await PATCH(request(update, "https://attacker.example"), { params: Promise.resolve({ clientId, questionId }) })).status).toBe(403);
    expect((await PATCH(request(update), { params: Promise.resolve({ clientId, questionId: "bad" }) })).status).toBe(400);
    expect((await PATCH(request({ ...update, expected_version: 0 }), { params: Promise.resolve({ clientId, questionId }) })).status).toBe(422);
    expect(upstream).not.toHaveBeenCalled();
  });

  it("forwards only the validated optimistic update", async () => {
    const upstream = vi.fn().mockResolvedValue(Response.json({ id: questionId }));
    vi.stubGlobal("fetch", upstream);
    const response = await PATCH(request(update), {
      params: Promise.resolve({ clientId, questionId }),
    });
    expect(response.status).toBe(200);
    expect(upstream).toHaveBeenCalledWith(
      `http://localhost:8000/v1/clients/${clientId}/questions/${questionId}`,
      expect.objectContaining({ method: "PATCH", body: JSON.stringify(update) }),
    );
  });
});
