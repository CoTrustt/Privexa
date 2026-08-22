import { type NextRequest, NextResponse } from "next/server";

import {
  forwardQuestionMutation,
  parseQuestionMutation,
  validateQuestionIdentifiers,
  validateQuestionOrigin,
} from "@/lib/questions/proxy";
import { lifecycleQuestionMutationSchema } from "@/lib/questions/validation";

const transitions = ["resolve", "close", "reopen"] as const;
type Transition = (typeof transitions)[number];

function isTransition(value: string): value is Transition {
  return transitions.some((transition) => transition === value);
}

export async function POST(
  request: NextRequest,
  {
    params,
  }: { params: Promise<{ clientId: string; questionId: string; transition: string }> },
) {
  const originProblem = validateQuestionOrigin(request);
  if (originProblem) return originProblem;
  const { clientId, questionId, transition } = await params;
  const identifierProblem = validateQuestionIdentifiers(clientId, questionId);
  if (identifierProblem) return identifierProblem;
  if (!isTransition(transition)) {
    return NextResponse.json(
      { code: "INVALID_TRANSITION", detail: "That question action is not available." },
      { status: 400, headers: { "Cache-Control": "no-store" } },
    );
  }
  const parsed = await parseQuestionMutation(request, lifecycleQuestionMutationSchema);
  if (!parsed.ok) return parsed.response;
  return forwardQuestionMutation({
    request,
    path: `/v1/clients/${encodeURIComponent(clientId)}/questions/${encodeURIComponent(questionId)}/${transition}`,
    method: "POST",
    operation: transition,
    body: parsed.data,
  });
}
