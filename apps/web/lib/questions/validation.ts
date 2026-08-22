import { z } from "zod";

export const QUESTION_TITLE_MAX_LENGTH = 255;
export const QUESTION_TEXT_MAX_LENGTH = 20_000;
export const QUESTION_CONTEXT_MAX_LENGTH = 50_000;

const codePointLength = (value: string) => Array.from(value).length;

function authoredText(label: string, maximum: number) {
  return z.string().superRefine((value, context) => {
    if (!value.trim()) {
      context.addIssue({
        code: "custom",
        message: `${label} cannot be empty.`,
      });
    } else if (codePointLength(value) > maximum) {
      context.addIssue({
        code: "custom",
        message: `${label} must be ${maximum.toLocaleString("en-IN")} characters or fewer.`,
      });
    }
  });
}

export const questionDraftSchema = z
  .object({
    question_text: authoredText("Question", QUESTION_TEXT_MAX_LENGTH),
    context: z.string().superRefine((value, context) => {
      if (codePointLength(value) > QUESTION_CONTEXT_MAX_LENGTH) {
        context.addIssue({
          code: "custom",
          message: `Context must be ${QUESTION_CONTEXT_MAX_LENGTH.toLocaleString("en-IN")} characters or fewer.`,
        });
      }
    }),
  })
  .strict();

export const createQuestionMutationSchema = questionDraftSchema;

export const updateQuestionMutationSchema = z
  .object({
    expected_version: z.number().int().positive(),
    title: authoredText("Title", QUESTION_TITLE_MAX_LENGTH),
    question_text: authoredText("Question", QUESTION_TEXT_MAX_LENGTH),
    context: z.union([
      authoredText("Context", QUESTION_CONTEXT_MAX_LENGTH),
      z.null(),
    ]),
  })
  .strict();

export const lifecycleQuestionMutationSchema = z
  .object({ expected_version: z.number().int().positive() })
  .strict();

export type QuestionDraft = z.infer<typeof questionDraftSchema>;

export function normalizeQuestionContext(value: string): string | null {
  return value.trim() ? value : null;
}

export function deriveQuestionTitle(questionText: string): string {
  const firstMeaningfulLine = questionText
    .split(/\r?\n/u)
    .find((line) => line.trim().length > 0)
    ?.trim();
  return Array.from(firstMeaningfulLine ?? questionText.trim())
    .slice(0, QUESTION_TITLE_MAX_LENGTH)
    .join("");
}

export function titleForEditedQuestion(
  currentTitle: string,
  currentQuestionText: string,
  nextQuestionText: string,
): string {
  return currentTitle === deriveQuestionTitle(currentQuestionText)
    ? deriveQuestionTitle(nextQuestionText)
    : currentTitle;
}
