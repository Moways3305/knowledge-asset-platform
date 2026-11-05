import { useState } from "react";
import type { ModelConnectionDTO } from "../types/modelConnections";
import type { ModelDTO } from "../types/weknoraAdmin";
import { ActionMenu } from "./ActionLayout";
import { ProviderLogo } from "./providerIcons";
import type { ModelManagementState } from "./modelManagement";

const types: Record<string, string> = {
  chat: "对话",
  embedding: "嵌入",
  rerank: "重排",
  vllm: "多模态",
  asr: "语音识别",
};
const providers: Record<string, string> = {
  aliyun: "阿里云百炼",
  qwen: "阿里云百炼",
  deepseek: "DeepSeek",
  openai: "OpenAI",
  moonshot: "Moonshot",
  kimi: "Moonshot",
  zhipu: "智谱",
  glm: "智谱",
  siliconflow: "硅基流动",
};
type Row = { kind: "external"; model: ModelConnectionDTO } | { kind: "knowledge"; model: ModelDTO };
type Action = "edit" | "test" | "remove" | "toggle";

function lastTest(connection: ModelConnectionDTO) {
  const times = [connection.last_test_succeeded_at, connection.last_test_failed_at]
    .filter((value): value is string => Boolean(value))
    .map((value) => new Date(value).getTime())
    .filter(Number.isFinite);
  return times.length
    ? new Date(Math.max(...times)).toLocaleString("zh-CN", {
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      })
    : null;
}

export default function ModelRegistryTable({
  connections,
  models,
  externalState,
  knowledgeState,
  canEdit,
  loading,
  onExternalAction,
  onKnowledgeAction,
}: {
  connections: ModelConnectionDTO[];
  models: ModelDTO[];
  externalState: ModelManagementState;
  knowledgeState: ModelManagementState;
  canEdit: boolean;
  loading: boolean;
  onExternalAction: (action: Action, model: ModelConnectionDTO) => void;
  onKnowledgeAction: (action: Action, model: ModelDTO) => void;
}) {
  const [query, setQuery] = useState("");
  const [type, setType] = useState("all");
  const [status, setStatus] = useState("all");
  const all: Row[] = [
    ...connections.map((model): Row => ({ kind: "external", model })),
    ...models.map((model): Row => ({ kind: "knowledge", model })),
  ];
  const rows = all.filter((row) => {
    const name =
      row.kind === "external"
        ? `${row.model.display_name} ${row.model.model_name}`
        : row.model.name;
    const modelType = row.kind === "external" ? row.model.capability_type : row.model.type;
    const provider = row.model.provider ?? "";
    return (
      `${name} ${provider} ${providers[provider] ?? ""}`
        .toLowerCase()
        .includes(query.trim().toLowerCase()) &&
      (type === "all" || type === modelType) &&
      (status === "all" || (status === "enabled") === row.model.enabled)
    );
  });
  return (
    <section className="model-registry" aria-label="模型列表">
      <div className="model-registry-toolbar">
        <input
          aria-label="搜索模型"
          placeholder="搜索模型名称或供应商"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <select aria-label="模型能力" value={type} onChange={(e) => setType(e.target.value)}>
          <option value="all">全部能力</option>
          {Object.entries(types).map(([key, label]) => (
            <option key={key} value={key}>
              {label}
            </option>
          ))}
        </select>
        <select
          aria-label="启用状态筛选"
          value={status}
          onChange={(e) => setStatus(e.target.value)}
        >
          <option value="all">全部状态</option>
          <option value="enabled">已启用</option>
          <option value="disabled">已停用</option>
        </select>
        <span className="model-registry-count">
          {loading ? "正在同步…" : `${rows.length} 个模型`}
        </span>
      </div>
      <div
        className="model-registry-scroll"
        role="region"
        aria-label="模型表格，可横向滚动"
        tabIndex={0}
      >
        <table className="model-registry-table">
          <caption className="sr-only">已接入模型及其用途、启用状态和测试结果</caption>
          <thead>
            <tr>
              <th scope="col">模型名称</th>
              <th scope="col">启用状态</th>
              <th scope="col">供应商</th>
              <th scope="col">能力</th>
              <th scope="col">用途</th>
              <th scope="col">连接测试</th>
              <th scope="col">操作</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const model = row.model;
              const name = row.kind === "external" ? row.model.display_name : row.model.name;
              const type = row.kind === "external" ? row.model.capability_type : row.model.type;
              const usage = row.kind === "external" ? "内容生成 · 项目问答" : "知识库检索与解析";
              const manager = row.kind === "external" ? externalState : knowledgeState;
              const notice = manager.tests[model.model_ref];
              const busy = loading || manager.busy || !manager.ready;
              const provider = providers[model.provider ?? ""] ?? model.provider ?? "未指定";
              const time = row.kind === "external" ? lastTest(row.model) : null;
              const fallback =
                row.kind === "external"
                  ? row.model.health_status === "healthy"
                    ? "测试通过"
                    : row.model.health_status === "unhealthy"
                      ? "连接异常"
                      : "未测试"
                  : row.model.credential_status === "configured"
                    ? "待测试"
                    : row.model.credential_status === "missing"
                      ? "缺少凭据"
                      : "凭据待确认";
              const label = notice
                ? notice.tone === "busy"
                  ? "测试中…"
                  : notice.tone === "success"
                    ? "本次测试通过"
                    : "本次测试失败"
                : fallback;
              const tone =
                notice?.tone ??
                (fallback === "测试通过"
                  ? "success"
                  : ["连接异常", "缺少凭据"].includes(fallback)
                    ? "danger"
                    : "neutral");
              const action = (action: Action) =>
                row.kind === "external"
                  ? onExternalAction(action, row.model)
                  : onKnowledgeAction(action, row.model);
              return (
                <tr key={`${row.kind}:${model.model_ref}`} aria-label={`${name}（${usage}）`}>
                  <td>
                    <strong className="model-registry-name">{name}</strong>
                    {row.kind === "external" && name !== row.model.model_name && (
                      <small>{row.model.model_name}</small>
                    )}
                  </td>
                  <td>
                    <span className={`model-enabled ${model.enabled ? "is-enabled" : ""}`}>
                      {model.enabled ? "已启用" : "已停用"}
                    </span>
                  </td>
                  <td>
                    <span className="model-provider">
                      <ProviderLogo provider={model.provider ?? "custom"} label={provider} />
                      <span>{provider}</span>
                    </span>
                  </td>
                  <td>
                    {types[type] ?? type}
                    {row.kind === "knowledge" && type === "embedding" && row.model.dimension && (
                      <small>{row.model.dimension} 维</small>
                    )}
                  </td>
                  <td>
                    <span className="model-registry-usage">{usage}</span>
                  </td>
                  <td>
                    <span
                      className={`model-test-state is-${tone}`}
                      role={notice ? "status" : undefined}
                    >
                      {label}
                    </span>
                    {notice ? (
                      <small className="model-test-message">{notice.message}</small>
                    ) : (
                      time && <small>{time}</small>
                    )}
                  </td>
                  <td>
                    {canEdit ? (
                      <div className="model-row-actions">
                        <button
                          type="button"
                          className="model-text-action"
                          disabled={busy}
                          onClick={() => action("test")}
                        >
                          测试
                        </button>
                        <button
                          type="button"
                          className="model-text-action"
                          disabled={busy}
                          onClick={() => action("edit")}
                        >
                          编辑
                        </button>
                        <ActionMenu
                          label="···"
                          ariaLabel={`更多操作：${name}（${usage}）`}
                          disabled={busy}
                        >
                          {row.kind === "external" && (
                            <button className="btn-small" onClick={() => action("toggle")}>
                              {model.enabled ? "停用" : "启用"}
                            </button>
                          )}
                          <button
                            className="btn-small mf-delete-btn"
                            onClick={() => action("remove")}
                          >
                            删除
                          </button>
                        </ActionMenu>
                      </div>
                    ) : (
                      <span className="model-readonly">只读</span>
                    )}
                  </td>
                </tr>
              );
            })}
            {rows.length === 0 && (
              <tr>
                <td colSpan={7} className="model-registry-empty">
                  <strong>
                    {loading ? "正在读取模型…" : all.length ? "没有匹配的模型" : "尚未接入模型"}
                  </strong>
                  <span>
                    {loading
                      ? ""
                      : all.length
                        ? "调整搜索词或筛选条件后重试。"
                        : canEdit
                          ? "点击右上角“接入模型”，添加需要使用的模型。"
                          : "当前没有可展示的模型。"}
                  </span>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <p className="model-registry-hint">
        启用状态与连接测试分别显示；保存凭据后，请测试连接。知识库模型的测试结果仅保留在本次页面中。
      </p>
    </section>
  );
}
