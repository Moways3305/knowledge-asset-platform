import { describe, it, expect } from "vitest";
import type { AuthMeVM } from "../api/auth";
import { deriveCapabilities, can } from "./permissions";

function me(over: Partial<AuthMeVM> = {}): AuthMeVM {
  return {
    userId: "u1",
    name: "Tester",
    email: "t@dev.local",
    companyRoles: [],
    isBusinessUser: false,
    canDiscoverL5: false,
    projects: [],
    ...over,
  };
}

describe("deriveCapabilities", () => {
  it("treats null identity (anonymous) as having no capabilities", () => {
    const c = deriveCapabilities(null);
    expect(c).toEqual({
      isAdmin: false,
      isBoss: false,
      isConsultingDirector: false,
      isBusinessUser: false,
      isGovernance: false,
      hasProject: false,
      isProjectManager: false,
    });
  });

  it("marks pure admin without business roles", () => {
    const c = deriveCapabilities(me({ companyRoles: ["admin"], isBusinessUser: false }));
    expect(c.isAdmin).toBe(true);
    expect(c.isBusinessUser).toBe(false);
    expect(c.isGovernance).toBe(false);
  });

  it("marks governance from canDiscoverL5 (boss / consulting_director)", () => {
    const c = deriveCapabilities(
      me({ companyRoles: ["boss"], isBusinessUser: true, canDiscoverL5: true }),
    );
    expect(c.isGovernance).toBe(true);
    expect(c.isBoss).toBe(true);
    expect(c.isConsultingDirector).toBe(false);
    expect(c.isBusinessUser).toBe(true);
    expect(c.isAdmin).toBe(false);
  });

  it("distinguishes consulting director from Boss for governance writes", () => {
    const c = deriveCapabilities(
      me({ companyRoles: ["consulting_director"], isBusinessUser: true, canDiscoverL5: true }),
    );
    expect(c.isBoss).toBe(false);
    expect(c.isConsultingDirector).toBe(true);
  });

  it("detects project membership and project manager role", () => {
    const c = deriveCapabilities(
      me({
        isBusinessUser: true,
        projects: [{ projectId: "p1", projectName: "P1", projectRole: "project_manager" }],
      }),
    );
    expect(c.hasProject).toBe(true);
    expect(c.isProjectManager).toBe(true);
  });

  it("a plain consultant project member is not a project manager", () => {
    const c = deriveCapabilities(
      me({
        isBusinessUser: true,
        projects: [{ projectId: "p1", projectName: "P1", projectRole: "consultant" }],
      }),
    );
    expect(c.hasProject).toBe(true);
    expect(c.isProjectManager).toBe(false);
  });
});

describe("can (nav / route capability predicates)", () => {
  const anon = deriveCapabilities(null);
  const admin = deriveCapabilities(me({ companyRoles: ["admin"] }));
  const consultant = deriveCapabilities(me({ companyRoles: ["consultant"], isBusinessUser: true }));
  const governance = deriveCapabilities(
    me({ companyRoles: ["boss"], isBusinessUser: true, canDiscoverL5: true }),
  );

  it("shows business knowledge entries to business users, not pure admin", () => {
    expect(can.viewKnowledge(consultant)).toBe(true);
    expect(can.viewKnowledge(admin)).toBe(false);
    expect(can.viewKnowledge(anon)).toBe(false);
  });

  it("restricts model config to admin only", () => {
    expect(can.viewModels(admin)).toBe(true);
    expect(can.viewModels(governance)).toBe(false);
    expect(can.viewModels(consultant)).toBe(false);
  });

  it("restricts login risk control to admin only", () => {
    expect(can.viewAuthSecurity(admin)).toBe(true);
    expect(can.viewAuthSecurity(governance)).toBe(false);
    expect(can.viewAuthSecurity(consultant)).toBe(false);
  });

  it("restricts alert settings to admin only", () => {
    expect(can.viewAlerts(admin)).toBe(true);
    expect(can.viewAlerts(governance)).toBe(false);
  });

  it("shows shared system views to admin or governance", () => {
    for (const pred of [
      can.viewAudit,
      can.viewIngestAdmin,
      can.viewPermissions,
      can.viewWecomScan,
    ]) {
      expect(pred(admin)).toBe(true);
      expect(pred(governance)).toBe(true);
      expect(pred(consultant)).toBe(false);
    }
  });

  it("keeps people governance hidden from pure admin", () => {
    expect(can.viewPeople(admin)).toBe(false);
    expect(can.viewPeople(governance)).toBe(true);
    expect(can.viewPeople(consultant)).toBe(false);
  });

  it("shows project board only to active project members", () => {
    const member = deriveCapabilities(
      me({
        isBusinessUser: true,
        projects: [{ projectId: "p1", projectName: "P1", projectRole: "consultant" }],
      }),
    );
    expect(can.viewProject(member)).toBe(true);
    expect(can.viewProject(governance)).toBe(false);
    expect(can.viewProject(consultant)).toBe(false);
  });

  it("always allows home and help", () => {
    expect(can.viewHome(anon)).toBe(true);
    expect(can.viewHelp(anon)).toBe(true);
  });
});
