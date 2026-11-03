import PagePagination from "../components/PagePagination";
import ListWorkspace from "../components/ListWorkspace";
import { ProductPage, PageHeader } from "../components/ProductLayout";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  Archive,
  ArrowUpRight,
  FileText,
  RotateCcw,
  Search,
  SlidersHorizontal,
  Settings,
} from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";
import { CompanyKnowledgeBaseSettings } from "./AdminCompanyKbPage";
import { fetchLifecycleEvents } from "../api/knowledge";
import {
  applyGovernance,
  fetchGovernance,
  type BatchResult,
  type GovernanceItem,
  type GovernancePage,
  type ReasonCode,
} from "../api/governance";
import { ActionGroup } from "../components/ActionLayout";
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
  const [params, setParams] = useSearchParams();
  const settingsOpen = params.get("settings") === "knowledge-base";
  const [settingsBusy, setSettingsBusy] = useState(false);
  const showSettings = (open: boolean) => {
    if (settingsBusy) return;
    setParams(
      (current) => {
        const next = new URLSearchParams(current);
        if (open) next.set("settings", "knowledge-base");
        else next.delete("settings");
        return next;
      },
      { replace: true },
    );
  };
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
    fetchLifecycleEvents(detail.asset_id)
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
    <ProductPage className="cg-page admin-control-page">
      <PageHeader
        title="公司库治理"
        description="根据资料标题与安全摘要逐项核验，管理在库与归档资料。"
        actions={
          <>
            <Link className="product-button is-secondary" to="/knowledge?scope=company">
              浏览公司库 <ArrowUpRight size={16} />
            </Link>
            <button
              type="button"
              className="product-button is-secondary"
              onClick={() => showSettings(true)}
            >
              <Settings size={16} aria-hidden="true" /> 设置
            </button>
          </>
        }
      />
      <ListWorkspace className="cg-workspace" label="文件治理工作台">
        <div className="cg-tabs" role="group" aria-label="公司库治理视图">
          {[
            ["candidates", "待核验"],
            ["all", "全部在库"],
            ["archived", "归档中心"],
          ].map(([key, label]) => (
            <button
              key={key}
              aria-label={label}
              aria-pressed={view === key}
              onClick={() => changeView(key)}
            >
              {label}
              <span className="list-tab-count">{data ? (data.counts[key] ?? 0) : "—"}</span>
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
          <span>{loading ? "正在读取…" : data ? `${data.total} 项` : ""}</span>
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
            <h3>
              {keyword || signal
                ? "暂无匹配的资料"
                : view === "candidates"
                  ? "暂无待核验资料"
                  : archived
                    ? "暂无归档资料"
                    : "公司库暂无资料"}
            </h3>
            <p>
              {keyword || signal
                ? "调整搜索或筛选条件后重试。"
                : view === "candidates"
                  ? "可切换到全部在库，查看公司资料。"
                  : archived
                    ? "归档后的资料会显示在这里。"
                    : "资料完成公司发布后，会显示在这里。"}
            </p>
            {(keyword || signal) && (
              <button
                className="product-button is-secondary"
                onClick={() => {
                  setInput("");
                  setKeyword("");
                  setSignal("");
                  setPage(1);
                }}
              >
                清除筛选
              </button>
            )}
          </div>
        ) : (
          <div className="cg-table-wrap">
            <table data-responsive-table>
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
                    <td data-label="文件">
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
                    <td data-label="核验提示">
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
                    <td data-label="操作">
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
        {(selected.length > 0 || (data?.total ?? 0) > 25 || page > 1) && (
          <footer className="cg-bottom">
            {selected.length > 0 && (
              <ActionGroup label="所选资料操作">
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
              </ActionGroup>
            )}
            {((data?.total ?? 0) > 25 || page > 1) && (
              <PagePagination
                ariaLabel="公司资料治理分页"
                page={page}
                totalPages={Math.ceil((data?.total ?? 0) / 25)}
                disabled={loading}
                onPageChange={setPage}
              />
            )}
          </footer>
        )}
      </ListWorkspace>
      <DetailDrawer
        open={!!detail}
        title={detail?.title}
        onClose={() => setDetail(null)}
        footer={
          detail && (
            <ActionGroup
              label="当前资料治理操作"
              primary={
                <button
                  className="cg-primary"
                  disabled={loading || busy}
                  onClick={() => {
                    setSelected([detail]);
                    setDetail(null);
                    setConfirm(true);
                    setActionError("");
                    setCode(archived ? "other" : "historical");
                  }}
                >
                  {archived ? "预览恢复" : "预览归档"}
                </button>
              }
              secondary={
                <button className="btn-small" onClick={() => setDetail(null)}>
                  返回列表
                </button>
              }
            />
          )
        }
      >
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
      <TaskModal
        open={settingsOpen}
        title="公司库设置"
        description="查看知识库状态，管理初始化与维护操作。"
        closeLabel="关闭公司库设置"
        size="medium"
        busy={settingsBusy}
        onClose={() => showSettings(false)}
      >
        {settingsOpen && <CompanyKnowledgeBaseSettings onBusyChange={setSettingsBusy} />}
      </TaskModal>
    </ProductPage>
  );
}
