import type { ReactNode } from "react";
import ModuleFrame from "./ModuleFrame";
import "./ProjectModuleFrame.css";

export default function ProjectModuleFrame({
  navigation,
  children,
}: {
  navigation: ReactNode;
  children: ReactNode;
}) {
  return (
    <ModuleFrame navigation={navigation} label="项目工作区" className="project-module-frame">
      {children}
    </ModuleFrame>
  );
}
