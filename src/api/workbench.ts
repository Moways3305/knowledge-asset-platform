import type { WorkbenchOverviewDTO } from "../types/workbench";
import { apiGet } from "./http";

export function fetchWorkbenchOverview(signal?: AbortSignal): Promise<WorkbenchOverviewDTO> {
  return apiGet<WorkbenchOverviewDTO>("/api/v1/workbench/overview", signal);
}
