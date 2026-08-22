import { createServer } from "node:http";

const host = "127.0.0.1";
const port = 4010;
const sessionCookie = "stytch_session=e2e-session";

const applicationContext = {
  state: "ACTIVE_CLIENT",
  user: {
    id: "90000000-0000-4000-8000-000000000001",
    display_name: "Asha Rao",
  },
  firm: {
    id: "90000000-0000-4000-8000-000000000002",
    display_name: "Pai Privacy Consulting",
  },
  active_client: {
    id: "90000000-0000-4000-8000-000000000003",
    display_name:
      "Apollo Finance Consumer Lending and Digital Support Services — India Client Workspace",
  },
  authorised_clients: [
    {
      id: "90000000-0000-4000-8000-000000000003",
      display_name:
        "Apollo Finance Consumer Lending and Digital Support Services — India Client Workspace",
    },
  ],
  question_capabilities: { can_create: true, can_update: true },
};

const questions = new Map();
let questionSequence = 1;
let failNextQuestionMutation = false;

function nextQuestionId() {
  const suffix = String(questionSequence++).padStart(12, "0");
  return `91000000-0000-4000-8000-${suffix}`;
}

function readBody(request) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    request.on("data", (chunk) => chunks.push(chunk));
    request.on("end", () => {
      try {
        resolve(JSON.parse(Buffer.concat(chunks).toString("utf8")));
      } catch (error) {
        reject(error);
      }
    });
    request.on("error", reject);
  });
}

function authenticated(request, response) {
  if (request.headers.cookie?.split("; ").includes(sessionCookie)) return true;
  sendJson(response, 401, {
    code: "AUTHENTICATION_REQUIRED",
    detail: "A local E2E session is required.",
  });
  return false;
}

function questionPath(requestUrl) {
  const url = new URL(requestUrl, `http://${host}:${port}`);
  const match = url.pathname.match(
    /^\/v1\/clients\/([^/]+)\/questions(?:\/([^/]+))?(?:\/(resolve|close|reopen))?$/,
  );
  return match
    ? { url, clientId: match[1], questionId: match[2] ?? null, transition: match[3] ?? null }
    : null;
}

function sendJson(response, status, body) {
  response.writeHead(status, {
    "cache-control": "no-store",
    "content-type": "application/json; charset=utf-8",
  });
  response.end(JSON.stringify(body));
}

const server = createServer(async (request, response) => {
  if (request.url === "/health") {
    response.writeHead(204);
    response.end();
    return;
  }

  if (request.method === "GET" && request.url === "/v1/application-context") {
    if (!authenticated(request, response)) return;
    sendJson(response, 200, applicationContext);
    return;
  }

  if (request.method === "POST" && request.url === "/__test__/reset-questions") {
    questions.clear();
    questionSequence = 1;
    failNextQuestionMutation = false;
    response.writeHead(204);
    response.end();
    return;
  }

  if (request.method === "POST" && request.url === "/__test__/fail-next-question-mutation") {
    failNextQuestionMutation = true;
    response.writeHead(204);
    response.end();
    return;
  }

  const route = questionPath(request.url ?? "");
  if (route) {
    if (!authenticated(request, response)) return;
    if (route.clientId !== applicationContext.active_client.id) {
      sendJson(response, 404, {
        code: "RESOURCE_NOT_FOUND",
        detail: "The requested resource could not be found.",
      });
      return;
    }

    if (
      failNextQuestionMutation &&
      (request.method === "POST" || request.method === "PATCH")
    ) {
      failNextQuestionMutation = false;
      sendJson(response, 503, {
        code: "QUESTION_SERVICE_UNAVAILABLE",
        detail: "The question could not be saved right now. Your work is unchanged.",
      });
      return;
    }

    if (request.method === "GET" && !route.questionId) {
      const status = route.url.searchParams.get("status");
      const limit = Number(route.url.searchParams.get("limit") ?? 50);
      const offset = Number(route.url.searchParams.get("offset") ?? 0);
      const available = [...questions.values()]
        .filter((question) => !status || question.status === status)
        .sort((left, right) => right.created_at.localeCompare(left.created_at));
      sendJson(response, 200, {
        items: available.slice(offset, offset + limit),
        page: { limit, offset, has_more: available.length > offset + limit },
      });
      return;
    }

    if (request.method === "POST" && !route.questionId) {
      let body;
      try {
        body = await readBody(request);
      } catch {
        sendJson(response, 422, { code: "REQUEST_VALIDATION_FAILED", detail: "Review the question and try again." });
        return;
      }
      const now = new Date().toISOString();
      const question = {
        id: nextQuestionId(),
        client_id: route.clientId,
        title: body.title,
        question_text: body.question_text,
        context: body.context ?? null,
        status: "OPEN",
        version: 1,
        created_by_membership_id: "92000000-0000-4000-8000-000000000001",
        updated_by_membership_id: "92000000-0000-4000-8000-000000000001",
        created_at: now,
        updated_at: now,
      };
      questions.set(question.id, question);
      sendJson(response, 201, question);
      return;
    }

    const question = route.questionId ? questions.get(route.questionId) : null;
    if (!question) {
      sendJson(response, 404, { code: "RESOURCE_NOT_FOUND", detail: "The requested resource could not be found." });
      return;
    }
    if (request.method === "GET" && !route.transition) {
      sendJson(response, 200, question);
      return;
    }

    let body;
    try {
      body = await readBody(request);
    } catch {
      sendJson(response, 422, { code: "REQUEST_VALIDATION_FAILED", detail: "Review the question and try again." });
      return;
    }
    if (body.expected_version !== question.version) {
      sendJson(response, 409, { code: "VERSION_CONFLICT", detail: "The question changed. Refresh and try again." });
      return;
    }

    if (request.method === "PATCH" && !route.transition) {
      if (question.status !== "OPEN") {
        sendJson(response, 409, { code: "LIFECYCLE_CONFLICT", detail: "Reopen the question before editing it." });
        return;
      }
      Object.assign(question, {
        title: body.title,
        question_text: body.question_text,
        context: body.context ?? null,
        version: question.version + 1,
        updated_at: new Date().toISOString(),
      });
      sendJson(response, 200, question);
      return;
    }

    if (request.method === "POST" && route.transition) {
      const allowed =
        (route.transition === "resolve" && question.status === "OPEN") ||
        (route.transition === "close" && question.status === "RESOLVED") ||
        (route.transition === "reopen" && (question.status === "RESOLVED" || question.status === "CLOSED"));
      if (!allowed) {
        sendJson(response, 409, { code: "LIFECYCLE_CONFLICT", detail: "That status change is not available." });
        return;
      }
      question.status = route.transition === "resolve" ? "RESOLVED" : route.transition === "close" ? "CLOSED" : "OPEN";
      question.version += 1;
      question.updated_at = new Date().toISOString();
      sendJson(response, 200, question);
      return;
    }
  }

  sendJson(response, 404, {
    code: "NOT_FOUND",
    detail: "The local E2E endpoint does not exist.",
  });
});

server.listen(port, host);

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => server.close(() => process.exit(0)));
}
