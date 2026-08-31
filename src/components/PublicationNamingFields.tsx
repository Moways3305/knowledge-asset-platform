import { useEffect, useRef, useState } from "react";
import { fetchNamingOptions } from "../api/naming";
import type { NamingConfirmationDTO, NamingOptionsDTO, NamingPreviewDTO } from "../types/naming";
import "./PublicationNamingFields.css";

export interface PublicationNamingValue {
  confidentiality_level: string;
  naming: NamingConfirmationDTO;
}

export function createPublicationNamingValue(subject: string): PublicationNamingValue {
  return {
    confidentiality_level: "L2",
    naming: {
      directory_key: "",
      subject,
      formed_on: new Date().toISOString().slice(0, 10),
      version: "V1",
    },
  };
}

export default function PublicationNamingFields({
  scope,
  projectId,
  value,
  disabled = false,
  onChange,
  onPreview,
  onPreviewed,
}: {
  scope: "project" | "company";
  projectId?: string;
  value: PublicationNamingValue;
  disabled?: boolean;
  onChange: (value: PublicationNamingValue) => void;
  onPreview: (value: PublicationNamingValue) => Promise<NamingPreviewDTO>;
  onPreviewed: (preview: NamingPreviewDTO | null) => void;
}) {
  const [options, setOptions] = useState<NamingOptionsDTO | null>(null);
  const [loadState, setLoadState] = useState<"loading" | "ready" | "error">("loading");
  const [previewState, setPreviewState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [preview, setPreview] = useState<NamingPreviewDTO | null>(null);
  const requestRef = useRef(0);

  useEffect(() => {
    const request = ++requestRef.current;
    setLoadState("loading");
    setOptions(null);
    setPreview(null);
    setPreviewState("idle");
    onPreviewed(null);
    fetchNamingOptions(scope, scope === "project" ? projectId : undefined)
      .then((result) => {
        if (request !== requestRef.current) return;
        const directories = result.directories.filter(
          (item) => item.enabled && item.scope === scope,
        );
        const selectedDirectory = directories.some(
          (item) => item.directory_key === value.naming.directory_key,
        )
          ? value.naming.directory_key
          : (directories[0]?.directory_key ?? "");
        setOptions({ ...result, directories });
        setLoadState("ready");
        onChange({
          confidentiality_level:
            value.confidentiality_level || result.default_confidentiality || "L2",
          naming: {
            ...value.naming,
            directory_key: selectedDirectory,
          },
        });
      })
      .catch(() => {
        if (request !== requestRef.current) return;
        setLoadState("error");
      });
    return () => {
      requestRef.current += 1;
    };
    // A new scope/project starts a new governed publication session.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scope, projectId]);

  const update = (next: PublicationNamingValue) => {
    setPreview(null);
    setPreviewState("idle");
    onPreviewed(null);
    onChange(next);
  };

  const runPreview = async () => {
    if (
      !value.naming.directory_key ||
      !value.naming.subject.trim() ||
      !value.naming.formed_on ||
      !value.naming.version.trim() ||
      (scope === "company" && !value.naming.applicable_to?.trim())
    ) {
      setPreviewState("error");
      return;
    }
    setPreviewState("loading");
    setPreview(null);
    onPreviewed(null);
    try {
      const result = await onPreview(value);
      setPreview(result);
      setPreviewState("ready");
      onPreviewed(result);
    } catch {
      setPreviewState("error");
    }
  };

  if (loadState === "loading") return <p role="status">正在加载目标库命名规则…</p>;
  if (loadState === "error") {
    return <p role="alert">目标库命名规则暂时无法加载，请关闭后重试。</p>;
  }
  if (!options?.directories.length) {
    return <p role="alert">目标库没有可用的正式目录，暂时不能发布。</p>;
  }

  return (
    <div className="publication-naming-fields">
      <div className="publication-naming-grid">
        <label>
          <span>正式目录</span>
          <select
            aria-label="正式目录"
            value={value.naming.directory_key}
            disabled={disabled}
            onChange={(event) =>
              update({
                ...value,
                naming: {
                  ...value.naming,
                  directory_key: event.target.value,
                },
              })
            }
          >
            {options.directories.map((item) => (
              <option key={item.directory_key} value={item.directory_key}>
                {item.display_name}
              </option>
            ))}
          </select>
        </label>
        <label className="publication-naming-wide">
          <span>主题</span>
          <input
            value={value.naming.subject}
            maxLength={120}
            disabled={disabled}
            onChange={(event) =>
              update({ ...value, naming: { ...value.naming, subject: event.target.value } })
            }
          />
        </label>
        {scope === "company" && (
          <label>
            <span>适用对象</span>
            <input
              value={value.naming.applicable_to ?? ""}
              maxLength={60}
              disabled={disabled}
              onChange={(event) =>
                update({ ...value, naming: { ...value.naming, applicable_to: event.target.value } })
              }
            />
          </label>
        )}
        <label>
          <span>形成日期</span>
          <input
            type="date"
            value={value.naming.formed_on}
            disabled={disabled}
            onChange={(event) =>
              update({ ...value, naming: { ...value.naming, formed_on: event.target.value } })
            }
          />
        </label>
        <label>
          <span>版本</span>
          <input
            value={value.naming.version}
            placeholder="V1"
            disabled={disabled}
            onChange={(event) =>
              update({ ...value, naming: { ...value.naming, version: event.target.value } })
            }
          />
        </label>
        <label>
          <span>密级</span>
          <select
            value={value.confidentiality_level}
            disabled={disabled}
            onChange={(event) => update({ ...value, confidentiality_level: event.target.value })}
          >
            {["L1", "L2", "L3", "L4", "L5"].map((level) => (
              <option key={level} value={level}>
                {level}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="publication-naming-preview">
        <button
          type="button"
          className="product-button is-secondary is-small"
          disabled={disabled || previewState === "loading"}
          onClick={() => void runPreview()}
        >
          {previewState === "loading" ? "校验中…" : "预览目标文件名"}
        </button>
        {previewState === "error" && (
          <p role="alert">请补全正式目录和命名信息，或刷新目录后重试。</p>
        )}
        {preview?.canonical_name && (
          <div className="publication-canonical" role="status">
            <span>目标文件名</span>
            <strong>{preview.canonical_name}</strong>
          </div>
        )}
      </div>
    </div>
  );
}
