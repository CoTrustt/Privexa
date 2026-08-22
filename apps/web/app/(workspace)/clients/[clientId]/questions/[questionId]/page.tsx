import { notFound, redirect } from "next/navigation";

import { QuestionDetailController } from "@/components/questions/question-detail-controller";
import {
  BlockingProfessionalObjectError,
  ProfessionalObjectPermissionDenied,
} from "@/components/professional-object/object-states";
import { getServerApplicationContext } from "@/lib/application-context/server";
import { questionCapabilities } from "@/lib/application-context/types";
import { getQuestion } from "@/lib/questions/server";
import { questionPageViewModel } from "@/lib/questions/presenter";

export default async function QuestionPage({
  params,
}: {
  params: Promise<{ clientId: string; questionId: string }>;
}) {
  const { clientId, questionId } = await params;
  const contextResult = await getServerApplicationContext();
  if (!contextResult.ok) {
    if (contextResult.status === 401) redirect("/sign-in?reason=SESSION_EXPIRED");
    return (
      <BlockingProfessionalObjectError
        problem={{ code: contextResult.problem.code, detail: contextResult.problem.detail }}
      />
    );
  }
  const client = contextResult.context.active_client;
  if (!client || client.id !== clientId) notFound();

  const result = await getQuestion(clientId, questionId);
  if (!result.ok) {
    if (result.status === 401) redirect("/sign-in?reason=SESSION_EXPIRED");
    if (result.status === 404 || result.status === 400) notFound();
    if (result.status === 403) return <ProfessionalObjectPermissionDenied />;
    return <BlockingProfessionalObjectError problem={result.problem} />;
  }
  if (result.data.client_id !== clientId) notFound();
  const capabilities = questionCapabilities(contextResult.context);
  const page = questionPageViewModel({
    question: result.data,
    firmId: contextResult.context.firm.id,
    client,
    canUpdate: capabilities.can_update,
  });
  return (
    <QuestionDetailController
      question={result.data}
      page={page}
      firmId={contextResult.context.firm.id}
      clientId={clientId}
    />
  );
}
