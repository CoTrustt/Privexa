import { Circle, CircleAlert, CircleCheck, CircleDot, OctagonAlert } from "lucide-react";

import type {
  ProfessionalObjectStatus,
  ProfessionalObjectStatusTone,
} from "@/lib/professional-objects/view-model";
import { cn } from "@/lib/ui/cn";

const toneClasses: Record<ProfessionalObjectStatusTone, string> = {
  neutral: "bg-[var(--pv-surface-strong)] text-[var(--pv-text-muted)]",
  information: "bg-[var(--pv-accent-soft)] text-[var(--pv-accent-text)]",
  attention: "bg-[var(--pv-attention-soft)] text-[var(--pv-attention)]",
  success: "bg-[var(--pv-success-soft)] text-[var(--pv-success)]",
  critical: "bg-[var(--pv-critical-soft)] text-[var(--pv-critical)]",
};

const toneIcons = {
  neutral: Circle,
  information: CircleDot,
  attention: CircleAlert,
  success: CircleCheck,
  critical: OctagonAlert,
} satisfies Record<ProfessionalObjectStatusTone, typeof Circle>;

export function ProfessionalObjectStatusLabel({
  status,
  compact = false,
  className,
}: {
  status: ProfessionalObjectStatus;
  compact?: boolean;
  className?: string;
}) {
  const Icon = toneIcons[status.tone] ?? Circle;
  return (
    <span
      className={cn(
        "inline-flex w-fit items-center gap-1.5 rounded-full font-semibold",
        compact ? "px-2 py-1 text-[11px] leading-4" : "px-2.5 py-1.5 text-xs leading-4",
        toneClasses[status.tone] ?? toneClasses.neutral,
        className,
      )}
      aria-label={`Status: ${status.label}`}
      title={status.description}
    >
      <Icon className="size-3.5 shrink-0" aria-hidden />
      <span>{status.label}</span>
    </span>
  );
}
