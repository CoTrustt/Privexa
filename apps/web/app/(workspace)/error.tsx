"use client";

import { useEffect } from "react";

import { WorkspaceState } from "@/components/workspace/workspace-state";

export default function WorkspaceError({ error }: { error: Error & { digest?: string } }) {
  useEffect(() => {
    console.error("Workspace rendering failed", error.digest ?? error.name);
  }, [error]);

  return <WorkspaceState kind="temporary" />;
}
