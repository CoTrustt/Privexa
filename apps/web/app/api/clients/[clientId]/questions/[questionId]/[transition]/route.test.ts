// @vitest-environment node

import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));

import { POST } from "./route";

const clientId = "20000000-0000-4000-8000-000000000001";
const questionId = "10000000-0000-4000-8000-000000000001";

function request() {
  return new NextRequest(`http://localhost:3000/api/clients/${clientId}/questions/${questionId}/resolve`, {
    method: "POST",
    headers: { origin: "http://localhost:3000", "content-type": "application/json" },
    body: JSON.stringify({ expected_version: 2 }),
  });
}

afterEach(() => vi.unstubAllGlobals());

describe("Question lifecycle BFF", () => {
  it("refuses arbitrary status transitions", async () => {
    const upstream = vi.fn();
    vi.stubGlobal("fetch", upstream);
    const response = await POST(request(), {
      params: Promise.resolve({ clientId, questionId, transition: "approve" }),
    });
    expect(response.status).toBe(400);
    expect(upstream).not.toHaveBeenCalled();
  });

  it("forwards a narrow lifecycle command", async () => {
    const upstream = vi.fn().mockResolvedValue(Response.json({ status: "RESOLVED" }));
    vi.stubGlobal("fetch", upstream);
    const response = await POST(request(), {
      params: Promise.resolve({ clientId, questionId, transition: "resolve" }),
    });
    expect(response.status).toBe(200);
    expect(upstream).toHaveBeenCalledWith(
      `http://localhost:8000/v1/clients/${clientId}/questions/${questionId}/resolve`,
      expect.objectContaining({ method: "POST", body: JSON.stringify({ expected_version: 2 }) }),
    );
  });
});
