import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { ArrowRight, BookOpen, Check, FileText, History, Send } from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import { createClientUuid } from "../api/http";
import { fetchAgentPolicies, type AgentPolicy } from "../api/maintenanceAgent";
import {
  delegate,
  fetchTask,
  recentTasks,
  type KnowledgeTask,
  type KnowledgeTaskDetail,
  type KnowledgeEvidence,
} from "../api/knowledgeTasks";
import { reportCorrection } from "../api/knowledgeTrust";
import Button from "../components/Button";
import { PageHeader, ProductPage } from "../components/ProductLayout";
import { formatBeijingTime } from "../utils/time";
import { maintenanceAgentHref } from "../navigation/agentRoutes";
import "./KnowledgeTaskWorkspace.css";

const states = {
  queued: "已接单",
  searching: "查找资料中",
  checking: "核对版本中",
  ready: "已找到资料",
  empty: "需补充线索",
  failed: "未能完成",
};
const active = (s: KnowledgeTask["status"]) => ["queued", "searching", "checking"].includes(s);
const example = "帮我找一份适合制造业客户的访谈提纲，看看有没有新版，给我一份明天能用的。";
const message = (e: unknown) => (e instanceof Error ? e.message : "请求失败，请重试。");

export default function KnowledgeTaskWorkspace({ embedded = false }: { embedded?: boolean }) {
  const { authMe } = useAuth();
  return (
    <LibraryWorkspace
      key={JSON.stringify([authMe?.userId, authMe?.activeCompanyRole])}
      embedded={embedded}
    />
  );
}

function LibraryWorkspace({ embedded }: { embedded: boolean }) {
  const location = useLocation();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const key = params.get("library") || "company";
  const [libraries, setLibraries] = useState<AgentPolicy[]>([]);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  useEffect(() => {
    let alive = true;
    fetchAgentPolicies()
      .then((p) => {
        if (alive) {
          setLibraries(p);
          setError("");
        }
      })
      .catch((e) => {
        if (alive) setError(message(e));
      });
    return () => {
      alive = false;
    };
  }, [reload]);
  const policy = libraries.find((p) => p.library_key === key);
  return (
    <ProductPage className={`kt-workspace ${embedded ? "is-workspace-agent" : ""}`}>
      <PageHeader
        title={embedded ? "查找与交代任务" : "知识维护 Agent"}
        description="按用途找资料，核对当前版本，跟进需要维护的地方。"
        actions={
          <label className="kt-scope">
            知识库
            <select
              value={key}
              onChange={(e) => {
                const next = new URLSearchParams(params);
                next.set("tab", "tasks");
                next.set("library", e.target.value);
                ["target_id", "view", "page", "asset_id"].forEach((name) => next.delete(name));
                navigate(maintenanceAgentHref(next.toString(), {}, location.hash));
              }}
            >
              {libraries.map((p) => (
                <option key={p.library_key} value={p.library_key}>
                  {p.name}
                </option>
              ))}
            </select>
          </label>
        }
      />
      <nav className="agent-tabs kt-tabs" aria-label="知识维护视图">
        <span aria-current="page">交代任务</span>
        {[
          ["issues", "维护待办"],
          ["runs", "巡检记录"],
          ["settings", "巡检设置"],
        ].map(([tab, label]) => (
          <Link
            key={tab}
            to={maintenanceAgentHref(
              location.search,
              { library: key, tab, page: null },
              location.hash,
            )}
          >
            {label}
          </Link>
        ))}
      </nav>
      {error ? (
        <p role="alert">
          {error}{" "}
          <Button size="small" onClick={() => setReload((n) => n + 1)}>
            重试
          </Button>
        </p>
      ) : policy ? (
        <TaskBoard key={key} library={key} />
      ) : (
        <p role="status">{libraries.length ? "当前身份无法访问此知识库。" : "正在读取知识库…"}</p>
      )}
    </ProductPage>
  );
}

function TaskBoard({ library }: { library: string }) {
  const [input, setInput] = useState("");
  const [rows, setRows] = useState<KnowledgeTask[]>([]);
  const [selected, setSelected] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [listError, setListError] = useState("");
  const [revision, setRevision] = useState(0);
  const request = useRef({ text: "", id: "" });
  const editor = useRef<HTMLTextAreaElement>(null);
  const current = selected || rows[0]?.id;
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const load = async () => {
      try {
        const fresh = await recentTasks(library, controller.signal);
        if (controller.signal.aborted) return;
        setRows(fresh);
        setSelected((existing) => existing || fresh[0]?.id || "");
        setListError("");
        if (fresh.some((r) => active(r.status))) timer = setTimeout(load, 2500);
      } catch (e) {
        if (!controller.signal.aborted) setListError(message(e));
      }
    };
    void load();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [library, revision]);
  async function send() {
    const instruction = input.trim();
    if (busy || instruction.length < 2) return;
    if (request.current.text !== instruction)
      request.current = { text: instruction, id: createClientUuid() };
    setBusy(true);
    setError("");
    try {
      const row = await delegate(library, instruction, request.current.id);
      setRows((old) => [row, ...old.filter((t) => t.id !== row.id)]);
      setSelected(row.id);
      setInput("");
      request.current = { text: "", id: "" };
      setRevision((n) => n + 1);
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }
  function edit(value: string) {
    setInput(value);
    editor.current?.focus();
  }
  return (
    <div className="kt-board">
      <form
        className="kt-composer"
        onSubmit={(e) => {
          e.preventDefault();
          void send();
        }}
      >
        <label htmlFor="kt-instruction">交代一件事</label>
        <textarea
          ref={editor}
          id="kt-instruction"
          placeholder="想找什么资料，准备用在哪里？"
          value={input}
          maxLength={600}
          disabled={busy}
          onChange={(e) => setInput(e.target.value)}
        />
        <div className="kt-composer-actions">
          <button type="button" disabled={busy} onClick={() => edit(example)}>
            试一试：找制造业访谈提纲
          </button>
          <Button
            type="submit"
            variant="primary"
            disabled={busy || input.trim().length < 2}
            icon={<Send size={15} />}
          >
            {busy ? "提交中…" : "交给 Agent"}
          </Button>
        </div>
        {error && <p role="alert">{error}</p>}
      </form>
      <section className="kt-history">
        <h3>
          <History size={18} />
          最近交代的事
        </h3>
        {listError && (
          <p role="alert">
            {listError} <Button onClick={() => setRevision((n) => n + 1)}>重试</Button>
          </p>
        )}
        {!rows.length && !listError && (
          <p className="kt-muted">交代第一件事后，可以在这里查看进度和结果。</p>
        )}
        {rows.map((row) => (
          <div key={row.id} className="kt-item">
            <button
              type="button"
              className="kt-row"
              aria-expanded={current === row.id}
              onClick={() => setSelected(current === row.id ? "closed" : row.id)}
            >
              <span>{row.instruction}</span>
              <small>{formatBeijingTime(row.created_at)}</small>
              <b>{states[row.status]}</b>
            </button>
            {current === row.id && <TaskResult library={library} id={row.id} edit={edit} />}
          </div>
        ))}
      </section>
    </div>
  );
}

function TaskResult({
  library,
  id,
  edit,
}: {
  library: string;
  id: string;
  edit: (v: string) => void;
}) {
  const [data, setData] = useState<KnowledgeTaskDetail | null>(null);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const load = async () => {
      try {
        const fresh = await fetchTask(library, id, controller.signal);
        if (controller.signal.aborted) return;
        setData(fresh);
        setError("");
        if (active(fresh.status)) timer = setTimeout(load, 1750);
      } catch (e) {
        if (!controller.signal.aborted) {
          setError(message(e));
          setData(null);
        }
      }
    };
    void load();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [library, id, refresh]);
  if (error)
    return (
      <p role="alert">
        {error}{" "}
        <Button size="small" onClick={() => setRefresh((n) => n + 1)}>
          重试
        </Button>
      </p>
    );
  if (!data || active(data.status))
    return (
      <p className="kt-progress" role="status">
        {data ? states[data.status] : "读取任务中"}…
      </p>
    );
  return (
    <div className="kt-result">
      <p className="kt-trace">
        <Check size={14} />
        入选 {data.candidates} 份 · 核对 {data.inspected} 份
        {data.mode === "model"
          ? " · 模型参与选取"
          : data.mode === "model_unavailable"
            ? " · 模型暂不可用，已按目录匹配"
            : " · 目录匹配"}
      </p>
      {data.availability === "changed" && data.evidence && (
        <p>任务完成后资料已换版，已重新核对当前版本。</p>
      )}
      {data.evidence ? (
        <Evidence
          key={data.evidence.version_id}
          doc={data.evidence}
          refresh={() => setRefresh((n) => n + 1)}
        />
      ) : (
        <>
          <p>
            {data.availability === "changed"
              ? "资料已换版，请重新核对后使用。"
              : data.availability === "unavailable"
                ? "当前资料已不可访问。"
                : data.status === "failed"
                  ? data.failure_reason === "access_changed"
                    ? "执行期间知识库权限已变更，请重新选择可访问的知识库。"
                    : "查询资料时服务暂不可用，可以重新交代。"
                  : data.candidates
                    ? "找到相关线索，但未确认可推荐的当前版本。"
                    : "在当前知识库的可见标题和标签中未找到匹配。可以补充模板名、行业或标签。"}
          </p>
          <Button size="small" onClick={() => edit(data.instruction)}>
            调整后再找
          </Button>
        </>
      )}
    </div>
  );
}

function Evidence({ doc, refresh }: { doc: KnowledgeEvidence; refresh: () => void }) {
  const [draft, setDraft] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [sent, setSent] = useState(false);
  const suggested = doc.pending_update
    ? "请核对待采用版本与当前版本的差异，确认可采用后更新资料。"
    : doc.old_source_links.length
      ? "本库有资料的来源仍指向已替代版本，请核对关联并更新适用的资料。"
      : doc.needs_update
        ? "此资料已标记待更新，请核对当前版本并补充最新内容。"
        : "请核对这份资料是否仍适用。";
  async function confirm() {
    if (!draft?.trim() || sending) return;
    setSending(true);
    setError("");
    try {
      await reportCorrection(doc.asset_id, {
        expected_updated_at: doc.updated_at,
        reason: draft.trim(),
      });
      setDraft(null);
      setSent(true);
      refresh();
    } catch (e) {
      setError(message(e));
    } finally {
      setSending(false);
    }
  }
  const corrections: Record<string, string> = {
    open: "待维护人处理",
    resolved: "已处理，待验证",
    verified: "验证通过",
    rejected: "已驳回",
    duplicate: "已归并",
    withdrawn: "已撤回",
  };
  return (
    <article className="kt-evidence">
      <div className="kt-document">
        <FileText size={20} />
        <strong>{doc.title}</strong>
        <span>{doc.version}</span>
      </div>
      <p>
        {doc.matched.length
          ? `标题或标签匹配「${doc.matched.join("」「")}」。`
          : "已找到关联资料。"}
        已核对为当前采用版本。
      </p>
      {doc.summary && <blockquote>{doc.summary}</blockquote>}
      {!!doc.summary_matched.length && (
        <p>可见摘要中提到「{doc.summary_matched.join("」「")}」。</p>
      )}
      {!!doc.unmatched.length && <p>尚无依据确认「{doc.unmatched.join("」「")}」也匹配。</p>}
      {!!doc.old_source_links.length && (
        <details>
          <summary>查看本库仍关联旧资料的条目</summary>
          <ul>
            {doc.old_source_links.map((item) => (
              <li key={item.asset_id}>
                <Link
                  to={`/knowledge/${item.asset_id}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  title="在 KAP 新标签页查看知识资料"
                >
                  {item.title}
                  <span className="agent-reference-hint" aria-hidden="true">
                    {" "}
                    · KAP ↗
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </details>
      )}
      {!doc.original && <p>当前身份可打开资料详情，原文需要授权。</p>}
      {!doc.parsed && <p>尚未确认正文解析完成。本次依据为标题、标签及可见摘要。</p>}
      {doc.pending_update && <p>还有关联新版待处理，使用前可先请维护人确认。</p>}
      {doc.needs_update && <p>这份资料已标记为待更新。</p>}
      {doc.history_truncated && <p>可见版本记录较多，本次只核对了部分历史。</p>}
      {doc.compared_version ? (
        <details>
          <summary>
            查看两版差异 · {doc.compared_version} → {doc.version}
          </summary>
          <p>
            {doc.changed_fields.length
              ? "变化的字段：" +
                doc.changed_fields
                  .map((x) => ({ version: "版本号", summary: "摘要", directory: "目录" })[x] || x)
                  .join("、")
              : "可见的摘要和版本字段一致。"}
          </p>
          <div className="kt-diff">
            {[
              [doc.compared_version, doc.previous_summary],
              [doc.version, doc.current_summary],
            ].map(([v, s], i) => (
              <div key={i}>
                <b>{v}</b>
                <p>{s || "无可展示摘要"}</p>
              </div>
            ))}
          </div>
        </details>
      ) : (
        <p className="kt-muted">可见版本记录中未找到可直接比较的上一版。</p>
      )}
      <div className="kt-actions">
        <Link
          to={`/knowledge/${doc.asset_id}`}
          target="_blank"
          rel="noopener noreferrer"
          title="在 KAP 新标签页查看知识资料"
        >
          <BookOpen size={15} />
          {doc.original ? "打开推荐资料" : "查看资料详情"}
          <span className="agent-reference-hint" aria-hidden="true">
            KAP ↗
          </span>
        </Link>
        {!(sent || ["open", "resolved"].includes(doc.correction_status || "")) &&
          draft === null && (
            <Button size="small" onClick={() => setDraft(suggested)}>
              预览更新建议
            </Button>
          )}
      </div>
      {(doc.correction_status || sent) && (
        <p role="status">
          我提交的维护建议 · {corrections[doc.correction_status || "open"] || "已记录"}
        </p>
      )}
      {draft !== null && (
        <div className="kt-draft">
          <label>
            给维护人的更新建议
            <textarea
              maxLength={1000}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              disabled={sending}
            />
          </label>
          <div className="kt-actions">
            <Button
              size="small"
              variant="primary"
              disabled={sending || !draft.trim()}
              onClick={() => void confirm()}
              icon={<ArrowRight size={14} />}
            >
              确认提交给维护人
            </Button>
            <Button
              size="small"
              disabled={sending}
              onClick={() => {
                setDraft(null);
                setError("");
              }}
            >
              取消
            </Button>
          </div>
          {error && <p role="alert">{error}</p>}
        </div>
      )}
    </article>
  );
}
