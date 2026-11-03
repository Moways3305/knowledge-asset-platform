import type { ReactNode } from "react";
import ModuleNavigation from "./ModuleNavigation";
import ModuleFrame from "./ModuleFrame";

/** Keeps the library's sibling navigation in the same place when changing pages. */
export default function KnowledgeModuleFrame({ children }: { children: ReactNode }) {
  return (
    <ModuleFrame navigation={<ModuleNavigation embedded />} label="知识工作区">
      {children}
    </ModuleFrame>
  );
}
