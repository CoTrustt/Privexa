import { describe, expect, it } from "vitest";

import {
  isSafeInternalHref,
  PROFESSIONAL_OBJECT_TYPE_DEFINITIONS,
  professionalObjectHref,
} from "./object-types";
import { PROFESSIONAL_OBJECT_TYPES } from "./view-model";

describe("professional object presentation definitions", () => {
  it("defines a readable label and route segment for every foundational object type", () => {
    expect(Object.keys(PROFESSIONAL_OBJECT_TYPE_DEFINITIONS).sort()).toEqual(
      [...PROFESSIONAL_OBJECT_TYPES].sort(),
    );
    for (const definition of Object.values(PROFESSIONAL_OBJECT_TYPE_DEFINITIONS)) {
      expect(definition.label).not.toHaveLength(0);
      expect(definition.pluralRouteSegment).toMatch(/^[a-z-]+$/);
    }
  });

  it("keeps client and object identifiers encoded in generated internal routes", () => {
    expect(professionalObjectHref("client/one", "evidence", "object?one")).toBe(
      "/clients/client%2Fone/evidence/object%3Fone",
    );
  });

  it("rejects external, protocol-relative, script, and backslash navigation targets", () => {
    expect(isSafeInternalHref("/clients/client-1/evidence/object-1")).toBe(true);
    expect(isSafeInternalHref("https://attacker.example/record")).toBe(false);
    expect(isSafeInternalHref("//attacker.example/record")).toBe(false);
    expect(isSafeInternalHref("javascript:alert(1)")).toBe(false);
    expect(isSafeInternalHref("/clients\\attacker.example")).toBe(false);
  });
});
