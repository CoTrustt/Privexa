import { type NextRequest } from "next/server";

import {
  forwardQuestionMutation,
  parseQuestionMutation,
  validateQuestionIdentifiers,
  validateQuestionOrigin,
} from "@/lib/questions/proxy";
import { updateQuestionMutationSchema } from "@/lib/questions/validation";

export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ clientId: string; questionId: string }> },
) {
  const originProblem = validateQuestionOrigin(request);
  if (originProblem) return originProblem;
  const { clientId, questionId } = await params;
  const identifierProblem = validateQuestionIdentifiers(clientId, questionId);
  if (identifierProblem) return identifierProblem;
  const parsed = await parseQuestionMutation(request, updateQuestionMutationSchema);
  if (!parsed.ok) return parsed.response;
  return forwardQuestionMutation({
    request,
    path: `/v1/clients/${encodeURIComponent(clientId)}/questions/${encodeURIComponent(questionId)}`,
    method: "PATCH",
    operation: "update",
    body: parsed.data,
  });
}
