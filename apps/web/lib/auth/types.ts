export type FirmRole =
  | "FIRM_OWNER"
  | "FIRM_ADMIN"
  | "CONSULTANT"
  | "REVIEWER"
  | "READ_ONLY";

export type PrivexaSession = {
  user_id: string;
  membership_id: string;
  firm_id: string;
  role: FirmRole;
  display_name: string;
  firm_name: string;
};

export type AuthenticationProblem = {
  code: string;
  detail: string;
  request_id?: string;
};

export type SessionResult =
  | { ok: true; session: PrivexaSession }
  | { ok: false; status: number; problem: AuthenticationProblem };
