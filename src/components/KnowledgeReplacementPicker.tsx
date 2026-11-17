import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "../api/http";
import { fetchReplacementOptions, fetchTrust } from "../api/knowledgeTrust";

export interface ReplacementSelection {
  asset_id: string;
  updated_at: string;
}

/** Shared by the asset maintenance panel and company governance. */
export default function KnowledgeReplacementPicker({
  assetId,
  disabled,
  onChange,
}: {
  assetId: string;
  disabled?: boolean;
  onChange: (value: ReplacementSelection | null) => void;
}) {
  const [query, setQuery] = useState("");
  const [options, setOptions] = useState<{ asset_id: string; title: string }[]>([]);
  const [candidate, setCandidate] = useState<ReplacementSelection | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const serial = useRef(0);
  useEffect(
    () => () => {
      serial.current++;
    },
    [assetId],
  );
  const reset = () => {
    serial.current++;
    setCandidate(null);
    setConfirmed(false);
    onChange(null);
  };
  return (
    <div className="knowledge-trust-task">
      <label>
        查找新版资料
        <input
          value={query}
          disabled={disabled || loading}
          maxLength={200}
          placeholder="输入已入库新版的标题"
          onChange={(e) => {
            setQuery(e.target.value);
            setOptions([]);
            reset();
          }}
        />
      </label>
      <button
        type="button"
        disabled={disabled || loading}
        onClick={async () => {
          reset();
          const request = ++serial.current;
          setLoading(true);
          setError("");
          try {
            const result = await fetchReplacementOptions(assetId, query);
            if (serial.current === request) {
              setOptions(result);
              if (!result.length) setError("没有可关联的新版，请先通过上传新版完成入库。");
            }
          } catch (e) {
            if (serial.current === request)
              setError(e instanceof ApiError ? e.message : "查找失败，请重试。");
          } finally {
            if (serial.current === request) setLoading(false);
          }
        }}
      >
        {loading ? "正在核对…" : "查找可关联新版"}
      </button>
      <label>
        新版资料
        <select
          aria-label="新版资料"
          disabled={disabled || loading}
          value={candidate?.asset_id ?? ""}
          onChange={async (e) => {
            const id = e.target.value;
            reset();
            if (!id) return;
            const request = ++serial.current;
            setLoading(true);
            setError("");
            try {
              const result = await fetchTrust(id);
              if (serial.current === request) setCandidate(result);
            } catch (e) {
              if (serial.current === request)
                setError(e instanceof ApiError ? e.message : "新版读取失败。");
            } finally {
              if (serial.current === request) setLoading(false);
            }
          }}
        >
          <option value="">请选择新版</option>
          {options.map((item) => (
            <option key={item.asset_id} value={item.asset_id}>
              {item.title}
            </option>
          ))}
        </select>
      </label>
      {candidate && (
        <Link to={`/knowledge/${candidate.asset_id}`} target="_blank" rel="noreferrer">
          打开新版核对内容
        </Link>
      )}
      <label className="knowledge-trust-confirm">
        <input
          type="checkbox"
          checked={confirmed}
          disabled={disabled || !candidate || loading}
          onChange={(e) => {
            setConfirmed(e.target.checked);
            onChange(e.target.checked ? candidate : null);
          }}
        />
        我已核对新版内容，确认采用新版并将旧版归档。
      </label>
      {error && <p role="status">{error}</p>}
    </div>
  );
}
