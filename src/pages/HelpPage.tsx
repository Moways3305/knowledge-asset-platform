import { Link } from "react-router-dom";

// 统一使用说明（PBC-10E）。把各功能页原本堆叠的设计/边界/规则/规划说明集中到此处，
// 按模块分组。内容为前端静态文案，口径对齐当前真实能力；不含任何密钥 / 内部地址 /
// 内部存储引用 / 外部系统内部标识。

interface HelpItem {
  term?: string;
  text: string;
}
interface HelpSection {
  id: string;
  title: string;
  intro?: string;
  items: HelpItem[];
}

const SECTIONS: HelpSection[] = [
  {
    id: "identity",
    title: "账号与身份",
    items: [
      { term: "登录方式", text: "支持本地会话登录与企微 OAuth（企微登录需后端配置 WECOM_*，未配置时安全降级）。密码登录尚未实现。" },
      { term: "业务身份", text: "顾问 / 项目经理 / Boss / 咨询总监为业务身份，拥有相应知识访问权。" },
      { term: "系统管理身份（admin）", text: "纯 admin 是系统运维身份，不具备业务知识访问权，不能浏览知识库正文 / 摘要 / 原文；仅可使用管理后台的安全运营元数据页。" },
    ],
  },
  {
    id: "knowledge",
    title: "知识资产库",
    intro: "知识分公司 / 项目 / 个人三类库，同库内用 zone（资料区 / 资产区）标记资产化状态。",
    items: [
      { term: "可见性", text: "个人知识仅 owner 本人可见；项目知识对该项目 active 成员开放摘要与原文；公司知识按保密级别开放发现 / 摘要。L5 仅 Boss / 咨询总监可发现。" },
      { term: "语义检索", text: "知识首页搜索框为真实语义检索（后端 WeKnora 召回 + 意图识别 + 权限裁剪 + 输出脱敏），结果含答案 / 引用 / 原文层状态。" },
      { term: "原文权限", text: "跨项目 / 公司 L3/L4 原文需发起原文访问申请，审批通过后在有效期内放行；过期 / 撤销立即失效。" },
      { term: "删除 / 撤下", text: "受控软删除：删除后资产退出检索 / 问答 / 预览，保留审计追溯。删除权限：个人 owner 本人 / 项目 active 项目经理 / 公司 Boss·咨询总监。" },
    ],
  },
  {
    id: "ingest",
    title: "入库与资产化",
    intro: "两条路径共享同一「AI 预览 → 人工校正 → 入库 / 审核分流」模型。",
    items: [
      { term: "路径 B 本地上传", text: "上传文件后由 worker 异步抽取文本、外部 LLM 生成命名规范化标题 / 三层摘要 / 标签 / 分类草稿（LLM 不可用时 fail-closed 降级为确定性建议并提示人工补全），人工校正后提交入库。" },
      { term: "路径 A 企微微盘", text: "企微微盘扫描创建的待确认任务进入待确认列表（仅显示你有权确认的任务），点击后复用路径 B 同一确认链路入库。" },
      { term: "命名规范", text: "平台命名格式：【一级类-二级类】主题_对象/客户_日期_V版本_L保密级别。命名不合规不阻断入库，但会标记命名异常进入人工审核提示。" },
      { term: "保密级别 / AI 调用级别", text: "L1 公开 → L5 绝密；A1 可直接调用 / A2 脱敏后 / A3 摘要后 / A4 禁止调用。L4/L5 不进入开放式 AI 调用。" },
      { term: "资料区 / 资产区", text: "资料区（material）为项目过程材料；资产区（asset）需真实内部分享或客户验证 + 登记证据 + 项目经理确认后标记。两者是同一项目库的分区标签，不是两个库。" },
    ],
  },
  {
    id: "project",
    title: "项目知识库",
    items: [
      { term: "项目创建", text: "由 Boss / 咨询总监创建项目知识空间，需指定 active 业务用户为项目经理（自动建立 active 成员关系）；纯 admin 不可创建业务项目。" },
      { term: "项目内角色", text: "辅导老师（现场教学 / 陪跑 / 进度观察）、项目经理（资产区确认 / 知识运营 / 审核个人到项目提交）、顾问（查看授权资料 / 提交资料与候选 / 问答，不确认资产区）。" },
      { term: "项目问答", text: "项目 Q&A 经平台权限网关按真实身份逐项做三层访问判断，引用与回答均由网关裁定；资产区引用已验证、资料区引用需谨慎确认。" },
      { term: "项目设置", text: "项目经理 / 治理角色可改项目设置与成员；企微群配置只存安全标识，响应只回脱敏 label。" },
    ],
  },
  {
    id: "review",
    title: "审核与授权",
    items: [
      { term: "资产化确认", text: "material → asset 须先登记验证证据（内部分享 / 客户验证），再由被分配的项目经理确认后标记为资产区。系统登记证据引用，不替代真实业务场景。" },
      { term: "原文访问授权", text: "申请 / 审批 / 拒绝 / 撤销已接入真实后端；审批通过生成 active 授权并在运行时放行原文层，过期 / 撤销立即失效。" },
      { term: "个人到项目提交", text: "个人知识进入项目须由知识所有者本人主动提交；项目经理审核个人到项目的提交。" },
      { term: "边界", text: "项目资产 → 公司知识的升格审核仍为后续任务；本阶段已实现项目 material → asset 审核闭环。" },
    ],
  },
  {
    id: "admin",
    title: "管理后台",
    intro: "管理后台仅展示安全运营元数据，不展示业务正文 / 原文 / 摘要全文。",
    items: [
      { term: "入库管理", text: "运营查看入库任务状态、抽取状态、命名合规、错误等元数据（admin / Boss / 咨询总监）。" },
      { term: "微盘扫描配置", text: "admin 创建 / 编辑 / 启停 / 手动触发企微微盘扫描目录，并指定待确认任务的业务归属人；扫描运行时复核归属人仍合法，失效则 fail-closed 不建任务。真实企微连接由后端 WECOM_* 配置控制，未配置时安全降级。" },
      { term: "审计日志", text: "操作 / 异常 / 登录三类审计，按角色脱敏返回；时间为北京时间，action 已中文展示并保留原始追踪 ID 供排障。" },
      { term: "权限规则", text: "permission_rules 配置中心（Boss / 咨询总监可改、admin 只读）；部分规则为治理配置视图，运行时接入边界见各规则说明。" },
      { term: "人员权限", text: "人员、公司角色、项目成员关系管理；admin 不因系统身份获得业务原文授权权。" },
      { term: "告警设置", text: "告警规则与通知记录；企微通知真实下发受 WECOM_NOTIFY_ENABLED 总开关控制（默认仅本地 in_app）。" },
    ],
  },
  {
    id: "integration",
    title: "外部集成（启用边界）",
    intro: "外部系统经后端 env 注入启用，未配置时 fail-closed 安全降级，不伪装成功。",
    items: [
      { term: "WeKnora", text: "知识底座 / 向量召回；入库确认时按 scope 懒创建知识库，未配置时跳过索引、不阻断入库。" },
      { term: "外部 LLM", text: "内容处理与问答合成；不可用时降级为确定性建议或保守不返回原文。" },
      { term: "企业微信（WeCom）", text: "OAuth 身份、微盘扫描、通知下发，均受 WECOM_* 配置控制。" },
      { term: "ONLYOFFICE", text: "原文只读预览：由平台权限网关签发凭证、只读打开并全程审计；平台不直接暴露对象存储地址、内部存储引用或下载凭证。未配置时安全降级、不泄露原文地址。" },
      { term: "外部 Agent / 工作流网关", text: "平台核心是 provider 中立的外部 Agent / 工作流网关；Agent 完全跟随调用人权限，不绕过、不拥有独立权限。Dify 只是其中一个兼容适配器。" },
    ],
  },
  {
    id: "roadmap",
    title: "仍未实现 / 后续增强",
    intro: "以下为当前尚未实现或规划中的能力，功能页不会伪装为已实现。",
    items: [
      { text: "入库前实体级自动脱敏管线（当前为目标分级规划，未执行实际脱敏）。" },
      { text: "知识首页右侧运营洞察接口（当前为本地规则提示）。" },
      { text: "L1/L2 默认放行的 system_rule 规则化运行时（当前为常量策略）。" },
      { text: "access_request_timeout_hours 驱动的超时自动审批。" },
      { text: "密码登录 / 密码凭证校验。" },
      { text: "项目资产 → 公司知识的升格审核；整体 UI 视觉优化。" },
    ],
  },
];

export default function HelpPage() {
  return (
    <div className="help-page">
      <div className="help-header">
        <h2>使用说明</h2>
        <p>平台功能、权限边界与外部集成的集中说明。功能界面只保留操作与必要提示，详细说明集中在此。</p>
      </div>

      <nav className="help-toc">
        {SECTIONS.map((s) => (
          <a key={s.id} href={`#${s.id}`} className="help-toc-link">{s.title}</a>
        ))}
      </nav>

      {SECTIONS.map((s) => (
        <section key={s.id} id={s.id} className="help-section">
          <h3>{s.title}</h3>
          {s.intro && <p className="help-section-intro">{s.intro}</p>}
          <dl className="help-dl">
            {s.items.map((it, i) => (
              <div key={i} className="help-dl-row">
                {it.term && <dt>{it.term}</dt>}
                <dd>{it.text}</dd>
              </div>
            ))}
          </dl>
        </section>
      ))}

      <p className="help-footer">
        返回 <Link to="/knowledge">知识首页</Link>。生产部署 / 运维步骤见仓库 README 与运维文档，不在此页。
      </p>
    </div>
  );
}
