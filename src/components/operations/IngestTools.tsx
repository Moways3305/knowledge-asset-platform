import { useEffect, useState } from "react";
import { fetchAuthMe } from "../../api/auth";
import { fetchWecomScanProjectOptions } from "../../api/admin";
import { backfillMarkdown } from "../../api/admin";
import { OperationPanel, ReadResult, useOperation } from "./OperationPanel";
import { OpsSummaryButton, KnowledgeInsightsButton } from "./ReadTools";

function BackfillForm({ onJobCreated }: { onJobCreated?: () => void }) {
  const [scope, setScope] = useState("all");
  const [projectId, setProjectId] = useState("");
  const [limit, setLimit] = useState(50);
  const [rebuild, setRebuild] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const operation = useOperation();
  return (
    <form
      className="operation-form"
      onSubmit={(event) => {
        event.preventDefault();
        if (
          operation.busy ||
          (scope === "project" && !projectId) ||
          !Number.isInteger(limit) ||
          limit < 1 ||
          limit > 100
        )
          return;
        setConfirming(true);
      }}
    >
      <p>
        为历史资料补齐受控正文。每次只处理所选范围的一批资料，可分批继续。需要重建检索索引时单独勾选。
      </p>
      <fieldset disabled={operation.busy || confirming} className="operation-form">
        <label>
          资料范围
          <select value={scope} onChange={(event) => setScope(event.target.value)}>
            <option value="all">全部范围</option>
            <option value="company">公司库</option>
            <option value="project">指定项目</option>
            <option value="personal">个人库</option>
          </select>
        </label>
        {scope === "project" && (
          <ReadResult refreshLabel={false} load={fetchWecomScanProjectOptions}>
            {(data) => (
              <label>
                项目
                <select
                  required
                  value={projectId}
                  onChange={(event) => setProjectId(event.target.value)}
                >
                  <option value="">请选择项目</option>
                  {data.items.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.name}
                    </option>
                  ))}
                </select>
              </label>
            )}
          </ReadResult>
        )}
        <label>
          本次处理上限
          <input
            type="number"
            min={1}
            max={100}
            required
            value={limit}
            onChange={(event) => setLimit(Number(event.target.value))}
          />
        </label>
        <label className="operation-check">
          <input
            type="checkbox"
            checked={rebuild}
            onChange={(event) => setRebuild(event.target.checked)}
          />
          同时重建索引
        </label>
      </fieldset>
      {!confirming ? (
        <button
          className="btn-small"
          type="submit"
          disabled={operation.busy || (scope === "project" && !projectId)}
        >
          准备正文回填
        </button>
      ) : (
        <>
          <p>
            确认对所选范围执行正文回填，最多 {limit} 项{rebuild ? "，并重建索引" : "，不重建索引"}
            。任务创建后可在作业记录中查看进度。
          </p>
          <div className="operation-actions">
            <button
              type="button"
              className="btn-small"
              disabled={operation.busy}
              onClick={() =>
                void operation.run(async () => {
                  const job = await backfillMarkdown({
                    scope,
                    project_id: scope === "project" ? projectId : undefined,
                    limit,
                    rebuild_index: rebuild,
                  });
                  setConfirming(false);
                  onJobCreated?.();
                  return `已创建正文回填作业。当前状态：${({ queued: "等待执行", running: "执行中", completed: "已完成", completed_with_errors: "部分未成功", failed: "执行失败", no_action: "没有可处理项", submitted_pending_index: "待索引确认" } as Record<string, string>)[job.status] ?? "待确认"}；请在作业记录中查看最终结果。`;
                })
              }
            >
              {operation.busy ? "提交中…" : "确认执行"}
            </button>
            <button
              type="button"
              className="btn-small"
              disabled={operation.busy}
              onClick={() => setConfirming(false)}
            >
              取消
            </button>
          </div>
        </>
      )}
      {operation.feedback}
    </form>
  );
}

export function IngestTools({ onJobCreated }: { onJobCreated?: () => void }) {
  const [role, setRole] = useState("");
  useEffect(() => {
    let live = true;
    void fetchAuthMe()
      .then((me) => {
        if (live) setRole(me.activeCompanyRole ?? "");
      })
      .catch(() => {});
    return () => {
      live = false;
    };
  }, []);
  return (
    <div className="operation-actions">
      {role === "admin" && <OpsSummaryButton />}
      {["admin", "boss", "consulting_director"].includes(role) && (
        <OperationPanel label="历史正文回填">
          <BackfillForm onJobCreated={onJobCreated} />
        </OperationPanel>
      )}
      <KnowledgeInsightsButton />
    </div>
  );
}
