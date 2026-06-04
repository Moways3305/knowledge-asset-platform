import { useState, useMemo, useCallback, useEffect } from "react";
import { Link, useParams } from "react-router-dom";
import { projectQa, fetchAuthMe, fetchKnowledgeList, ApiError, type AuthMeVM } from "../api/client";
import type { ProjectQaResponseDTO } from "../types/agent";
import type { KnowledgeCardVM } from "../types/knowledge";

// 路由 :id 在导航里是路由兼容占位串（如 "current"），不是业务数据；真实项目 Q&A /
// 知识看板需要真实项目，因此从 /auth/me 的有效项目中解析"本次实际所在项目"。
const UUID_RE = /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/;

type ZoneType = "material" | "asset";

// 平台生命周期阶段的规范顺序（领域元数据，用于阶段排序展示；非业务数据）。
const LIFECYCLE_PHASES = [
  "售前", "诊断", "启动共识", "定题", "目标计划", "行动辅导", "阶段评估", "年度复盘", "专项诊断",
];
const UNLABELED_PHASE = "未标注阶段";

const visibilityLabel: Record<string, string> = {
  public: "公开",
  "project-only": "项目内",
  confidential: "机密",
};

const assetTypeLabel: Record<string, string> = {
  methodology: "方法论",
  deliverable: "交付物",
  case: "案例",
  template: "模板",
  insight: "洞察",
};


interface QAModel {
  id: string;
  name: string;
  tag: string;
}

// 问答模型选项：选择项映射为后端 model_key 真实传入 /projects/{id}/qa（影响本次问答，
// 回答仍由后端网关产生，非前端伪造结果）。
const qaModels: QAModel[] = [
  { id: "default", name: "系统默认模型", tag: "稳定" },
  { id: "deepseek-r1", name: "DeepSeek-R1 内网版", tag: "推理" },
  { id: "qwen-enterprise", name: "通义千问企业版", tag: "通用" },
];

function toModelKey(modelId: string): string {
  return modelId === "default" ? "system_default" : modelId;
}

// 快捷提问示例：仅用于填充输入框，非后端推荐 / 非真实项目内容。
const exampleQuestions = [
  "本项目当前阶段有哪些关键交付物？",
  "资产区里有哪些可复用的方法论？",
  "资料区有哪些内容尚未沉淀为资产？",
];

function phaseOrder(phase: string): number {
  const i = LIFECYCLE_PHASES.indexOf(phase);
  return i === -1 ? LIFECYCLE_PHASES.length + 1 : i;
}

export default function ProjectKnowledgePage() {
  const { id } = useParams<{ id: string }>();
  const [selectedPhase, setSelectedPhase] = useState<string>(""); // "" = 全部阶段
  const [activeZone, setActiveZone] = useState<ZoneType | "">(""); // "" = 资料+资产
  const [filterVisibility, setFilterVisibility] = useState("");
  const [qaInput, setQaInput] = useState("");
  // Q&A 接真实平台权限网关：结果来自后端，而非本地假问答。
  const [qaResult, setQaResult] = useState<ProjectQaResponseDTO | null>(null);
  const [qaLoading, setQaLoading] = useState(false);
  const [qaError, setQaError] = useState<string | null>(null);
  const [selectedModelId, setSelectedModelId] = useState(qaModels[0].id);

  // 从 /auth/me 解析"本次实际所在项目"（路由 :id 为占位串，不直接用作项目 UUID）。
  const [authMe, setAuthMe] = useState<AuthMeVM | null>(null);
  const [authError, setAuthError] = useState<string | null>(null);

  // 真实项目知识（来自 GET /knowledge?scope=project，按当前项目名筛选）。
  const [projectCards, setProjectCards] = useState<KnowledgeCardVM[] | null>(null);
  const [cardsLoading, setCardsLoading] = useState(false);
  const [cardsError, setCardsError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchAuthMe()
      .then((me) => { if (!cancelled) setAuthMe(me); })
      .catch((e) => { if (!cancelled) setAuthError(e instanceof Error ? e.message : "加载身份失败"); });
    return () => { cancelled = true; };
  }, []);

  // 优先用路由 UUID（且为本人有效项目）；否则回退到第一个有效项目。
  const effectiveProject = useMemo(() => {
    const projects = authMe?.projects ?? [];
    if (id && UUID_RE.test(id)) {
      const matched = projects.find((p) => p.projectId === id);
      if (matched) return matched;
    }
    return projects[0] ?? null;
  }, [authMe, id]);

  // 拉取项目 scope 真实知识，按当前项目名筛选（列表项暴露 project_name，不暴露 project_id）。
  useEffect(() => {
    if (!effectiveProject) return;
    let cancelled = false;
    setCardsLoading(true);
    setCardsError(null);
    fetchKnowledgeList({ scope: "project" })
      .then((all) => {
        if (cancelled) return;
        setProjectCards(all.filter((c) => c.projectName === effectiveProject.projectName));
        setCardsLoading(false);
      })
      .catch((e) => {
        if (cancelled) return;
        setCardsError(e instanceof ApiError ? e.message : "加载项目知识失败（请确认后端已启动）");
        setCardsLoading(false);
      });
    return () => { cancelled = true; };
  }, [effectiveProject]);

  const cards = projectCards ?? [];
  const cardPhase = useCallback((c: KnowledgeCardVM) => c.lifecyclePhase || UNLABELED_PHASE, []);

  // 真实聚合：阶段列表（仅出现在数据中的阶段，按规范顺序）+ 各阶段资料/资产计数。
  const phases = useMemo(() => {
    const set = new Set<string>();
    cards.forEach((c) => set.add(cardPhase(c)));
    return Array.from(set).sort((a, b) => phaseOrder(a) - phaseOrder(b));
  }, [cards, cardPhase]);

  const totalMaterials = cards.filter((c) => c.zone === "material").length;
  const totalAssets = cards.filter((c) => c.zone === "asset").length;

  const phaseCount = useCallback(
    (phase: string, zone?: ZoneType) =>
      cards.filter((c) => cardPhase(c) === phase && (!zone || c.zone === zone)).length,
    [cards, cardPhase]
  );

  const inPhase = useMemo(
    () => (selectedPhase ? cards.filter((c) => cardPhase(c) === selectedPhase) : cards),
    [cards, selectedPhase, cardPhase]
  );
  const zoneMaterials = inPhase.filter((c) => c.zone === "material");
  const zoneAssets = inPhase.filter((c) => c.zone === "asset");

  const visibleCards = useMemo(() => {
    let items = inPhase;
    if (activeZone) items = items.filter((c) => c.zone === activeZone);
    if (filterVisibility) items = items.filter((c) => c.visibility === filterVisibility);
    return items;
  }, [inPhase, activeZone, filterVisibility]);

  // 资产沉淀提醒：从真实数据派生——有资料但暂无资产的阶段（无假数字，无硬编码业务事实）。
  const pendingAssetPhases = useMemo(
    () => phases.filter((p) => phaseCount(p, "material") > 0 && phaseCount(p, "asset") === 0),
    [phases, phaseCount]
  );

  const handlePhaseClick = useCallback((phase: string) => {
    setSelectedPhase(phase);
    setFilterVisibility("");
    setActiveZone("");
  }, []);

  const handleAsk = useCallback(async () => {
    const q = qaInput.trim();
    if (!q) return;
    if (!effectiveProject) {
      setQaError("当前账号没有可问答的有效项目（需要项目成员身份）。");
      return;
    }
    setQaLoading(true);
    setQaError(null);
    setQaResult(null);
    try {
      const res = await projectQa(effectiveProject.projectId, {
        query: q,
        modelKey: toModelKey(selectedModelId),
      });
      setQaResult(res);
    } catch (e) {
      const msg = e instanceof ApiError ? `${e.message}（${e.deniedReason ?? e.status}）` : "问答请求失败";
      setQaError(msg);
    } finally {
      setQaLoading(false);
    }
  }, [qaInput, effectiveProject, selectedModelId]);

  const handleResetQA = useCallback(() => {
    setQaInput("");
    setQaResult(null);
    setQaError(null);
  }, []);

  const handleExampleClick = useCallback((q: string) => {
    setQaInput(q);
  }, []);

  const projectTitle = effectiveProject?.projectName ?? "（未解析到有效项目）";

  return (
    <div className="project-page">
      {/* Header + KPI（KPI 为真实聚合：项目 scope 知识按 zone 统计） */}
      <div className="pj-header">
        <div className="pj-header-text">
          <h2>项目知识看板</h2>
          <p>项目 <strong>{projectTitle}</strong> 的知识驾驶舱 — 按生命周期阶段组织项目资料区与资产区（数据来自平台项目知识库）</p>
        </div>
        <div className="kl-kpis">
          <div className="kl-kpi">
            <div className="kl-kpi-value">{totalMaterials}</div>
            <div className="kl-kpi-label">资料区</div>
          </div>
          <div className="kl-kpi">
            <div className="kl-kpi-value kl-kpi-success">{totalAssets}</div>
            <div className="kl-kpi-label">资产区</div>
          </div>
          <div className="kl-kpi">
            <div className="kl-kpi-value">{phases.length}</div>
            <div className="kl-kpi-label">覆盖阶段</div>
          </div>
        </div>
      </div>

      <p className="page-help-line">
        项目内角色（辅导老师 / 项目经理 / 顾问）职责与资料区·资产区规则见 <Link to="/help#project" className="page-help-link">使用说明 →</Link>
      </p>

      {/* Lifecycle stages（真实：仅展示数据中出现的阶段 + 真实计数） */}
      <section className="project-section">
        <h3>生命周期阶段 <span className="lifecycle-route-inline">（按平台阶段顺序）</span></h3>
        {cardsLoading ? (
          <div className="pj-empty-state"><div className="pj-empty-title">加载中…</div></div>
        ) : cardsError ? (
          <div className="pj-empty-state">
            <div className="pj-empty-title">加载失败</div>
            <p className="pj-empty-desc">{cardsError}</p>
          </div>
        ) : phases.length === 0 ? (
          <div className="pj-empty-state">
            <div className="pj-empty-title">该项目暂无知识资产</div>
            <p className="pj-empty-desc">
              项目知识库尚无内容。可前往 <Link to="/upload">资产化确认</Link> 上传入库，或在 <Link to="/admin/wecom-scan">微盘扫描</Link> 配置企微微盘自动采集；也可在 <Link to="/knowledge">知识首页</Link> 切换到项目范围浏览。
            </p>
          </div>
        ) : (
          <div className="lifecycle-row">
            <div
              className={`lifecycle-card ${selectedPhase === "" ? "current" : ""} lc-clickable`}
              onClick={() => handlePhaseClick("")}
            >
              <div className="lc-head"><span className="lc-name">全部阶段</span></div>
              <div className="lc-stats">
                <span className="lc-count">{cards.length} 份</span>
              </div>
            </div>
            {phases.map((p) => (
              <div
                key={p}
                className={`lifecycle-card ${selectedPhase === p ? "current" : ""} lc-clickable`}
                onClick={() => handlePhaseClick(p)}
              >
                <div className="lc-head">
                  <span className="lc-name">{p}</span>
                  {selectedPhase === p && <span className="lc-current-badge">已选</span>}
                </div>
                <div className="lc-stats">
                  <span className="lc-count">资料 {phaseCount(p, "material")} · 资产 {phaseCount(p, "asset")}</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Zone tabs + filters + real cards */}
      {phases.length > 0 && (
        <section className="project-section">
          <div className="pj-stage-toolbar">
            <h3>{selectedPhase || "全部阶段"} — 知识内容</h3>
            <div className="pj-stage-toolbar-right">
              <div className="pj-zone-tabs">
                <button className={`pj-zone-tab ${activeZone === "" ? "active" : ""}`} onClick={() => setActiveZone("")}>
                  全部（{zoneMaterials.length + zoneAssets.length}）
                </button>
                <button className={`pj-zone-tab ${activeZone === "material" ? "active" : ""}`} onClick={() => setActiveZone("material")}>
                  资料区（{zoneMaterials.length}）
                </button>
                <button className={`pj-zone-tab ${activeZone === "asset" ? "active" : ""}`} onClick={() => setActiveZone("asset")}>
                  资产区（{zoneAssets.length}）
                </button>
              </div>
              <select value={filterVisibility} onChange={(e) => setFilterVisibility(e.target.value)}>
                <option value="">全部可见性</option>
                <option value="public">公开</option>
                <option value="project-only">项目内</option>
                <option value="confidential">机密</option>
              </select>
              <span className="pj-stage-count">{visibleCards.length} 条结果</span>
            </div>
          </div>

          {visibleCards.length > 0 ? (
            <div className="pj-asset-grid">
              {visibleCards.map((c) => (
                <div key={c.id} className={`pj-asset-card ${c.zone === "asset" ? "pj-card-asset" : "pj-card-material"}`}>
                  <div className="card-header">
                    <Link to={`/knowledge/${c.id}`} className="card-title">{c.title}</Link>
                    <div className="card-header-badges">
                      <span className={`pj-zone-badge pj-zone-badge-${c.zone}`}>{c.zone === "asset" ? "资产" : "资料"}</span>
                      <span className="asset-type-badge">{assetTypeLabel[c.assetType] ?? c.assetType}</span>
                      <span className={`visibility-badge ${c.visibility}`}>{visibilityLabel[c.visibility] ?? c.visibility}</span>
                    </div>
                  </div>
                  <p className="pj-asset-summary">{c.summary || (c.access.summary ? "" : "（无摘要权限）")}</p>
                  <div className="card-tags">
                    {c.tags.map((t) => <span key={t} className="tag">{t}</span>)}
                  </div>
                  <div className="card-meta">
                    <span>{c.lifecyclePhase || UNLABELED_PHASE}</span>
                    <span>{c.updatedAt || "—"}</span>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="pj-empty-state">
              <div className="pj-empty-title">暂无内容</div>
              <p className="pj-empty-desc">当前筛选条件下无匹配内容，尝试切换阶段、区域或可见性筛选。</p>
            </div>
          )}
        </section>
      )}

      {/* Stage Q&A（真实平台权限网关） */}
      <section className="project-section">
        <h3>项目知识问答</h3>
        <div className="pj-qa-box">
          <p className="pj-qa-desc">项目问答已接入平台权限网关：问题提交到后端 <code>POST /projects/&#123;id&#125;/qa</code>，以你的真实身份逐项做三层访问判断，引用与回答均由网关裁定。来自资产区的引用为已验证内容，来自资料区的引用用于参考需谨慎确认。</p>
          <div className="pj-qa-target">
            {effectiveProject ? (
              <span>本次问答项目：<strong>{effectiveProject.projectName}</strong>（{effectiveProject.projectRole}）</span>
            ) : authError ? (
              <span className="pj-qa-target-warn">身份加载失败：{authError}</span>
            ) : authMe ? (
              <span className="pj-qa-target-warn">当前账号无可问答的有效项目（需要项目成员身份）。</span>
            ) : (
              <span>正在解析当前项目…</span>
            )}
          </div>
          <div className="pj-qa-model-row">
            <span className="pj-qa-model-label">问答模型</span>
            <select className="pj-qa-model-select" value={selectedModelId} onChange={(e) => setSelectedModelId(e.target.value)}>
              {qaModels.map((m) => (
                <option key={m.id} value={m.id}>{m.name}（{m.tag}）</option>
              ))}
            </select>
            <span className="pj-qa-model-hint">模型切换作为 model_key 传入本次问答，不影响知识卡片生成或系统默认配置</span>
          </div>
          <div className="qa-input-wrap">
            <input
              type="text"
              className="qa-input"
              placeholder="输入你的问题…"
              value={qaInput}
              onChange={(e) => setQaInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") handleAsk(); }}
            />
            <button className="btn-primary pj-qa-btn" onClick={handleAsk} disabled={!qaInput.trim() || qaLoading || !effectiveProject}>{qaLoading ? "提问中…" : "提问"}</button>
            {(qaInput || qaResult || qaError) && (
              <button className="btn-small pj-qa-reset" onClick={handleResetQA}>清空</button>
            )}
          </div>
          <div className="qa-examples">
            <span className="qa-examples-label">快捷提问示例（仅填充输入框，非后端推荐）：</span>
            {exampleQuestions.map((q) => (
              <span key={q} className="qa-example qa-example-clickable" onClick={() => handleExampleClick(q)}>{q}</span>
            ))}
          </div>
          {qaError && (
            <div className="pj-qa-result pj-qa-error">
              <span className="pj-qa-answer-label">问答未成功</span>
              <p>{qaError}</p>
            </div>
          )}
          {qaResult && (
            <div className="pj-qa-result">
              <div className="pj-qa-answer">
                <span className="pj-qa-answer-label">AI 回答 · 模型：{qaResult.model_key} · 决策：{qaResult.decision_status}</span>
                <p>{qaResult.response_text}</p>
              </div>
              <div className="pj-qa-trace">
                <span>调用记录 call_id：<code>{qaResult.call_id}</code></span>
                {qaResult.trace_id && <span>trace_id：<code>{qaResult.trace_id}</code></span>}
              </div>
              {qaResult.citations.length > 0 && (
                <div className="pj-qa-sources">
                  <span className="pj-qa-sources-label">引用来源（经权限网关裁定，引用层级不超过可达访问层级）</span>
                  {qaResult.citations.map((c) => (
                    <div key={c.asset_id} className="pj-qa-source-item">
                      <span className="pj-qa-source-title">{c.asset_title}</span>
                      <span className={`pj-zone-badge pj-zone-badge-${c.cited_zone}`}>{c.cited_zone === "asset" ? "资产区" : "资料区"}</span>
                      <span className="pj-qa-source-layer">访问层级：{c.used_access_layer}</span>
                      {c.is_pending_review && <span className="pj-qa-source-risk">待审风险</span>}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </section>

      {/* 资产沉淀提醒（从真实数据派生，无假数字） */}
      {phases.length > 0 && (
        <section className="project-section">
          <h3>资产沉淀提醒</h3>
          {pendingAssetPhases.length > 0 ? (
            <div className="risk-list">
              {pendingAssetPhases.map((p) => (
                <div key={p} className="risk-item pj-risk-medium">
                  <span className="pj-risk-badge pj-risk-medium">提示</span>
                  <span className="pj-risk-text">
                    「{p}」阶段有 {phaseCount(p, "material")} 份资料，尚无资产沉淀——可在内部分享/客户验证后由项目经理确认进入资产区。
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <div className="pj-empty-state">
              <div className="pj-empty-title">无待沉淀提示</div>
              <p className="pj-empty-desc">各有资料的阶段均已产生资产，或当前项目暂无资料。</p>
            </div>
          )}
        </section>
      )}

      <p className="page-help-line">
        资料区 / 资产区治理规则、问答边界与脱敏复审说明见 <Link to="/help#project" className="page-help-link">使用说明 →</Link>
      </p>
    </div>
  );
}
