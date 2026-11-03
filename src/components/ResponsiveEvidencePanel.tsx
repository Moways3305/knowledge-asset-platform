import { useState, type ReactNode } from "react";
import { BookOpen, ChevronRight } from "lucide-react";
import DetailDrawer from "./DetailDrawer";

/** Same citation content: desktop reference column, mobile reference sheet. */
export default function ResponsiveEvidencePanel({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <aside className="project-answer-sources" aria-label="回答依据">
        <h3>回答依据</h3>
        {children}
      </aside>
      <button type="button" className="mobile-evidence-trigger" onClick={() => setOpen(true)}>
        <BookOpen size={17} aria-hidden="true" />
        查看回答依据与引用
        <ChevronRight size={16} aria-hidden="true" />
      </button>
      <DetailDrawer
        portal
        open={open}
        title="回答依据"
        onClose={() => setOpen(false)}
        className="mobile-evidence-drawer"
      >
        {children}
      </DetailDrawer>
    </>
  );
}
