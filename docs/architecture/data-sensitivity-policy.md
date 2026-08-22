# Data Sensitivity Policy

Privexa uses one small, provider-neutral sensitivity vocabulary:

```text
STANDARD < SENSITIVE < RESTRICTED
```

The numeric severity ranks are internal deterministic policy details. Serialized values remain the
three names above. Sensitivity does not grant access; authentication, application authorization,
tenant scope, and PostgreSQL RLS remain independent controls.

## Core invariant

Derived information may retain or increase source sensitivity, but normal application processing
must never reduce it automatically. `SensitivityPolicy.classify_derived(...)` takes the most
restrictive source, inherited, and declared level. An explicit declared value below that floor is a
policy violation. A derived operation with no sources fails closed.

`SensitivityPolicy.classify_new(...)` applies `STANDARD` only when a genuinely new independent
object has no declared or inherited classification. Missing or invalid metadata on an existing
protected object must not be repaired by defaulting it to `STANDARD`.

## Execution context

Protected web requests begin with an immutable, trusted `ExecutionContext` whose
`effective_sensitivity` is `STANDARD`. After loading protected information, application services use:

```python
restricted_context = context.with_minimum_sensitivity(
    SensitivityLevel.RESTRICTED,
)
```

The method returns the existing context when it is already equally or more restrictive. Otherwise
it returns a new frozen trusted context with identical identity, tenant, authorization, origin, and
correlation fields. Directly constructed or deserialized contexts cannot use this trusted path.

## Persistence and extension points

Build 0 does not yet contain an information-bearing document, evidence, report, or generated-output
entity, so PBI-0.7 adds no sensitivity column or migration. Future protected content should persist
its effective sensitivity as a non-null string-backed `SensitivityLevel`, use an allowed-values
`CHECK`, and resolve inherited/source restrictions before repository writes.

Sensitivity levels do not encode provider eligibility, redaction, export, residency, retention, or
tenant configuration. Future AI and data-handling policy will consume `effective_sensitivity` along
with Firm policy. LLMs and agents may consume that decision but cannot author or downgrade it. A
future human reclassification workflow must be separately authorized and audited; PBI-0.7 exposes
no downgrade or unrestricted setter.
