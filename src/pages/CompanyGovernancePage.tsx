import { useCallback, useEffect, useRef, useState } from "react";
import {
  Archive,
  ArrowUpRight,
  FileText,
  RotateCcw,
  Search,
  SlidersHorizontal,
} from "lucide-react";
import { Link } from "react-router-dom";
import { apiGet } from "../api/http";
import {
  applyGovernance,
  fetchGovernance,
  type BatchResult,
  type GovernanceItem,
  type GovernancePage,
  type ReasonCode,
} from "../api/governance";
import DetailDrawer from "../components/DetailDrawer";
import TaskModal from "../components/TaskModal";
import "./CompanyGovernancePage.css";

const signals: Record<string, string> = {
  same_title: "同名待核验",
  draft: "过程稿",
  policy_age: "法规时效待核验",
  research_age: "历史研究",
  content_check: "内容待检查",
  needs_update: "需要处理",
};
const reasons: Record<ReasonCode, string> = {
  historical: "历史参考",
  superseded: "新版替代",
  duplicate: "重复资料",
  low_value: "低价值内容",
  other: "其他",
};
const statuses: Record<string, string> = {
  active: "已入库",
  needs_update: "需要处理",
  deprecated: "已停用",
  archived: "已归档",
};
const date = (v: string | null) => (v ? new Date(v).toLocaleDateString("zh-CN") : "—");
type Event = {
  event_id: string;
  event_type: string;
  reason: string | null;
  actor_display: string | null;
  created_at: string;
};
const eventNames: Record<string, string> = {
  archived: "归档",
  reenabled: "恢复",
  archive_warning: "预警",
  archive_candidate: "归档候选",
  reenable_requested: "申请恢复",
  status_changed: "状态变更",
};

export default function CompanyGovernancePage() {
  const [view, setView] = useState("candidates");
  const [signal, setSignal] = useState("");
  const [input, setInput] = useState("");
  const [keyword, setKeyword] = useState("");
  const [page, setPage] = useState(1);
  const [data, setData] = useState<GovernancePage | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<GovernanceItem[]>([]);
  const [detail, setDetail] = useState<GovernanceItem | null>(null);
  const [events, setEvents] = useState<Event[]>([]);
  const [eventStatus, setEventStatus] = useState("");
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [reason, setReason] = useState("");
  const [code, setCode] = useState<ReasonCode>("historical");
  const [replacement, setReplacement] = useState("");
  const [result, setResult] = useState<BatchResult | null>(null);
  const [actionError, setActionError] = useState("");
  const serial = useRef(0);
  const archived = view === "archived";
  const load = useCallback(async () => {
    const n = ++serial.current;
    setLoading(true);
    setError("");
    setSelected([]);
    try {
      const r = await fetchGovernance(view, signal, keyword, page);
      if (n === serial.current) setData(r);
    } catch {
      if (n === serial.current) {
        setData(null);
        setError("无法读取治理清单，请检查权限或重试。");
      }
    } finally {
      if (n === serial.current) setLoading(false);
    }
  }, [view, signal, keyword, page]);
  useEffect(() => {
    void load();
    const requestNumber = serial.current;
    return () => {
      serial.current = requestNumber + 1;
    };
  }, [load]);
  useEffect(() => {
    if (!detail) return;
    let active = true;
    setEvents([]);
    setEventStatus("正在读取历史…");
    apiGet<{ items: Event[] }>(`/api/v1/knowledge/${detail.asset_id}/lifecycle/events`)
      .then((r) => {
        if (active) {
          setEvents(r.items);
          setEventStatus(r.items.length ? "" : "暂无治理记录");
        }
      })
      .catch(() => {
        if (active) setEventStatus("历史记录读取失败，请关闭后重试。");
      });
    return () => {
      active = false;
    };
  }, [detail]);
  const changeView = (next: string) => {
    setView(next);
    setSignal("");
    setPage(1);
    setSelected([]);
    setResult(null);
  };
  const toggle = (item: GovernanceItem) =>
    setSelected((prev) =>
      prev.some((s) => s.asset_id === item.asset_id)
        ? prev.filter((s) => s.asset_id !== item.asset_id)
        : [...prev, item],
    );
  async function execute() {
    if (busy || !reason.trim() || !selected.length) return;
    setBusy(true);
    setActionError("");
    try {
      const r = await applyGovernance(
        selected,
        archived ? "restore" : "archive",
        code,
        reason.trim(),
        !archived && code === "superseded" ? replacement.trim() : undefined,
      );
      setResult(r);
      setConfirm(false);
      setDetail(null);
      setReason("");
      setReplacement("");
      await load();
    } catch {
      setActionError("未能确认执行结果。请关闭预览并刷新清单，核对状态后再操作。");
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="cg-page">
      <header className="cg-header">
        <div>
          <h1>公司库治理</h1>
          <p>让有效知识留在工作中，让历史资料有处可查。</p>
        </div>
        <Link to="/knowledge?scope=company">
          浏览公司库 <ArrowUpRight size={16} />
        </Link>
      </header>
      <section className="cg-overview" aria-label="治理概览">
        <div className="cg-overview-intro">
          <Archive size={28} />
          <h2>整理知识，保留价值。</h2>
          <p>候选由文件标题和安全摘要生成。逐项核验后处理，历史资料可随时恢复。</p>
        </div>
        <div className="cg-meters">
          {[
            ["all", "在库资料"],
            ["candidates", "待核验候选"],
            ["archived", "已归档"],
          ].map(([key, label]) => (
            <button key={key} onClick={() => changeView(key)} aria-pressed={view === key}>
              <strong>{data ? (data.counts[key]?.toLocaleString() ?? 0) : "—"}</strong>
              <span>{label}</span>
            </button>
          ))}
        </div>
      </section>
      <section className="cg-workspace" aria-label="文件治理工作台">
        <div className="cg-tabs">
          {[
            ["candidates", "待核验"],
            ["all", "全部在库"],
            ["archived", "归档中心"],
          ].map(([key, label]) => (
            <button key={key} aria-pressed={view === key} onClick={() => changeView(key)}>
              {label}
            </button>
          ))}
          <button className="cg-refresh" onClick={() => void load()} disabled={loading}>
            <RotateCcw size={15} />
            刷新
          </button>
        </div>
        <form
          className="cg-filters"
          onSubmit={(e) => {
            e.preventDefault();
            setPage(1);
            setKeyword(input);
          }}
        >
          <div className="cg-search">
            <Search size={17} />
            <input
              aria-label="搜索资料"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="搜索文件名称、摘要或资产 ID"
              maxLength={200}
            />
            <button type="submit">搜索</button>
          </div>
          <label>
            <SlidersHorizontal size={16} />
            <select
              aria-label="候选原因"
              value={signal}
              onChange={(e) => {
                setSignal(e.target.value);
                setPage(1);
              }}
            >
              {<option value="">全部原因</option>}
              {Object.entries(signals).map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
          </label>
        </form>
        <div className="cg-context">
          <span>
            {archived
              ? "归档资料不参与默认检索与问答；恢复后重新进入在库范围。"
              : "同名和年代较早仅为核验线索，不代表重复或失效。"}
          </span>
          <span>{data?.total ?? 0} 项</span>
        </div>
        {result && (
          <div className="cg-result" role="status">
            本批完成 {result.items.filter((i) => i.success).length} 项，未完成{" "}
            {result.items.filter((i) => !i.success).length} 项。
            {result.items
              .filter((i) => !i.success)
              .map((i) => (
                <p key={i.asset_id}>
                  {i.asset_id}：{i.message}
                </p>
              ))}
          </div>
        )}
        {error ? (
          <div className="cg-empty" role="alert">
            {error}
            <button onClick={() => void load()}>重试</button>
          </div>
        ) : loading ? (
          <div className="cg-empty" role="status">
            正在读取公司资料…
          </div>
        ) : !data?.items.length ? (
          <div className="cg-empty">
            <Archive size={28} />
            <h3>{archived ? "暂无匹配的归档资料" : "暂无匹配的资料"}</h3>
            <p>试试其他筛选条件，或查看全部在库资料。</p>
          </div>
        ) : (
          <div className="cg-table-wrap">
            <table>
              <thead>
                <tr>
                  <th>
                    <input
                      type="checkbox"
                      aria-label="选择本页全部资料"
                      checked={selected.length === data.items.length}
                      onChange={(e) => setSelected(e.target.checked ? data.items : [])}
                    />
                  </th>
                  <th>文件</th>
                  <th>核验提示</th>
                  <th>{archived ? "归档日期" : "记录更新"}</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((item) => (
                  <tr
                    key={item.asset_id}
                    className={
                      selected.some((s) => s.asset_id === item.asset_id) ? "is-selected" : ""
                    }
                  >
                    <td>
                      <input
                        type="checkbox"
                        aria-label={`选择 ${item.title}`}
                        checked={selected.some((s) => s.asset_id === item.asset_id)}
                        onChange={() => toggle(item)}
                      />
                    </td>
                    <td>
                      <div className="cg-file">
                        <span className="cg-file-icon">
                          <FileText size={19} />
                        </span>
                        <div>
                          <button className="cg-file-title" onClick={() => setDetail(item)}>
                            {item.title}
                          </button>
                          <small>
                            {item.confidentiality_level} /{" "}
                            {statuses[item.asset_status] ?? item.asset_status}
                          </small>
                        </div>
                      </div>
                    </td>
                    <td>
                      {item.signals.length ? (
                        item.signals.map((s) => (
                          <span className="cg-tag" key={s}>
                            {signals[s] ?? s}
                          </span>
                        ))
                      ) : (
                        <span className="cg-muted">未命中候选规则</span>
                      )}
                    </td>
                    <td className="cg-date">
                      {date(archived ? item.archived_at : item.updated_at)}
                    </td>
                    <td>
                      <button className="cg-inspect" onClick={() => setDetail(item)}>
                        核验
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <footer className="cg-bottom">
          <span>已选 {selected.length} 项（本页）</span>
          <button
            className="cg-primary"
            disabled={!selected.length || loading}
            onClick={() => {
              setConfirm(true);
              setActionError("");
              setCode(archived ? "other" : "historical");
            }}
          >
            {archived ? <RotateCcw size={16} /> : <Archive size={16} />}{" "}
            {archived ? "预览恢复" : "预览归档"}
          </button>
          <div className="cg-pagination">
            <button disabled={page === 1 || loading} onClick={() => setPage((p) => p - 1)}>
              上一页
            </button>
            <span>
              {page} / {Math.max(1, Math.ceil((data?.total ?? 0) / 25))}
            </span>
            <button
              disabled={loading || page * 25 >= (data?.total ?? 0)}
              onClick={() => setPage((p) => p + 1)}
            >
              下一页
            </button>
          </div>
        </footer>
      </section>
      <DetailDrawer open={!!detail} title={detail?.title} onClose={() => setDetail(null)}>
        {detail && (
          <div className="cg-detail">
            <span className="cg-tag">{statuses[detail.asset_status]}</span>
            <h3>安全摘要</h3>
            <p>{detail.summary || "暂无可展示的安全摘要，请先补齐摘要再核验。"}</p>
            <h3>处理线索</h3>
            <p>{detail.signals.map((s) => signals[s]).join("、") || "未命中候选规则"}</p>
            <p className="cg-muted">
              同名文件须核对版本与内容；正文缺失须先检查解析；历史研究应保留数据截至日期。
            </p>
            {detail.archive_reason && (
              <>
                <h3>最近归档原因</h3>
                <p className="cg-pre">{detail.archive_reason}</p>
              </>
            )}
            <h3>治理记录</h3>
            <p>{eventStatus}</p>
            <ol>
              {events.map((e) => (
                <li key={e.event_id}>
                  <strong>{eventNames[e.event_type] ?? "生命周期事件"}</strong>
                  <small>
                    {date(e.created_at)} / {e.actor_display || "系统"}
                  </small>
                  <p className="cg-pre">{e.reason || "未填写原因"}</p>
                </li>
              ))}
            </ol>
            <small className="cg-id">资产 ID：{detail.asset_id}</small>
          </div>
        )}
      </DetailDrawer>
      <TaskModal
        open={confirm}
        title={`${archived ? "恢复" : "归档"} ${selected.length} 份资料`}
        description={
          archived
            ? "恢复为已入库状态，重新参与默认检索与问答。"
            : "归档后退出默认检索与问答，原文件与历史记录保留。"
        }
        onClose={() => !busy && setConfirm(false)}
        busy={busy}
        size="large"
        footer={
          <>
            <button disabled={busy} onClick={() => setConfirm(false)}>
              取消
            </button>
            <button
              className="cg-primary"
              disabled={
                busy ||
                !reason.trim() ||
                (!archived && code === "superseded" && !replacement.trim())
              }
              onClick={() => void execute()}
            >
              {busy ? "正在处理…" : `确认${archived ? "恢复" : "归档"}`}
            </button>
          </>
        }
      >
        <div className="cg-confirm">
          <ul>
            {selected.map((i) => (
              <li key={i.asset_id}>{i.title}</li>
            ))}
          </ul>
          <label>
            处理类型
            <select
              value={code}
              disabled={busy}
              onChange={(e) => setCode(e.target.value as ReasonCode)}
            >
              {Object.entries(reasons).map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          {!archived && code === "superseded" && (
            <label>
              替代资产 ID
              <input
                value={replacement}
                disabled={busy}
                onChange={(e) => setReplacement(e.target.value)}
                placeholder="有效公司知识的资产 ID"
              />
            </label>
          )}
          <label>
            处理原因（必填）
            <textarea
              rows={3}
              maxLength={1000}
              value={reason}
              disabled={busy}
              onChange={(e) => setReason(e.target.value)}
              placeholder="说明核验依据、替代版本或恢复用途"
            />
          </label>
          <p className="cg-muted">
            每份资料独立核验并记录结果。清单生成后已变更的资料会跳过，请刷新后重新核验。
          </p>
          {actionError && <p role="alert">{actionError}</p>}
        </div>
      </TaskModal>
    </main>
  );
}
