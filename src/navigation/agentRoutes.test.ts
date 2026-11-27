import { describe, expect, it } from "vitest";
import {
  legacyMaintenanceAgentDestination,
  maintenancePanelHref,
  MAINTENANCE_AGENT_PATH,
  AI_WORKSPACE_PATH,
} from "./agentRoutes";

describe("knowledge maintenance destinations", () => {
  it("retains historical reminder queries and fragments exactly on redirect", () => {
    const search = "?library=project%3Aalpha&target_id=digest-1&view=mine&tab=issues&session=one";
    expect(legacyMaintenanceAgentDestination(search, "#issue-7")).toBe(
      `${MAINTENANCE_AGENT_PATH}${search}#issue-7`,
    );
  });

  it("changes business tabs without discarding workspace or reminder context", () => {
    const url = new URL(
      maintenancePanelHref(
        "?library=company&session=one&tab=issues&target_id=digest-1&page=2",
        { tab: "runs", page: null },
        "#selected",
      ),
      "https://kap.example",
    );
    expect(url.pathname).toBe(AI_WORKSPACE_PATH);
    expect(Object.fromEntries(url.searchParams)).toEqual({
      library: "company",
      session: "one",
      agent: "knowledge-maintenance",
      panel: "runs",
      target_id: "digest-1",
    });
    expect(url.hash).toBe("#selected");
  });

  it("only clears reminder restrictions when explicitly requesting all library issues", () => {
    const url = new URL(
      maintenancePanelHref("?session=one&target_id=digest-1&view=mine&mine=true&page=3", {
        library: "project:alpha",
        tab: "issues",
        target_id: null,
        view: null,
        mine: null,
        page: null,
      }),
      "https://kap.example",
    );
    expect(Object.fromEntries(url.searchParams)).toEqual({
      session: "one",
      library: "project:alpha",
      agent: "knowledge-maintenance",
      panel: "issues",
    });
  });
});
