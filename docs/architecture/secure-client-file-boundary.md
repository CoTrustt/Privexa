# Secure Client File Boundary

PBI-0.8 adds a backend-only file primitive. It does not add Evidence, OCR, extraction, search,
embeddings, LLM calls, agents, or a frontend.

## Security contract

`stored_files` is authoritative for file identity, Firm/Client ownership, lifecycle, integrity, and
sensitivity. Every row has `(firm_id, client_id)` referential integrity to its ClientWorkspace and
forced PostgreSQL RLS. File operations reuse the canonical `ExecutionContext` and the
`file.create`, `file.read`, or `file.delete` client-scoped permission.

Callers supply a `file_id`; they never supply a bucket or object key. Privexa derives immutable
locations centrally:

```text
staging/firms/{firm_id}/clients/{client_id}/files/{file_id}/upload
objects/firms/{firm_id}/clients/{client_id}/files/{file_id}/original
```

The configured bucket is private. Long-lived S3 credentials belong only to trusted backend
infrastructure. A future worker or AI tool must re-establish an authorized ExecutionContext and use
a specific `file_id`; it must not receive global bucket credentials.

## Lifecycle

An upload request creates `PENDING_UPLOAD` metadata and a short-lived, object-specific signed PUT.
The PUT is bound to content type, content length, SHA-256, metadata, and `If-None-Match: *`. On
completion, Privexa HEAD-verifies the staging object, copies it to the canonical immutable key,
HEAD-verifies the canonical object, and only then records `AVAILABLE`. Integrity failures become
`FAILED`. Repeated completion is safe.

Only `AVAILABLE` files receive a short-lived signed GET. Delete removes the canonical and staging
objects before recording the `DELETED` tombstone; provider failure leaves metadata unchanged so the
request can be retried. Already issued signed URLs cannot be revoked independently, so download TTLs
remain deliberately short and deletion removes the object immediately.

Client files have a `SENSITIVE` floor and may be explicitly raised to `RESTRICTED`. There is no
automatic content classification.

## Local development

Copy the object-storage values from `.env.example` into `.env`, using local-only credentials, then
run:

```bash
docker compose up -d --wait postgres minio
docker compose run --rm minio-init
cd apps/api
set -a && source ../../.env && set +a
uv run alembic upgrade head
uv run uvicorn privexa_api.asgi:app --reload
```

The init container deterministically creates private `privexa-development` and `privexa-test`
buckets, configures one-day cleanup for abandoned `staging/` objects, and provisions a separate
application identity limited to object GET, PUT, and DELETE. MinIO root credentials are used only
by provisioning; the API must use the distinct `OBJECT_STORAGE_ACCESS_KEY` and
`OBJECT_STORAGE_SECRET_KEY`. Local browser CORS is limited by MinIO to `PRIVEXA_WEB_ORIGIN`. The
MinIO console is available on port 9001 for local diagnostics only.

Run the automated real-storage proof with:

```bash
cd apps/api
set -a && source ../../.env && set +a
PRIVEXA_ENVIRONMENT=test OBJECT_STORAGE_BUCKET=privexa-test \
  uv run pytest tests/test_file_boundary_storage_integration.py -q
```

Production uses a private S3-compatible bucket provisioned outside application startup, HTTPS,
least-privilege workload credentials, provider-managed encryption at rest, and the provider's audit
controls. Local MinIO preserves the S3 authorization/API shape but is not evidence of equivalent
production encryption or durability.

## API surface

```text
POST   /v1/clients/{client_id}/files/uploads
POST   /v1/clients/{client_id}/files/{file_id}/complete
GET    /v1/clients/{client_id}/files/{file_id}
POST   /v1/clients/{client_id}/files/{file_id}/download
DELETE /v1/clients/{client_id}/files/{file_id}
```

Responses intentionally omit bucket names and object keys. Signed URLs use `Cache-Control:
no-store` and are never written to the database or application logs.
