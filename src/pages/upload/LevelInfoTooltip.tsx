import { useState, useRef, useEffect } from "react";
import { confidentialityLevelDescriptions, aiAccessLevelDescriptions } from "./uploadConstants";

interface LevelTooltipProps {
  type: "confidentiality" | "aiAccess";
}

function LevelTooltip({ type }: LevelTooltipProps) {
  const [visible, setVisible] = useState(false);
  const triggerRef = useRef<HTMLSpanElement>(null);
  const popupRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!visible) return;
    function onClickOutside(e: MouseEvent) {
      if (
        popupRef.current &&
        !popupRef.current.contains(e.target as Node) &&
        triggerRef.current &&
        !triggerRef.current.contains(e.target as Node)
      ) {
        setVisible(false);
      }
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, [visible]);

  if (type === "confidentiality") {
    return (
      <span className="lv-tip-wrapper">
        <span
          ref={triggerRef}
          className="lv-tip-icon"
          tabIndex={0}
          role="button"
          aria-label="查看保密级别说明"
          onMouseEnter={() => setVisible(true)}
          onMouseLeave={() => setVisible(false)}
          onFocus={() => setVisible(true)}
          onBlur={() => setVisible(false)}
          onClick={() => setVisible((v) => !v)}
        >
          ⓘ
        </span>
        {visible && (
          <div ref={popupRef} className="lv-tip-popup">
            <table className="lv-tip-table">
              <thead>
                <tr>
                  <th>级别</th>
                  <th>定义</th>
                  <th>典型资料</th>
                  <th>AI 调用建议</th>
                </tr>
              </thead>
              <tbody>
                {confidentialityLevelDescriptions.map((l) => (
                  <tr key={l.level}>
                    <td>
                      <strong>{l.level}</strong>
                    </td>
                    <td>{l.summary}</td>
                    <td>{l.examples}</td>
                    <td>{l.aiSuggestion}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </span>
    );
  }

  return (
    <span className="lv-tip-wrapper">
      <span
        ref={triggerRef}
        className="lv-tip-icon"
        tabIndex={0}
        role="button"
        aria-label="查看自动处理级别说明"
        onMouseEnter={() => setVisible(true)}
        onMouseLeave={() => setVisible(false)}
        onFocus={() => setVisible(true)}
        onBlur={() => setVisible(false)}
        onClick={() => setVisible((v) => !v)}
      >
        ⓘ
      </span>
      {visible && (
        <div ref={popupRef} className="lv-tip-popup">
          <table className="lv-tip-table">
            <thead>
              <tr>
                <th>级别</th>
                <th>AI 调用说明</th>
              </tr>
            </thead>
            <tbody>
              {aiAccessLevelDescriptions.map((a) => (
                <tr key={a.level}>
                  <td>
                    <strong>{a.level}</strong>
                  </td>
                  <td>{a.description}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </span>
  );
}

/** 在资料信息卡片底部展示保密级别和自动处理级别的说明入口。 */
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
