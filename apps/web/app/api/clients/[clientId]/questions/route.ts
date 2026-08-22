import { type NextRequest } from "next/server";

import {
  forwardQuestionMutation,
  parseQuestionMutation,
  validateQuestionIdentifiers,
  validateQuestionOrigin,
} from "@/lib/questions/proxy";
import {
  createQuestionMutationSchema,
  deriveQuestionTitle,
  normalizeQuestionContext,
} from "@/lib/questions/validation";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ clientId: string }> },
) {
  const originProblem = validateQuestionOrigin(request);
  if (originProblem) return originProblem;
  const { clientId } = await params;
  const identifierProblem = validateQuestionIdentifiers(clientId);
  if (identifierProblem) return identifierProblem;
  const parsed = await parseQuestionMutation(request, createQuestionMutationSchema);
  if (!parsed.ok) return parsed.response;
  return forwardQuestionMutation({
    request,
    path: `/v1/clients/${encodeURIComponent(clientId)}/questions`,
    method: "POST",
    operation: "create",
    body: {
      title: deriveQuestionTitle(parsed.data.question_text),
      question_text: parsed.data.question_text,
      context: normalizeQuestionContext(parsed.data.context),
    },
  });
}
