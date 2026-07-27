import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { aiAccessLevelDescriptions, confidentialityLevelDescriptions } from "./uploadConstants";

interface LevelTooltipProps {
  type: "confidentiality" | "aiAccess";
}

interface PopupPosition {
  left: number;
  top: number;
  placement: "top" | "bottom";
}

function LevelTooltip({ type }: LevelTooltipProps) {
  const [visible, setVisible] = useState(false);
  const [position, setPosition] = useState<PopupPosition | null>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const popupRef = useRef<HTMLDivElement>(null);
  const label = type === "confidentiality" ? "查看保密级别说明" : "查看自动处理级别说明";

  useLayoutEffect(() => {
    if (!visible || !triggerRef.current) return;
    const updatePosition = () => {
      const rect = triggerRef.current?.getBoundingClientRect();
      if (!rect) return;
      const width = Math.min(520, window.innerWidth - 32);
      const estimatedHeight = type === "confidentiality" ? 290 : 180;
      const placeBelow = rect.top < estimatedHeight + 16;
      setPosition({
        left: Math.max(16, Math.min(rect.left, window.innerWidth - width - 16)),
        top: placeBelow ? rect.bottom + 8 : rect.top - 8,
        placement: placeBelow ? "bottom" : "top",
      });
    };
    updatePosition();
    window.addEventListener("resize", updatePosition);
    window.addEventListener("scroll", updatePosition, true);
    return () => {
      window.removeEventListener("resize", updatePosition);
      window.removeEventListener("scroll", updatePosition, true);
    };
  }, [type, visible]);

  useEffect(() => {
    if (!visible) return;
    const onPointerDown = (event: MouseEvent) => {
      const target = event.target as Node;
      if (!triggerRef.current?.contains(target) && !popupRef.current?.contains(target))
        setVisible(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setVisible(false);
        triggerRef.current?.focus();
      }
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [visible]);

  const popup = visible && position && (
    <div
      ref={popupRef}
      className={`lv-tip-popup is-${position.placement}`}
      role="dialog"
      aria-label={label}
      style={{ left: position.left, top: position.top }}
    >
      <table className="lv-tip-table">
        <thead>
          <tr>
            <th>级别</th>
            <th>{type === "confidentiality" ? "定义" : "AI 调用说明"}</th>
            {type === "confidentiality" && <th>典型资料</th>}
            {type === "confidentiality" && <th>AI 调用建议</th>}
          </tr>
        </thead>
        <tbody>
          {type === "confidentiality"
            ? confidentialityLevelDescriptions.map((level) => (
                <tr key={level.level}>
                  <td>
                    <strong>{level.level}</strong>
                  </td>
                  <td>{level.summary}</td>
                  <td>{level.examples}</td>
                  <td>{level.aiSuggestion}</td>
                </tr>
              ))
            : aiAccessLevelDescriptions.map((level) => (
                <tr key={level.level}>
                  <td>
                    <strong>{level.level}</strong>
                  </td>
                  <td>{level.description}</td>
                </tr>
              ))}
        </tbody>
      </table>
    </div>
  );

  return (
    <span className="lv-tip-wrapper">
      <button
        ref={triggerRef}
        className="lv-tip-icon"
        aria-expanded={visible}
        aria-haspopup="dialog"
        aria-label={label}
        onClick={() => setVisible((current) => !current)}
        type="button"
      >
        ⓘ
      </button>
      {popup && createPortal(popup, document.body)}
    </span>
  );
}

export default function LevelInfoCard() {
  return (
    <div className="up-level-info-card">
      <h5 className="up-level-info-title">级别说明</h5>
      <div className="up-level-info-row">
        <span className="up-level-info-label">保密级别</span>
        <LevelTooltip type="confidentiality" />
      </div>
      <div className="up-level-info-row">
        <span className="up-level-info-label">自动处理级别</span>
        <LevelTooltip type="aiAccess" />
      </div>
    </div>
  );
}
