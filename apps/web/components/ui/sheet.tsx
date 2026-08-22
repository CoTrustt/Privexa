"use client";

import type { ComponentPropsWithoutRef } from "react";

import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { cn } from "@/lib/ui/cn";

export { Dialog as Sheet, DialogClose as SheetClose, DialogDescription as SheetDescription, DialogTitle as SheetTitle, DialogTrigger as SheetTrigger };

export function SheetContent({
  className,
  ...props
}: ComponentPropsWithoutRef<typeof DialogContent>) {
  return (
    <DialogContent
      className={cn(
        "left-auto right-0 top-0 h-dvh max-h-none w-[min(36rem,100vw)] translate-x-0 translate-y-0 rounded-none border-y-0 border-r-0 p-0 shadow-[0_20px_64px_rgb(24_24_27_/_16%)]",
        className,
      )}
      {...props}
    />
  );
}
