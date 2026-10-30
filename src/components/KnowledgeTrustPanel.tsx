import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ApiError } from "../api/http";
import {
  fetchTrust,
  fetchReplacementOptions,
  reportCorrection,
  replaceTrust,
  reviewTrust,
  saveTrustPolicy,
  transitionCorrection,
  type TrustState,
} from "../api/knowledgeTrust";
import { formatBeijingTime } from "../utils/time";
import TaskModal from "./TaskModal";
import "./KnowledgeTrustPanel.css";

const freshnessLabels: Record<TrustState["freshness"], string> = {
  unreviewed: "尚未复核",
  verified: "已复核",
  changed: "修改后待复核",
  due: "已到复核日期",
  needs_update: "需要更新",
  archived: "已归档或停用",
};
const correctionLabels = { open: "待处理", resolved: "待提出者验证", verified: "已验证解决" };

interface KnowledgeTrustPanelProps {
  assetId: string;
  revision?: string;
  onChanged?: (state: TrustState) => void;
}

export default function KnowledgeTrustPanel(props: KnowledgeTrustPanelProps) {
  const [params, setParams] = useSearchParams();
  const requestedSection = params.get("maintenance");
  const section = ["review", "corrections", "verify"].includes(requestedSection ?? "")
    ? requestedSection
    : null;
  const [open, setOpen] = useState(Boolean(section));
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setOpen(Boolean(section));
  }, [props.assetId, section]);

  return (
    <>
      <button
        type="button"
        className="btn-secondary"
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => setOpen(true)}
      >
        知识维护与复核
      </button>
      <TaskModal
        open={open}
        title="知识维护与复核"
        description="安排复核、处理旧版或反馈资料问题。"
        size="large"
        portal
        busy={busy}
        onClose={() => {
          setOpen(false);
          if (section)
            setParams(
              (previous) => {
                const next = new URLSearchParams(previous);
                next.delete("maintenance");
                return next;
              },
              { replace: true },
            );
        }}
      >
        {open && (
          <KnowledgeTrustContent {...props} initialSection={section} onBusyChange={setBusy} />
        )}
      </TaskModal>
    </>
  );
}

function KnowledgeTrustContent({
  assetId,
  revision,
  onChanged,
  onBusyChange,
  initialSection,
}: KnowledgeTrustPanelProps & {
  onBusyChange: (busy: boolean) => void;
  initialSection: string | null;
}) {
  const [state, setState] = useState<TrustState | null>(null);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [owner, setOwner] = useState("");
  const [due, setDue] = useState("");
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const sectionRef = useRef<HTMLElement>(null);
  const focusedSection = useRef(false);
  const [replacementId, setReplacementId] = useState("");
  const [replacementQuery, setReplacementQuery] = useState("");
  const [replacementOptions, setReplacementOptions] = useState<
    { asset_id: string; title: string }[]
  >([]);
  const [candidate, setCandidate] = useState<TrustState | null>(null);
  const [confirmArchive, setConfirmArchive] = useState(false);
  const generation = useRef(0);
  const lock = useRef(false);
  const candidateRequest = useRef(0);

  useEffect(() => {
    const current = ++generation.current;
    setState(null);
    setError("");
    setNote("");
    setCandidate(null);
    setReplacementId("");
    setReplacementQuery("");
    setReplacementOptions([]);
    setReasons({});
    setConfirmArchive(false);
    setDue("");
    void fetchTrust(assetId)
      .then((result) => {
        if (generation.current !== current) return;
        setState(result);
        setOwner(result.maintainer_user_id ?? "");
        if (result.review_due_at) {
          const date = new Date(result.review_due_at);
          date.setMinutes(date.getMinutes() - date.getTimezoneOffset());
          setDue(date.toISOString().slice(0, 16));
        }
      })
      .catch((e: unknown) => {
        if (generation.current === current)
          setError(e instanceof ApiError ? e.message : "复核信息加载失败，请重试。");
      });
    return () => {
      generation.current = current + 1;
    };
  }, [assetId, revision]);

  useEffect(() => {
    if (!state || !initialSection || focusedSection.current) return;
    const target = sectionRef.current?.querySelector<HTMLElement>(
      initialSection === "review" ? "#trust-review-heading" : "#trust-corrections-heading",
    );
    target?.focus();
    target?.scrollIntoView?.({ block: "nearest" });
    focusedSection.current = true;
  }, [state, initialSection]);

  async function run(action: () => Promise<TrustState>, message: string, reasonKey?: string) {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    onBusyChange(true);
    setError("");
    setNote("");
    const current = generation.current;
    try {
      const result = await action();
      if (generation.current === current) {
        setState(result);
        setNote(message);
        if (reasonKey) setReasons((current) => ({ ...current, [reasonKey]: "" }));
        // Parent reload invalidates metadata editors opened before this governance change.
        onChanged?.(result);
      }
    } catch (e) {
      if (generation.current === current)
        setError(e instanceof ApiError ? e.message : "操作未完成，请重试。");
    } finally {
      lock.current = false;
      setBusy(false);
      onBusyChange(false);
    }
  }

  if (!state)
    return (
      <section className="knowledge-trust" aria-label="知识维护与复核">
        <p role="status">{error || "加载复核信息…"}</p>
        {error && (
          <button type="button" onClick={() => void run(() => fetchTrust(assetId), "已刷新")}>
            重新加载复核信息
          </button>
        )}
      </section>
    );
  const body = (key: string) => ({
    expected_updated_at: state.updated_at,
    reason: reasons[key] ?? "",
  });
  const valid = (key: string) => Boolean(reasons[key]?.trim()) && !busy;
  const reasonField = (key: string, label: string) => (
    <label className="knowledge-trust-reason">
      {label}（必填）
      <textarea
        value={reasons[key] ?? ""}
        maxLength={1000}
        disabled={busy}
        onChange={(event) => setReasons((current) => ({ ...current, [key]: event.target.value }))}
      />
    </label>
  );
  const active = state.freshness !== "archived";
  const deadline = due && !Number.isNaN(Date.parse(due)) ? new Date(due).toISOString() : null;

  return (
    <section
      ref={sectionRef}
      className="knowledge-trust"
      aria-label="知识维护与复核"
      aria-busy={busy}
    >
      <header>
        <h3>复核状态</h3>
        <span>{freshnessLabels[state.freshness]}</span>
      </header>
      <dl>
        <div>
          <dt>维护人</dt>
          <dd>{state.maintainer_name ?? "尚未指定"}</dd>
        </div>
        <div>
          <dt>下次复核</dt>
          <dd>{state.review_due_at ? formatBeijingTime(state.review_due_at) : "尚未安排"}</dd>
        </div>
        <div>
          <dt>最近复核</dt>
          <dd>{state.verified_at ? formatBeijingTime(state.verified_at) : "暂无记录"}</dd>
        </div>
      </dl>
      <p>到期只提醒复核，不自动归档。资料修改后需要重新复核。</p>
      {state.replacement_asset_id && (
        <p>
          该资料已被新版替代：
          <Link to={`/knowledge/${state.replacement_asset_id}`}>查看当前新版</Link>
        </p>
      )}
      {error && <p role="alert">{error}</p>}
      {note && <p role="status">{note}</p>}
      {active && (
        <div className="knowledge-trust-task">
          <h3>提出新的纠错</h3>
          {reasonField("report", "纠错问题")}
          <button
            type="button"
            disabled={!valid("report")}
            onClick={() =>
              void run(
                () => reportCorrection(assetId, body("report")),
                "纠错已提交，处理后需要你再次验证。",
                "report",
              )
            }
          >
            提出纠错
          </button>
        </div>
      )}
      {state.can_manage && (
        <details open={initialSection === "review" || undefined}>
          <summary>安排复核与处理旧版</summary>
          <h3 id="trust-review-heading" tabIndex={-1}>
            维护安排与复核
          </h3>
          {active && (
            <>
              <div className="knowledge-trust-fields">
                <label>
                  维护人
                  <select value={owner} onChange={(e) => setOwner(e.target.value)}>
                    <option value="">请选择维护人</option>
                    {state.maintainers.map((person) => (
                      <option key={person.id} value={person.id}>
                        {person.name}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  下次复核日期
                  <input
                    type="datetime-local"
                    value={due}
                    onChange={(e) => setDue(e.target.value)}
                  />
                </label>
              </div>
              {reasonField("policy", "维护安排说明")}
              <div className="knowledge-trust-actions">
                <button
                  type="button"
                  disabled={!valid("policy") || !owner || !deadline}
                  onClick={() =>
                    void run(
                      () =>
                        saveTrustPolicy(assetId, {
                          ...body("policy"),
                          maintainer_user_id: owner,
                          review_due_at: deadline,
                        }),
                      "维护责任和复核日期已保存。",
                      "policy",
                    )
                  }
                >
                  保存维护安排
                </button>
              </div>
              {reasonField("review", "复核结论说明")}
              <div className="knowledge-trust-actions">
                <button
                  type="button"
                  disabled={!valid("review") || !deadline || !state.maintainer_user_id}
                  onClick={() =>
                    void run(
                      () =>
                        reviewTrust(assetId, {
                          ...body("review"),
                          outcome: "verified",
                          next_review_at: deadline,
                        }),
                      "复核已通过。",
                      "review",
                    )
                  }
                >
                  确认复核通过
                </button>
                <button
                  type="button"
                  disabled={!valid("review") || !state.maintainer_user_id}
                  onClick={() =>
                    void run(
                      () => reviewTrust(assetId, { ...body("review"), outcome: "needs_update" }),
                      "已标记需要更新，请编辑资料或关联新版。",
                      "review",
                    )
                  }
                >
                  标记需要更新
                </button>
              </div>
              <h3>关联新版与归档</h3>
              {reasonField("replacement", "替代关系说明")}
              <label>
                查找新版资料
                <input
                  value={replacementQuery}
                  onChange={(e) => {
                    setReplacementQuery(e.target.value);
                    candidateRequest.current++;
                    setReplacementOptions([]);
                    setCandidate(null);
                    setReplacementId("");
                    setConfirmArchive(false);
                  }}
                  placeholder="输入新版资料标题关键词"
                  maxLength={200}
                />
              </label>
              <button
                type="button"
                disabled={busy}
                onClick={async () => {
                  const current = generation.current;
                  const request = ++candidateRequest.current;
                  setError("");
                  setCandidate(null);
                  setReplacementId("");
                  setConfirmArchive(false);
                  try {
                    const result = await fetchReplacementOptions(assetId, replacementQuery);
                    if (generation.current === current && candidateRequest.current === request) {
                      setReplacementOptions(result);
                      if (!result.length) setNote("没有符合条件的新版，请先完成入库并复核。");
                    }
                  } catch (e) {
                    if (generation.current === current && candidateRequest.current === request)
                      setError(e instanceof ApiError ? e.message : "新版查找失败。");
                  }
                }}
              >
                查找可关联新版
              </button>
              <label>
                新版资料
                <select
                  value={replacementId}
                  onChange={(e) => {
                    setReplacementId(e.target.value);
                    candidateRequest.current++;
                    setCandidate(null);
                    setConfirmArchive(false);
                  }}
                >
                  <option value="">请选择已复核新版</option>
                  {replacementOptions.map((item) => (
                    <option key={item.asset_id} value={item.asset_id}>
                      {item.title}
                    </option>
                  ))}
                </select>
              </label>
              <button
                type="button"
                disabled={busy || !replacementId.trim()}
                onClick={async () => {
                  setError("");
                  const current = generation.current;
                  const request = ++candidateRequest.current;
                  try {
                    const result = await fetchTrust(replacementId.trim());
                    if (generation.current === current && candidateRequest.current === request)
                      setCandidate(result);
                  } catch (e) {
                    if (generation.current === current)
                      setError(e instanceof ApiError ? e.message : "新版读取失败。");
                  }
                }}
              >
                核对新版
              </button>
              {candidate && (
                <p>
                  新版状态：{freshnessLabels[candidate.freshness]}。
                  <Link to={`/knowledge/${candidate.asset_id}`}>打开新版核对内容</Link>
                </p>
              )}
              <label className="knowledge-trust-confirm">
                <input
                  type="checkbox"
                  checked={confirmArchive}
                  onChange={(e) => setConfirmArchive(e.target.checked)}
                />
                我已核对新版，确认将当前旧版归档并退出默认检索。
              </label>
              <button
                type="button"
                disabled={
                  !valid("replacement") ||
                  !candidate ||
                  candidate.freshness !== "verified" ||
                  !confirmArchive
                }
                onClick={() =>
                  void run(
                    () =>
                      replaceTrust(assetId, {
                        ...body("replacement"),
                        replacement_asset_id: candidate?.asset_id,
                        expected_replacement_updated_at: candidate?.updated_at,
                        confirm_archive: true,
                      }),
                    "已关联新版并归档旧版。",
                    "replacement",
                  )
                }
              >
                关联新版并归档旧版
              </button>
            </>
          )}
          {state.replacement_asset_id && (
            <div>
              {reasonField("replacement", "替代关系说明")}
              <button
                type="button"
                disabled={!valid("replacement")}
                onClick={() =>
                  void run(
                    () =>
                      replaceTrust(assetId, { ...body("replacement"), replacement_asset_id: null }),
                    "替代关系已撤销，旧版仍保持归档，需要单独确认启用。",
                    "replacement",
                  )
                }
              >
                撤销替代关系（不自动启用）
              </button>
            </div>
          )}
        </details>
      )}
      <h3 id="trust-corrections-heading" tabIndex={-1}>
        资料纠错
      </h3>
      {!state.corrections.length && <p>暂无你可查看的纠错记录。</p>}
      {state.corrections.map((item) => (
        <article key={item.id}>
          <strong>{correctionLabels[item.status]}</strong>
          <p>{item.description}</p>
          {item.resolution && <p>处理说明：{item.resolution}</p>}
          {(item.can_resolve || item.can_verify) &&
            reasonField(`correction:${item.id}`, `此条纠错的处理说明`)}
          {item.can_resolve && (
            <button
              type="button"
              disabled={!valid(`correction:${item.id}`)}
              onClick={() =>
                void run(
                  () =>
                    transitionCorrection(assetId, item.id, {
                      expected_updated_at: item.updated_at,
                      reason: reasons[`correction:${item.id}`] ?? "",
                      action: "resolve",
                    }),
                  "已处理，等待提出者验证。",
                  `correction:${item.id}`,
                )
              }
            >
              已更新，交给提出者验证
            </button>
          )}
          {item.can_verify && (
            <div className="knowledge-trust-actions">
              <button
                type="button"
                disabled={!valid(`correction:${item.id}`)}
                onClick={() =>
                  void run(
                    () =>
                      transitionCorrection(assetId, item.id, {
                        expected_updated_at: item.updated_at,
                        reason: reasons[`correction:${item.id}`] ?? "",
                        action: "verify",
                      }),
                    "纠错已验证解决。",
                    `correction:${item.id}`,
                  )
                }
              >
                验证已解决
              </button>
              <button
                type="button"
                disabled={!valid(`correction:${item.id}`)}
                onClick={() =>
                  void run(
                    () =>
                      transitionCorrection(assetId, item.id, {
                        expected_updated_at: item.updated_at,
                        reason: reasons[`correction:${item.id}`] ?? "",
                        action: "reopen",
                      }),
                    "已重新打开纠错，等待再次处理。",
                    `correction:${item.id}`,
                  )
                }
              >
                仍有问题，重新处理
              </button>
            </div>
          )}
        </article>
      ))}
    </section>
  );
}
