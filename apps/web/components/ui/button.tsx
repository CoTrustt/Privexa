import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { forwardRef, type ButtonHTMLAttributes } from "react";

import { cn } from "@/lib/ui/cn";

export const buttonVariants = cva(
  "inline-flex min-h-11 items-center justify-center gap-2 rounded-[var(--pv-radius-control)] px-4 text-sm font-semibold transition-colors duration-150 motion-reduce:transition-none disabled:cursor-not-allowed disabled:opacity-55",
  {
    variants: {
      variant: {
        primary: "bg-[var(--pv-accent)] text-white hover:bg-[var(--pv-accent-hover)]",
        secondary:
          "border border-[var(--pv-border)] bg-[var(--pv-surface)] text-[var(--pv-text-strong)] hover:bg-[var(--pv-surface-strong)]",
        tertiary:
          "bg-transparent px-3 text-[var(--pv-text-muted)] hover:bg-[var(--pv-surface-strong)] hover:text-[var(--pv-text-strong)]",
        destructive:
          "bg-[var(--pv-critical)] text-white hover:brightness-95",
      },
      size: {
        default: "min-h-11",
        compact: "min-h-10 px-3 text-[13px]",
        icon: "size-11 min-h-0 p-0",
      },
    },
    defaultVariants: { variant: "secondary", size: "default" },
  },
);

export interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ asChild = false, className, variant, size, type = "button", ...props }, ref) => {
    const Component = asChild ? Slot : "button";
    return (
      <Component
        ref={ref}
        type={asChild ? undefined : type}
        className={cn(buttonVariants({ variant, size }), className)}
        {...props}
      />
    );
  },
);
Button.displayName = "Button";
