import type { WorkbenchOverviewDTO } from "../types/workbench";
import { apiGet } from "./http";

export function fetchWorkbenchOverview(): Promise<WorkbenchOverviewDTO> {
  return apiGet<WorkbenchOverviewDTO>("/api/v1/workbench/overview");
}
