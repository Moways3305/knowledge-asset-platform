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
      category_id: "",
      subject,
      formed_on: new Date().toISOString().slice(0, 10),
      version: "V1",
      directory_key: "",
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
        const categories = result.categories.filter((item) => item.enabled !== false);
        const directories = result.directories.filter(
          (item) => item.enabled && item.scope === scope,
        );
        const category =
          categories.find((item) => item.id === value.naming.category_id) ?? categories[0];
        const suggestedDirectory =
          directories.find((item) => item.directory_key === category?.suggested_directory_key) ??
          directories.find((item) => item.directory_key === value.naming.directory_key) ??
          directories[0];
        setOptions({ ...result, categories, directories });
        setLoadState("ready");
        onChange({
          confidentiality_level:
            value.confidentiality_level ||
            category?.default_confidentiality ||
            result.default_confidentiality ||
            "L2",
          naming: {
            ...value.naming,
            category_id: category?.id ?? "",
            directory_key: suggestedDirectory?.directory_key ?? "",
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
      !value.naming.category_id ||
      !value.naming.subject.trim() ||
      !value.naming.formed_on ||
      !value.naming.version.trim() ||
      !value.naming.directory_key ||
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
  if (!options?.categories.length || !options.directories.length) {
    return <p role="alert">目标库没有可用的正式类别或目录，暂时不能发布。</p>;
  }

  return (
    <div className="publication-naming-fields">
      <div className="publication-naming-grid">
        <label>
          <span>目录类别</span>
          <select
            value={value.naming.category_id}
            disabled={disabled}
            onChange={(event) => {
              const category = options.categories.find((item) => item.id === event.target.value);
              const suggested = options.directories.find(
                (item) => item.directory_key === category?.suggested_directory_key,
              );
              update({
                ...value,
                confidentiality_level:
                  category?.default_confidentiality || value.confidentiality_level,
                naming: {
                  ...value.naming,
                  category_id: event.target.value,
                  directory_key: suggested?.directory_key || value.naming.directory_key,
                },
              });
            }}
          >
            {options.categories.map((item) => (
              <option key={item.id} value={item.id}>
                {item.primary} / {item.secondary}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>正式目录</span>
          <select
            value={value.naming.directory_key ?? ""}
            disabled={disabled}
            onChange={(event) =>
              update({ ...value, naming: { ...value.naming, directory_key: event.target.value } })
            }
          >
            <option value="">请选择正式目录</option>
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
          <p role="alert">请补全命名和正式目录，或检查目标规则后重试。</p>
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
