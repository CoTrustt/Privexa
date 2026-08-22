import { z } from "zod";

export const QUESTION_STATUSES = ["OPEN", "RESOLVED", "CLOSED"] as const;
const questionIdentifierPattern =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export const questionStatusSchema = z.enum(QUESTION_STATUSES);

export const questionSchema = z
  .object({
    id: z.string().uuid(),
    client_id: z.string().uuid(),
    title: z.string(),
    question_text: z.string(),
    context: z.string().nullable(),
    status: questionStatusSchema,
    version: z.number().int().positive(),
    created_by_membership_id: z.string().uuid(),
    updated_by_membership_id: z.string().uuid(),
    created_at: z.string(),
    updated_at: z.string(),
  })
  .strict();

export const questionListSchema = z
  .object({
    items: z.array(questionSchema),
    page: z
      .object({
        limit: z.number().int().positive(),
        offset: z.number().int().nonnegative(),
        has_more: z.boolean(),
      })
      .strict(),
  })
  .strict();

export type QuestionStatus = z.infer<typeof questionStatusSchema>;
export type Question = z.infer<typeof questionSchema>;
export type QuestionList = z.infer<typeof questionListSchema>;

export function isQuestionIdentifier(value: string): boolean {
  return questionIdentifierPattern.test(value);
}

export interface QuestionProblem {
  code: string;
  detail: string;
  requestId?: string;
}

export type QuestionResult<T> =
  | { ok: true; data: T }
  | { ok: false; status: number; problem: QuestionProblem };

export function questionProblem(value: unknown, fallback: string): QuestionProblem {
  if (typeof value !== "object" || value === null) {
    return { code: "QUESTION_REQUEST_FAILED", detail: fallback };
  }
  const body = value as Record<string, unknown>;
  return {
    code: typeof body.code === "string" ? body.code : "QUESTION_REQUEST_FAILED",
    detail: typeof body.detail === "string" ? body.detail : fallback,
    ...(typeof body.request_id === "string" ? { requestId: body.request_id } : {}),
  };
}
