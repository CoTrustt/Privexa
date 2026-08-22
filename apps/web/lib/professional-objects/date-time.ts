const presentationLocale = "en-IN";
const presentationTimeZone = "Asia/Kolkata";

const dateTimeFormatter = new Intl.DateTimeFormat(presentationLocale, {
  day: "2-digit",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  timeZone: presentationTimeZone,
  timeZoneName: "short",
});

export interface FormattedProfessionalTimestamp {
  dateTime: string;
  label: string;
}

export function formatProfessionalTimestamp(
  value: string | null | undefined,
): FormattedProfessionalTimestamp | null {
  if (!value) return null;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return null;
  return {
    dateTime: parsed.toISOString(),
    label: dateTimeFormatter.format(parsed),
  };
}
