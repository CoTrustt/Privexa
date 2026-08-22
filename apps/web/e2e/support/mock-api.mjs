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
};

function sendJson(response, status, body) {
  response.writeHead(status, {
    "cache-control": "no-store",
    "content-type": "application/json; charset=utf-8",
  });
  response.end(JSON.stringify(body));
}

const server = createServer((request, response) => {
  if (request.url === "/health") {
    response.writeHead(204);
    response.end();
    return;
  }

  if (request.method === "GET" && request.url === "/v1/application-context") {
    if (!request.headers.cookie?.split("; ").includes(sessionCookie)) {
      sendJson(response, 401, {
        code: "AUTHENTICATION_REQUIRED",
        detail: "A local E2E session is required.",
      });
      return;
    }
    sendJson(response, 200, applicationContext);
    return;
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
