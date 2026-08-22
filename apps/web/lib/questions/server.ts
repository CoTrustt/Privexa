import "server-only";

import { cookies } from "next/headers";

import {
  isQuestionIdentifier,
  questionListSchema,
  questionProblem,
  questionSchema,
  type Question,
  type QuestionList,
  type QuestionResult,
  type QuestionStatus,
} from "./contracts";

const apiUrl = process.env.PRIVEXA_API_URL ?? "http://localhost:8000";

const unavailable = "Questions could not be loaded right now. Try again.";

async function getFromQuestionApi<T>(
  path: string,
  parse: (value: unknown) => T | null,
): Promise<QuestionResult<T>> {
  const sessionToken = (await cookies()).get("stytch_session")?.value;
  if (!sessionToken) {
    return {
      ok: false,
      status: 401,
      problem: { code: "AUTHENTICATION_REQUIRED", detail: "Sign in to continue." },
    };
  }

  try {
    const response = await fetch(`${apiUrl}${path}`, {
      cache: "no-store",
      headers: { Cookie: `stytch_session=${sessionToken}` },
    });
    const body: unknown = await response.json().catch(() => null);
    if (response.ok) {
      const parsed = parse(body);
      if (parsed !== null) return { ok: true, data: parsed };
      return {
        ok: false,
        status: 502,
        problem: { code: "UNEXPECTED_RESPONSE", detail: unavailable },
      };
    }
    return { ok: false, status: response.status, problem: questionProblem(body, unavailable) };
  } catch {
    return {
      ok: false,
      status: 503,
      problem: { code: "QUESTION_SERVICE_UNAVAILABLE", detail: unavailable },
    };
  }
}

export async function listQuestions({
  clientId,
  status,
  limit = 50,
  offset = 0,
}: {
  clientId: string;
  status?: QuestionStatus;
  limit?: number;
  offset?: number;
}): Promise<QuestionResult<QuestionList>> {
  if (!isQuestionIdentifier(clientId)) {
    return {
      ok: false,
      status: 400,
      problem: { code: "INVALID_IDENTIFIER", detail: "The requested questions are unavailable." },
    };
  }
  const parameters = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (status) parameters.set("status", status);
  return getFromQuestionApi(
    `/v1/clients/${encodeURIComponent(clientId)}/questions?${parameters}`,
    (value) => {
      const parsed = questionListSchema.safeParse(value);
      return parsed.success ? parsed.data : null;
    },
  );
}

export async function getQuestion(
  clientId: string,
  questionId: string,
): Promise<QuestionResult<Question>> {
  if (!isQuestionIdentifier(clientId) || !isQuestionIdentifier(questionId)) {
    return {
      ok: false,
      status: 400,
      problem: { code: "INVALID_IDENTIFIER", detail: "The requested question is unavailable." },
    };
  }
  return getFromQuestionApi(
    `/v1/clients/${encodeURIComponent(clientId)}/questions/${encodeURIComponent(questionId)}`,
    (value) => {
      const parsed = questionSchema.safeParse(value);
      return parsed.success ? parsed.data : null;
    },
  );
}
