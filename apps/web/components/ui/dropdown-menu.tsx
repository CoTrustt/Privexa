"use client";

import * as DropdownMenuPrimitive from "@radix-ui/react-dropdown-menu";
import { Check } from "lucide-react";
import { forwardRef, type ComponentPropsWithoutRef, type ElementRef } from "react";

import { cn } from "@/lib/ui/cn";

export const DropdownMenu = DropdownMenuPrimitive.Root;
export const DropdownMenuTrigger = DropdownMenuPrimitive.Trigger;

export const DropdownMenuContent = forwardRef<
  ElementRef<typeof DropdownMenuPrimitive.Content>,
  ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.Content>
>(({ className, sideOffset = 8, ...props }, ref) => (
  <DropdownMenuPrimitive.Portal>
    <DropdownMenuPrimitive.Content
      ref={ref}
      sideOffset={sideOffset}
      collisionPadding={16}
      className={cn(
        "z-60 min-w-52 overflow-hidden rounded-[var(--pv-radius-card)] border border-[var(--pv-border)] bg-[var(--pv-surface)] p-1.5 shadow-[0_16px_48px_rgb(24_24_27_/_10%)]",
        className,
      )}
      {...props}
    />
  </DropdownMenuPrimitive.Portal>
));
DropdownMenuContent.displayName = "DropdownMenuContent";

export const DropdownMenuItem = forwardRef<
  ElementRef<typeof DropdownMenuPrimitive.Item>,
  ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.Item> & {
    destructive?: boolean;
    selected?: boolean;
  }
>(({ children, className, destructive = false, selected = false, ...props }, ref) => (
  <DropdownMenuPrimitive.Item
    ref={ref}
    className={cn(
      "relative flex min-h-10 cursor-default select-none items-center gap-2 rounded-[8px] px-3 text-[13px] outline-none data-[disabled]:opacity-50 data-[highlighted]:bg-[var(--pv-surface-strong)]",
      destructive ? "text-[var(--pv-critical)]" : "text-[var(--pv-text)]",
      className,
    )}
    {...props}
  >
    {children}
    {selected ? <Check className="ml-auto size-4" aria-hidden /> : null}
  </DropdownMenuPrimitive.Item>
));
DropdownMenuItem.displayName = "DropdownMenuItem";

export const DropdownMenuSeparator = DropdownMenuPrimitive.Separator;
