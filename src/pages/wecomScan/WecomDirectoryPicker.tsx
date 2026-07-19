import { useState, useCallback, useEffect } from "react";
import { fetchWecomDriveDirectories, fetchWecomDriveSpaces } from "../../api/admin";
import type { WecomDriveDirectoryDTO, WecomDriveSpaceDTO } from "../../types/wecom";

// 微盘目录选择器。先列空间，再浏览子目录并钻取；选中后回填可保存的 directory_ref。
// 只展示目录名（友好），不要求用户理解 spaceid/fatherid；不展示文件、不下载。
export default function WecomDirectoryPicker({
  onSelect,
}: {
  onSelect: (ref: string, label: string) => void;
}) {
  const [spaces, setSpaces] = useState<WecomDriveSpaceDTO[]>([]);
  const [space, setSpace] = useState<WecomDriveSpaceDTO | null>(null);
  // 面包屑：第一项为空间根（ref=null），后续为已钻取目录。
  const [stack, setStack] = useState<{ ref: string | null; name: string }[]>([]);
  const [dirs, setDirs] = useState<WecomDriveDirectoryDTO[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchWecomDriveSpaces()
      .then((d) => {
        if (!cancelled) setSpaces(d.items);
      })
      .catch(() => {
        if (!cancelled) setError("微盘空间暂时无法加载，请检查企业微信配置后重试。");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const loadDirs = useCallback(async (spaceRef: string, parentRef: string | undefined) => {
    setLoading(true);
    setError(null);
    try {
      setDirs((await fetchWecomDriveDirectories(spaceRef, parentRef)).items);
    } catch {
      setError("目录暂时无法加载，请返回上级或稍后重试。");
      setDirs([]);
    } finally {
      setLoading(false);
    }
  }, []);

  const openSpace = useCallback(
    async (sp: WecomDriveSpaceDTO) => {
      setSpace(sp);
      setStack([{ ref: null, name: sp.name }]);
      await loadDirs(sp.space_ref, undefined);
    },
    [loadDirs],
  );

  const drill = useCallback(
    async (d: WecomDriveDirectoryDTO) => {
      if (!space) return;
      setStack((s) => [...s, { ref: d.directory_ref, name: d.name }]);
      await loadDirs(space.space_ref, d.directory_ref);
    },
    [space, loadDirs],
  );

  const goTo = useCallback(
    async (idx: number) => {
      if (!space) return;
      const ns = stack.slice(0, idx + 1);
      setStack(ns);
      await loadDirs(space.space_ref, ns[ns.length - 1].ref ?? undefined);
    },
    [space, stack, loadDirs],
  );

  const useHere = useCallback(() => {
    if (!space) return;
    const cur = stack[stack.length - 1];
    const ref = cur?.ref ?? `spaceid:${space.space_ref};fatherid:`; // 空间根 = fatherid 空
    const label = stack.map((s) => s.name).join(" / ");
    onSelect(ref, label);
  }, [space, stack, onSelect]);

  return (
    <div className="ws87-picker">
      {error && (
        <div className="ws-note-hint" style={{ color: "var(--color-danger-fg, #b00)" }}>
          {error}
        </div>
      )}
      {!space ? (
        <div>
          <div className="ws-form-label">选择微盘空间</div>
          {loading ? (
            <div className="ig-empty-state">
              <div className="ig-empty-title">加载中…</div>
            </div>
          ) : spaces.length === 0 ? (
            <p className="ws-form-hint">当前没有可选择的微盘空间，请检查企业微信配置后重试。</p>
          ) : (
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 6 }}>
              {spaces.map((sp) => (
                <button
                  key={sp.space_ref}
                  className="btn-small"
                  type="button"
                  onClick={() => void openSpace(sp)}
                >
                  {sp.name}
                </button>
              ))}
            </div>
          )}
        </div>
      ) : (
        <div>
          <div
            style={{
              display: "flex",
              gap: 6,
              alignItems: "center",
              flexWrap: "wrap",
              fontSize: 13,
            }}
          >
            {stack.map((s, i) => (
              <span key={i}>
                {i > 0 && <span style={{ color: "var(--color-text-muted, #aaa)" }}> / </span>}
                <button
                  className="btn-link"
                  type="button"
                  style={{
                    background: "none",
                    border: "none",
                    cursor: "pointer",
                    color: "var(--color-link, #36c)",
                    padding: 0,
                  }}
                  onClick={() => void goTo(i)}
                >
                  {s.name}
                </button>
              </span>
            ))}
            <button
              className="btn-small"
              type="button"
              style={{ marginLeft: "auto" }}
              onClick={() => {
                setSpace(null);
                setDirs([]);
                setStack([]);
              }}
            >
              切换空间
            </button>
          </div>
          {loading ? (
            <div className="ig-empty-state">
              <div className="ig-empty-title">加载中…</div>
            </div>
          ) : dirs.length === 0 ? (
            <p className="ws-form-hint" style={{ marginTop: 8 }}>
              该目录下无子目录。可直接「使用当前目录」。
            </p>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 4, marginTop: 8 }}>
              {dirs.map((d) => (
                <button
                  key={d.directory_ref}
                  className="btn-small"
                  type="button"
                  style={{ textAlign: "left" }}
                  onClick={() => void drill(d)}
                >
                  📁 {d.name}
                  {d.has_children ? " ›" : ""}
                </button>
              ))}
            </div>
          )}
          <div className="ws-form-actions" style={{ marginTop: 10 }}>
            <button className="btn-small-primary" type="button" onClick={useHere}>
              使用当前目录
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
