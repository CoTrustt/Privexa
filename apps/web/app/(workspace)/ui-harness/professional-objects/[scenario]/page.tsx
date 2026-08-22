import { notFound } from "next/navigation";

import { ProfessionalObjectScenarioHarness } from "@/components/professional-object/professional-object-scenario-harness";
import {
  isProfessionalObjectScenarioName,
  professionalObjectScenarios,
} from "@/fixtures/professional-object-scenarios";
import { getServerApplicationContext } from "@/lib/application-context/server";

export default async function ProfessionalObjectHarnessPage({
  params,
}: {
  params: Promise<{ scenario: string }>;
}) {
  if (
    process.env.NODE_ENV === "production" ||
    process.env.PRIVEXA_UI_HARNESS_ENABLED !== "true"
  ) {
    notFound();
  }

  const [{ scenario: scenarioName }, contextResult] = await Promise.all([
    params,
    getServerApplicationContext(),
  ]);
  if (
    !isProfessionalObjectScenarioName(scenarioName) ||
    !contextResult.ok ||
    !contextResult.context.active_client
  ) {
    notFound();
  }

  return (
    <ProfessionalObjectScenarioHarness
      scenario={professionalObjectScenarios[scenarioName]}
      activeFirmId={contextResult.context.firm.id}
      activeWorkspace={{
        id: contextResult.context.active_client.id,
        name: contextResult.context.active_client.display_name,
      }}
    />
  );
}
