import { Link } from "react-router-dom";
import { ArrowRight, CircleCheck, CircleDashed, LockKeyhole, Search, Sparkles } from "lucide-react";
import { can, type Capabilities } from "../auth/permissions";
import type { KnowledgeCardVM, KnowledgeDetailVM } from "../types/knowledge";
import DetailDrawer from "./DetailDrawer";
import "./AccessExplanationDrawer.css";

type ExplainableAsset = KnowledgeCardVM | KnowledgeDetailVM;

function indexExplanation(asset: ExplainableAsset) {
  if (asset.assetStatus !== "active")
    return {
      title: "资料尚未激活",
      body: "当前资料状态不支持检索或问答。资料恢复为有效状态后，系统会重新判断可用性。",
      action: null,
    };
  switch (asset.indexStatus) {
    case "indexing":
      return {
        title: "索引处理中",
        body: "资料正在进入检索底座。作业完成前不能据此判断检索或问答可用。",
        action: null,
      };
    case "index_failed":
      return {
        title: "索引未完成",
        body: "资料未能完成索引。具备维护权限的人员可以重新处理。",
        action: "retry" as const,
      };
    case "skipped":
      return {
        title: "未启用索引",
        body: "该资料已确认不进入检索底座，因此不会用于语义检索或问答。",
        action: null,
      };
    case "not_indexed":
      return { title: "等待索引", body: "资料已入库，正在等待索引作业处理。", action: null };
    default:
      return {
        title: "当前条件下不可用于检索",
        body: "系统无法进一步安全区分原因。请稍后重试或联系资料维护人员。",
        action: null,
      };
  }
}

export function accessLabel(asset: ExplainableAsset): string {
  if (asset.access.existingRequestStatus === "pending") return "原文申请审批中";
  if (asset.access.crossProjectSummary) {
    return asset.access.original ? "其他项目 · 原文已授权" : "其他项目 · 摘要可见";
  }
  if (!asset.access.summary) return "仅可发现";
  return asset.access.original ? "可查看摘要与原文" : "可查看摘要，原文受限";
}

export default function AccessExplanationDrawer({
  open,
  asset,
  capabilities,
  onClose,
  onRequest,
  onRetryIndex,
}: {
  open: boolean;
  asset: ExplainableAsset | null;
  capabilities: Capabilities;
  onClose: () => void;
  onRequest?: () => void;
  onRetryIndex?: () => void;
}) {
  if (!asset) return null;
  const detail = asset as KnowledgeDetailVM;
  const retrievalAvailable = detail.retrievalAvailable ?? asset.indexStatus === "indexed";
  const qaKnown = "qaAvailable" in asset && detail.qaAvailable != null;
  const qaAvailable = qaKnown ? detail.qaAvailable === true : null;
  const index = indexExplanation(asset);
  const pending = asset.access.existingRequestStatus === "pending";
  const originalBody = asset.access.original
    ? asset.access.existingGrantExpiresAt
      ? `原文授权当前有效，有效期至页面显示的授权时间。到期或被撤销后，入口会立即恢复为受限。`
      : "当前身份可以查看受控原文。"
    : pending
      ? "你已有一项原文申请正在审批。已读通知或查看本页不会改变审批状态。"
      : asset.access.canRequestOriginal
        ? "原文需要逐项申请。提交申请不会立即开放原文，审批结果以服务端状态为准。"
        : "当前身份不可查看原文，也没有可用的申请入口。";

  return (
    <DetailDrawer
      open={open}
      title="为什么是这个访问状态"
      description="依据当前页面已获准接收的安全状态生成；这里不会改变任何授权。"
      onClose={onClose}
      footer={
        <div className="aex-footer">
          {pending && (
            <Link to="/original-access?box=mine" onClick={onClose}>
              查看申请进度 <ArrowRight size={15} />
            </Link>
          )}
          {!pending && !asset.access.original && asset.access.canRequestOriginal && onRequest && (
            <button type="button" onClick={onRequest}>
              申请原文 <ArrowRight size={15} />
            </button>
          )}
          {index.action === "retry" && asset.access.canRetryIndex && onRetryIndex && (
            <button type="button" onClick={onRetryIndex}>
              重试索引 <ArrowRight size={15} />
            </button>
          )}
          {qaAvailable === false && can.viewModels(capabilities) && (
            <Link to="/admin/weknora-models" onClick={onClose}>
              查看模型配置 <ArrowRight size={15} />
            </Link>
          )}
        </div>
      }
    >
      <div className="aex-content">
        <section className="aex-ladder" aria-label="访问层级">
          {[
            { key: "discovery", label: "发现", ok: asset.access.discovery },
            { key: "summary", label: "摘要", ok: asset.access.summary },
            { key: "original", label: "原文", ok: asset.access.original },
          ].map((level, index) => (
            <div key={level.key} className={level.ok ? "is-reached" : "is-locked"}>
              {level.ok ? <CircleCheck /> : <LockKeyhole />}
              <span>{index + 1}</span>
              <strong>{level.label}</strong>
              <small>{level.ok ? "当前可达" : "当前受限"}</small>
            </div>
          ))}
        </section>
        <section className="aex-reason">
          <h3>原文访问</h3>
          <p>{originalBody}</p>
          {asset.access.existingGrantExpiresAt && (
            <p className="aex-fact">
              授权到期：
              {new Date(asset.access.existingGrantExpiresAt).toLocaleString("zh-CN", {
                timeZone: "Asia/Shanghai",
              })}
            </p>
          )}
        </section>
        <div className="aex-availability">
          <section>
            <Search />
            <div>
              <h3>{retrievalAvailable ? "检索可用" : index.title}</h3>
              <p>
                {retrievalAvailable ? "该资料已完成索引，可进入权限裁剪后的语义检索。" : index.body}
              </p>
            </div>
          </section>
          <section>
            <Sparkles />
            <div>
              <h3>
                {qaAvailable === true
                  ? "问答可用"
                  : qaAvailable === false
                    ? "问答不可用"
                    : "问答状态需在详情确认"}
              </h3>
              <p>
                {qaAvailable === true
                  ? "该资料可在当前安全层级内用于问答；引用仍受权限裁剪。"
                  : qaAvailable === false
                    ? retrievalAvailable
                      ? "当前项目可能尚无可用问答能力、资料 AI 使用等级不支持问答，或当前身份不具备使用资格。"
                      : "问答依赖可用索引；请先等待或恢复索引。"
                    : "列表未提供足以安全区分问答状态的信息；进入资料详情后可查看服务端判定。"}
              </p>
            </div>
          </section>
        </div>
        <p className="aex-boundary">
          <CircleDashed />{" "}
          搜索不到资料不代表系统中不存在资料；不可发现的资料不会在这里被确认、计数或描述。
        </p>
      </div>
    </DetailDrawer>
  );
}
