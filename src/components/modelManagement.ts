import type { Ref } from "react";

export type ModelTestNotice = { tone: "busy" | "success" | "danger"; message: string };
export interface ModelManagementState {
  ready: boolean;
  busy: boolean;
  tests: Record<string, ModelTestNotice>;
}
export interface ModelManagementHandle<T> {
  create: () => void;
  edit: (model: T) => void;
  test: (model: T) => void;
  remove: (model: T) => void;
  toggle?: (model: T) => void;
}
export interface ModelManagementProps<T> {
  managementRef?: Ref<ModelManagementHandle<T>>;
  onManagementState?: (state: ModelManagementState) => void;
}
export const emptyManagementState: ModelManagementState = { ready: false, busy: false, tests: {} };
