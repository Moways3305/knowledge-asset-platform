import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { fetchMyUploads } from "../api/ingest";
import { ApiError } from "../api/http";
import type { MyUploadItemDTO } from "../types/ingest";

const statusLabels: Record<MyUploadItemDTO["final_status"], string> = {
  processing: "处理中",
  awaiting_confirmation: "待确认",
  waiting_review: "等待审核",
  completed: "已完成",
  failed: "处理失败",
  duplicate_skipped: "跳过重复",
};

const processingLabels: Record<string, string> = {
  processing: "处理中",
  pending_confirmation: "待确认",
  waiting_review: "等待审核",
  completed: "处理完成",
  failed: "处理失败",
  duplicate_skipped: "已跳过重复",
};

export default function MyUploadsPanel({ onClose }: { onClose: () => void }) {
  const [items, setItems] = useState<MyUploadItemDTO[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [scope, setScope] = useState("");
  const [status, setStatus] = useState("");
  const [duplicate, setDuplicate] = useState("");
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");

  useEffect(() => {
    let live = true;
    setLoading(true);
    setError(null);
    void fetchMyUploads({
      scope: scope || undefined,
      finalStatus: status || undefined,
      duplicateResult: duplicate || undefined,
      since: since ? new Date(`${since}T00:00:00`).toISOString() : undefined,
      until: until ? new Date(`${until}T23:59:59`).toISOString() : undefined,
    })
      .then((value) => {
        if (live) setItems(value);
      })
      .catch((reason) => {
        if (live) setError(reason instanceof ApiError ? reason.message : "上传记录加载失败");
      })
      .finally(() => {
        if (live) setLoading(false);
      });
    return () => {
      live = false;
    };
  }, [duplicate, scope, since, status, until]);

  const filtered = Boolean(scope || status || duplicate || since || until);
  return (
    <section className="my-uploads" aria-labelledby="my-uploads-title">
      <header>
        <div>
          <span className="upload77-kicker">仅本人可见</span>
          <h2 id="my-uploads-title">我上传的资料</h2>
        </div>
        <button className="btn-secondary" type="button" onClick={onClose}>
          关闭
        </button>
      </header>
      <div className="my-uploads-filters" aria-label="上传记录筛选">
        <label>
          <span>目标范围</span>
          <select value={scope} onChange={(e) => setScope(e.target.value)}>
            <option value="">全部</option>
            <option value="personal">个人库</option>
            <option value="project">项目库</option>
            <option value="company">公司库</option>
          </select>
        </label>
        <label>
          <span>最终状态</span>
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">全部</option>
            <option value="processing">处理中</option>
            <option value="awaiting_confirmation">待确认</option>
            <option value="waiting_review">等待审核</option>
            <option value="completed">已完成</option>
            <option value="failed">失败</option>
            <option value="duplicate_skipped">跳过重复</option>
          </select>
        </label>
        <label>
          <span>重复结果</span>
          <select value={duplicate} onChange={(e) => setDuplicate(e.target.value)}>
            <option value="">全部</option>
            <option value="skipped">本次不入库</option>
            <option value="independent">独立入库</option>
            <option value="none">未处理重复</option>
          </select>
        </label>
        <label>
          <span>开始日期</span>
          <input type="date" value={since} onChange={(e) => setSince(e.target.value)} />
        </label>
        <label>
          <span>结束日期</span>
          <input type="date" value={until} onChange={(e) => setUntil(e.target.value)} />
        </label>
      </div>
      {loading ? (
        <p role="status">正在加载上传记录…</p>
      ) : error ? (
        <p role="alert">{error}</p>
      ) : items.length === 0 ? (
        <p className="my-uploads-empty">{filtered ? "当前筛选无结果" : "尚未上传资料"}</p>
      ) : (
        <div className="my-uploads-list">
          {items.map((item) => (
            <article key={item.task_id}>
              <div>
                <strong>{item.source_file_name}</strong>
                <span>{new Date(item.uploaded_at).toLocaleString()}</span>
              </div>
              <dl>
                <div>
                  <dt>目标</dt>
                  <dd>
                    {item.target_scope === "personal"
                      ? "个人库"
                      : item.target_scope === "project"
                        ? item.target_project_name
                          ? `项目库 · ${item.target_project_name}`
                          : "项目库"
                        : item.target_scope === "company"
                          ? "公司库"
                          : "待选择"}
                  </dd>
                </div>
                <div>
                  <dt>处理状态</dt>
                  <dd>{processingLabels[item.processing_status] ?? "状态更新中"}</dd>
                </div>
                <div>
                  <dt>最终状态</dt>
                  <dd>{statusLabels[item.final_status]}</dd>
                </div>
                <div>
                  <dt>重复处理</dt>
                  <dd>
                    {item.duplicate_result === "skipped"
                      ? "本次不入库"
                      : item.duplicate_result === "independent"
                        ? "作为独立资料入库"
                        : "无"}
                  </dd>
                </div>
              </dl>
              {item.result_asset_id && (
                <Link to={`/knowledge/${item.result_asset_id}`}>查看资产详情</Link>
              )}
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
