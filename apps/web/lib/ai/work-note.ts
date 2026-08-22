export interface PreparedWorkNoteCandidate {
  client_id: string;
  execution_id: string;
  task_id: "ai.prepare_work_note";
  task_version: "1";
  output_hash: string;
  draft: string;
  suggested_follow_up: string;
  caveat: string | null;
  review_required: true;
  authoritative: false;
}

export interface AIWorkNoteProblem {
  code: string;
  detail: string;
  retryable: boolean;
  retry_after_seconds: number | null;
}

export type PrepareWorkNoteResponse =
  | {
      status: "PREPARED";
      execution_id: string;
      candidate: PreparedWorkNoteCandidate;
      problem: null;
    }
  | {
      status: "RESTRICTED" | "FAILED";
      execution_id: string;
      candidate: null;
      problem: AIWorkNoteProblem;
    };

export function isPrepareWorkNoteResponse(value: unknown): value is PrepareWorkNoteResponse {
  if (typeof value !== "object" || value === null) return false;
  const body = value as Record<string, unknown>;
  if (typeof body.execution_id !== "string") return false;
  if (body.status === "PREPARED") {
    if (typeof body.candidate !== "object" || body.candidate === null) return false;
    const candidate = body.candidate as Record<string, unknown>;
    return (
      candidate.task_id === "ai.prepare_work_note" &&
      candidate.task_version === "1" &&
      candidate.review_required === true &&
      candidate.authoritative === false &&
      typeof candidate.client_id === "string" &&
      typeof candidate.execution_id === "string" &&
      typeof candidate.output_hash === "string" &&
      typeof candidate.draft === "string" &&
      typeof candidate.suggested_follow_up === "string" &&
      (candidate.caveat === null || typeof candidate.caveat === "string")
    );
  }
  if (body.status !== "RESTRICTED" && body.status !== "FAILED") return false;
  if (typeof body.problem !== "object" || body.problem === null) return false;
  const problem = body.problem as Record<string, unknown>;
  return (
    typeof problem.code === "string" &&
    typeof problem.detail === "string" &&
    typeof problem.retryable === "boolean"
  );
}
