import { Link } from "react-router-dom";

import { useState } from "react";
import {
  BookOpenCheck,
  BriefcaseBusiness,
  ChevronRight,
  CircleHelp,
  Compass,
  KeyRound,
  LibraryBig,
  Search,
  Settings2,
  ShieldCheck,
  Upload,
  UserRoundCheck,
  Workflow,
  type LucideIcon,
} from "lucide-react";
import { PageHeader, ProductPage } from "../components/ProductLayout";

// 统一使用说明。把各功能页原本堆叠的设计/边界/规则/规划说明集中到此处，
// 按模块分组。内容为前端静态文案，口径对齐当前真实能力；不含任何密钥 / 内部地址 /
// 内部存储引用 / 外部系统诊断标识。

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
    id: "quick-start",
    title: "快速开始",
    items: [
      {
        term: "日常入口",
        text: "从首页查看待办、快捷入口、今日状态和项目范围；需要处理的入库确认、审核和原文申请会汇总到工作台。",
      },
      {
        term: "知识使用",
        text: "在知识资产库先按公司、项目或个人目录浏览，可在当前目录内查找资料，或切换到全库搜索；在项目知识页查看资料区和资产区，也可以向当前项目知识提问。",
      },
      {
        term: "入库确认",
        text: "本地上传或企业微信微盘待确认文件都会先生成内容建议，你校正后再提交入库。",
      },
    ],
  },
  {
    id: "identity",
    title: "企业微信登录与 Kivo 入口",
    items: [
      {
        term: "登录方式",
        text: "Kivo 支持密码登录与企业微信登录。企业微信由管理员配置启用；未启用时不会开放企业微信入口。密码登录按邮箱与密码校验。MFA / 找回密码为后续增强。",
      },
      {
        term: "业务身份",
        text: "公司业务身份与项目成员角色共同决定操作范围。个人资料由本人管理；项目资料由该项目的有效项目经理管理；公司资料由总经理或咨询总监管理。维护人安排不会额外授予知识管理或原文权限。",
      },
      {
        term: "系统管理身份（admin）",
        text: "系统管理身份不默认拥有业务知识访问权，不能代替业务角色浏览知识正文、摘要或原文。",
      },
    ],
  },
  {
    id: "knowledge",
    title: "知识资产库",
    intro:
      "知识分公司、项目、个人三类库；项目库的资料区与资产区区分过程材料和已验证资产。入口和能力以当前部署版本及本人权限为准。",
    items: [
      {
        term: "可见性",
        text: "个人知识仅 owner 本人可见；项目 active 成员可读取本项目原文，其他 active 业务用户可发现项目 L1-L4 知识并仅查看安全摘要，跨项目 L3/L4 只显示脱敏摘要，缺少脱敏摘要时不会回退普通摘要。跨项目 L5 不可发现，公司职务或系统管理员不会自动取得其他项目原文。",
      },
      {
        term: "语义检索",
        text: "通过全库搜索查找有权限的知识，结果按权限裁剪并脱敏；搜索与问答不会因为使用自然语言而绕过保密等级或原文授权。未完成索引或解析的资料可能暂时无法参与问答，可查看详情中的可用状态。",
      },
      {
        term: "原文权限",
        text: "跨项目摘要可见不等于可以进入项目空间或读取原文。跨项目原文需逐项发起访问申请，审批通过后仅对对应资产在有效期内放行；过期 / 撤销立即失效。",
      },
      {
        term: "运营洞察",
        text: "运营洞察汇总索引或解析异常、原文申请、归档候选等需要处理的事项，按本人及所在项目或治理范围展示。系统管理员只看安全运营信息，不因此获得业务正文或原文权限。",
      },
      {
        term: "编辑资料",
        text: "有管理权限时，在资料详情中选择「编辑资料」，可更正标题、正式目录、标签、保密等级和摘要，填写修改原因后保存。编辑不会改写原始文件；需要更新正文时应上传新版并关联替代关系。页面打开后若资料已被他人修改或迁移目录，请重新加载最新信息再编辑，不能直接覆盖。",
      },
      {
        term: "调整保密等级",
        text: "降低等级须明确确认可能扩大访问范围；等级变更会使旧预览凭证失效，提升等级还会撤销已有原文授权。更正摘要会按保密等级重新处理，AI 使用设置不会随等级调整自动放宽。",
      },
      {
        term: "删除 / 撤下",
        text: "受控软删除：删除后资产退出检索 / 问答 / 预览，保留审计追溯。删除权限：个人 owner 本人 / 项目 active 项目经理 / 公司总经理或咨询总监。",
      },
    ],
  },
  {
    id: "directories",
    title: "正式目录与公司库治理",
    items: [
      {
        term: "新建公司三级目录",
        text: "总经理或咨询总监可在公司库标准分类中选择「新建三级目录」，填写名称并检查继承的默认密级。先保存草稿，再发布正式目录；仅保存草稿不会出现在正式浏览、上传或资料编辑的目录列表。只能挂在公司标准分类下，不能跨库、重复命名或继续创建四级目录。",
      },
      {
        term: "目录与资料分开管理",
        text: "新建或发布目录不会自动移动旧资料。单份资料可通过「编辑资料」调整正式目录；目录治理中的迁移操作需要核验候选再执行。目录配置与资料变更均保留操作记录。",
      },
      {
        term: "归档陈旧资料",
        text: "在「公司库治理」检查在库资料和归档候选，逐项核验后选择资料、预览归档并填写原因，再确认处理。候选只是管理建议，不会自动归档。归档后退出默认检索与问答，原文件和历史记录保留；这不是删除原文件。",
      },
      {
        term: "恢复与新版关系",
        text: "在归档中心核验用途后预览恢复并确认。若旧资料已关联替代新版，应先处理替代关系，不能直接把已被替代的资料重新启用；解除关联也不会自动恢复旧资料。关联新版的完整流程见「知识维护与纠错」。",
      },
    ],
  },
  {
    id: "maintenance",
    title: "知识维护与纠错",
    intro: "维护人 → 到期复核 → 更新或关联新版 → 旧版处理 → 用户纠错 → 再次验证。",
    items: [
      {
        term: "安排维护与复核",
        text: "在资料详情或「知识维护」安排维护人和下次复核日期。到期提醒用于推动人工检查，不会自动删除或归档。调整维护人或复核日期本身不视为内容更新，不会让已复核资料变成「修改后待复核」。",
      },
      {
        term: "复核资料",
        text: "先指定维护人，由有管理权限的人检查内容、密级、目录及适用范围后登记复核，并设置未来的下次复核日期。真实内容或元信息修改后需要重新复核；存在未处理纠错时不能直接标记为已复核。历史资料不会仅因启用此功能就自动成为已验证资料。",
      },
      {
        term: "关联新版并处理旧版",
        text: "正文变化时先上传新版。选择同一知识库范围、同一分类且已复核有效的资料作为替代新版，核对后明确确认关联和归档旧版。旧版退出默认检索与问答，历史文件保留；不会自动改写文件、迁移附件或扩大新版权限。",
      },
      {
        term: "反馈错误",
        text: "用户可从资料详情提交纠错并说明问题。纠错不会赋予原文访问权，也不会开放其他人的反馈记录；提交人和有管理权限的人可跟踪自己有权查看的反馈。",
      },
      {
        term: "处理后再次验证",
        text: "管理人应实际更正资料或关联替代新版，再处理纠错；仅换维护人、推迟日期或标记复核不算纠错证据。提交人核验处理后的资料，可确认解决或在满足条件时重新反馈。处理后资料再次变化时，应重新核对最新版本，不能沿用旧结果。",
      },
    ],
  },
  {
    id: "ingest",
    title: "上传文件",
    intro: "两条路径共享同一「AI 预览 → 人工校正 → 入库 / 审核分流」模型。",
    items: [
      {
        term: "本地上传",
        text: "上传后平台异步抽取文本，扫描件可进入 OCR 处理，并生成摘要、标签和命名建议；正式目录由确认人选择。请检查建议，不要把 AI 生成内容当作已核验事实；处理受限或字段缺失时按页面提示人工补全。",
      },
      {
        term: "企业微信待确认",
        text: "企业微信微盘扫描创建的待确认任务进入待确认列表（仅显示你有权确认的任务），点击后复用同一确认链路入库。",
      },
      {
        term: "命名规范",
        text: "规范名依据已发布的正式目录和当前命名规则生成。公司资料需检查适用对象、形成日期、版本及密级；项目资料还需有效项目代码。资料标题与原文件名分开管理，不会因 AI 建议自动改写原文件。缺少必填字段或项目代码时可能无法确认，请按校验提示补全后再提交。",
      },
      {
        term: "批次与失败处理",
        text: "上传按页面提示拆分批次；单文件上限为 100,000,000 字节，单次传输通常最多 10 个文件、合计 20 MiB，单文件单独传输可放宽到单文件上限。已上传不等于已入库或可问答，请跟踪确认、审核与索引状态；失败后先看原因和已有任务，再重试，避免反复上传产生重复资料。",
      },
      {
        term: "敏感信息保护",
        text: "入库建议由受信任的平台处理链路生成，原文与结构化建议受访问控制保护；对外展示、问答输出与引用内容会按权限和脱敏策略收口。原始文件保留供授权预览 / 溯源，不展示敏感正文对比。",
      },
      {
        term: "保密级别与自动处理",
        text: "保密级别用于决定知识展示、问答和原文访问范围。高保密级别内容只在授权范围内查看和处理。",
      },
      {
        term: "资料区 / 资产区",
        text: "资料区（material）为项目过程材料；资产区（asset）需真实内部分享或客户验证 + 登记证据 + 项目经理确认后标记。两者是同一项目库的分区标签，不是两个库。",
      },
    ],
  },
  {
    id: "personal",
    title: "个人知识",
    items: [
      {
        term: "默认私密",
        text: "个人知识默认只对本人可见，不参与他人的知识检索。",
      },
      {
        term: "提交项目",
        text: "需要进入项目库的内容，可由本人提交给项目负责人确认；通过前不会直接进入项目知识库。",
      },
      {
        term: "外部助手检索",
        text: "通过 MCP 连接外部助手后，全局知识搜索可使用你有权读取的原文或跨项目安全摘要作为证据，不会把无权原文注入模型；指定项目入口仍只访问你作为有效成员的当前项目。",
      },
    ],
  },
  {
    id: "project",
    title: "项目知识与问答",
    items: [
      {
        term: "项目创建",
        text: "由总经理 / 咨询总监创建项目知识空间，需指定 active 业务用户为项目经理（自动建立 active 成员关系）；纯 admin 不可创建业务项目。",
      },
      {
        term: "项目内角色",
        text: "辅导老师（现场教学 / 陪跑 / 进度观察）、项目经理（项目入库审批 / 资产区确认 / 知识运营 / 审核个人到项目提交）、顾问（查看授权资料 / 提交项目知识与候选 / 问答，不审批项目入库或确认资产区）。",
      },
      {
        term: "项目知识提交",
        text: "普通顾问提交到项目范围后进入待项目经理确认状态；通过前不会形成可检索或可问答的项目知识。仅目标项目经理可批准或驳回；项目经理提交自己负责项目的知识可直接确认。",
      },
      {
        term: "项目问答",
        text: "项目知识页以地址中的当前项目为准，可从页面顶部切换到本人有权限的其他项目；切换后列表、统计与问答会同步刷新。无效或无权限项目不会自动跳到其他项目。跨项目摘要策略不会开放项目知识页、项目简报、设置、成员、上传或审核。当前项目问答只检索当前成员项目，不会扩展到其他项目；资产区引用已验证，资料区引用用于参考，仍需结合业务判断确认。",
      },
      {
        term: "项目设置",
        text: "仅项目经理可修改本项目设置，并独立管理项目辅导老师与顾问；总经理 / 咨询总监负责任命或撤销项目经理。企微群配置只存安全标识，响应只回脱敏 label。",
      },
    ],
  },
  {
    id: "original-access",
    title: "原文访问申请",
    items: [
      {
        term: "申请与审批",
        text: "你当前没有原文查看权限时，可在知识详情页发起申请；项目经理、辅导老师或治理角色可在原文访问页审批。",
      },
      {
        term: "授权有效期",
        text: "审批通过后可在有效期内查看原文，授权可撤销，过期后自动失效。",
      },
    ],
  },
  {
    id: "review",
    title: "审核与授权",
    items: [
      {
        term: "资产化确认",
        text: "material → asset 须先登记验证证据（内部分享 / 客户验证），再由被分配的项目经理确认后标记为资产区。系统登记证据引用，不替代真实业务场景。",
      },
      {
        term: "原文访问授权",
        text: "申请 / 审批 / 拒绝 / 撤销均会记录操作；审批通过生成有效授权并放行原文层，过期 / 撤销立即失效。L1/L2 申请超过「访问申请自动通过时限」未审批由后台任务自动通过并生成授权；L3/L4/L5 机密资产不自动通过。",
      },
      {
        term: "个人到项目提交",
        text: "个人知识进入项目须由知识所有者本人主动提交；项目经理审核个人到项目的提交。",
      },
      {
        term: "项目入库审批",
        text: "顾问从上传页选择项目知识库提交后，审批工作台会生成待办。审批通过后执行入库，检索和问答还需索引及解析成功；入库不等于资料已完成资产化。失败时按任务状态重试，驳回不会删除受控原始材料。",
      },
      {
        term: "边界",
        text: "项目 material → asset 由项目经理确认；项目资产升格公司资产需一名总经理与一名咨询总监分别确认，任一方拒绝或撤回均不能完成升格。",
      },
    ],
  },
  {
    id: "admin",
    title: "管理员排障",
    intro: "管理后台仅展示安全运营元数据，不展示业务正文 / 原文 / 摘要全文。",
    items: [
      {
        term: "入库管理",
        text: "运营查看入库任务状态、抽取状态、命名合规、错误等元数据（admin / 总经理 / 咨询总监）。",
      },
      {
        term: "检索索引运维",
        text: "运维查看索引失败 / 解析滞留计数与最近失败资产（安全运营态）。可对筛选出的失败 / 跳过 / 待索引资产发起索引恢复，对已完成上传但解析异常的资产发起「重新解析」；恢复动作进入后台作业，面板展示作业安全统计与最近作业列表。重新解析不改变任何权限放行，不让未授权用户读到原文。运营面板绝不展示业务原文、文件名、技术诊断标识或存储引用。",
      },
      {
        term: "微盘扫描配置",
        text: "具有对应范围配置权限的人可管理微盘扫描目录，并指定待确认任务的业务归属人；扫描运行时会复核归属人仍合法，不合法则不创建任务。项目范围操作须满足该项目管理权限，企微连接由管理员配置。",
      },
      {
        term: "审计日志",
        text: "操作、异常、登录三类审计按角色展示；默认表格显示业务化摘要，技术详情可展开用于排障。",
      },
      {
        term: "权限规则",
        text: "permission_rules 配置中心（总经理 / 咨询总监可改、admin 只读）。公司 L1/L2 原文与访问申请自动通过时限按运行时规则生效；跨项目项目知识始终只开放安全摘要，原文需逐资产授权。",
      },
      {
        term: "人员权限",
        text: "总经理可管理总经理、咨询总监和顾问；咨询总监可管理咨询总监和顾问，但不可修改总经理。总经理 / 咨询总监任命项目经理，项目经理独立管理本项目辅导老师与顾问。系统管理员仅查看审计与必要运行状态，不进入人员、角色或项目成员治理。",
      },
      {
        term: "公司知识库",
        text: "总经理或咨询总监在「公司知识库」管理入口创建并检查知识库状态，初始化完成前不能用于公司范围入库。资料治理在「公司库治理」进行；正式分类配置在「命名规则」管理。系统管理员身份不替代这些业务治理权限。",
      },
      {
        term: "告警设置",
        text: "告警规则与通知记录；企微通知真实下发受 WECOM_NOTIFY_ENABLED 总开关控制（默认仅本地 in_app）。",
      },
    ],
  },
  {
    id: "release-notes",
    title: "版本日志与公告",
    items: [
      {
        term: "查看更新",
        text: "在「版本日志」查看已发布的更新说明。版本身份与部署验证用于核对当前运行版本，拉取代码或构建镜像不等于已完成部署。",
      },
      {
        term: "审核日志草稿",
        text: "具有版本日志管理权限的人可编辑和预览草稿。完成对应版本的部署验证后才允许发布公告；部署生成草稿不会立即通知用户。发布前应完成业务验收、核对说明和通知选项，已发布记录不可按草稿直接改写。",
      },
    ],
  },
  {
    id: "models",
    title: "模型配置",
    intro: "外部 LLM 与 WeKnora 底座独立配置；任一侧不可用时会显示对应状态，不伪装成功。",
    items: [
      {
        term: "外部 LLM",
        text: "KAP 直接管理 OpenAI-compatible 对话模型，用于内容生成和项目问答，不要求在 WeKnora 创建同名模型。API 地址和密钥保存后不再显示。",
      },
      {
        term: "WeKnora 底座模型",
        text: "嵌入、重排和底座部署要求的兼容 LLM 槽位只用于知识库初始化与检索。兼容 LLM 槽位不控制 KAP 内容生成或项目问答；修改底座默认值不会重建知识库，也不会改变已有库的嵌入绑定。",
      },
      { term: "内容建议", text: "内容建议受限时会提示人工补全，已保存内容仍受访问控制保护。" },
    ],
  },
  {
    id: "integration",
    title: "MCP 接入",
    intro:
      "从「MCP 接入」连接 WorkBuddy、Codex 等支持 MCP 的助手，访问和操作始终以调用人的当前权限为准。",
    items: [
      {
        term: "连接与凭证",
        text: "在「MCP 接入」生成本人配置并按助手的连接方式接入。请妥善保存仅生成时展示的凭证，不要发到群聊或公开文档；重新生成会使旧凭证失效，已有助手需要更新配置。",
      },
      {
        term: "只读与操作权限",
        text: "默认只读。需要助手代办时显式启用上传与审批操作权限；授权不会提升本人业务权限。支持的流程包括上传、命名预览、确认入库和有权限的审核操作，具体可用工具及限制以连接后返回的能力为准。重新生成凭证前应检查权限选项，提交或审批前核对对象和操作内容。",
      },
      {
        term: "操作边界",
        text: "文件字节通过受控上传接口传输，不把原文塞进工具参数。助手应先读取上传限制再组批，遵守同一套入库、审核及审计规则。资料维护、新版关联和纠错等页面能力不代表都已开放为 MCP 工具，未列出的操作仍在平台对应入口办理。",
      },
      {
        term: "企业微信（WeCom）",
        text: "为 Kivo 提供企业微信身份认证、微盘扫描、通知下发，均受 WECOM_* 配置控制。",
      },
      {
        term: "ONLYOFFICE",
        text: "原文只读预览：平台按权限签发短期凭证，只读打开并全程记录；平台不直接暴露对象存储地址、内部存储引用或下载凭证。未启用时不会泄露原文地址。",
      },
      {
        term: "外部助手",
        text: "外部助手完全跟随调用人权限，不拥有独立知识权限。",
      },
    ],
  },
  {
    id: "roadmap",
    title: "功能边界与待增强能力",
    intro:
      "帮助内容说明当前代码支持的工作流，线上是否可用还取决于部署版本、配置和本人权限；待增强项不构成已开放承诺。",
    items: [
      {
        text: "扫描件 OCR 已支持，但识别结果仍需人工校正。结构保持式原文件重写不属于资料编辑功能；当前编辑资料不会在线改写 Office、PDF 等原文件，ONLYOFFICE 仅用于授权只读预览。",
      },
      {
        text: "历史资产全量重索引策略系统（当前支持单条 / 批量恢复与显式 reparse，全量重建仍为规划）。",
      },
      {
        text: "登录安全进阶：MFA、找回密码、密码轮换、多设备会话管理 UI、企微组织树 / 通讯录同步与自动建用户（密码登录、企业微信登录、登录失败短时锁定 / IP 限流、cookie 会话 CSRF 防护、admin 登录风控面板与手动解锁、账号停用 / 改密 / 强制下线时撤销平台会话、企微成员失效时停用平台用户并撤销会话已实现）。",
      },
      {
        text: "项目资产升格公司知识已支持双人确认，不属于待开放能力；旧版归档与知识复核也不会替代真实业务验证。",
      },
    ],
  },
];

const HELP_GROUPS = [
  { title: "开始使用", icon: Compass, ids: ["quick-start", "identity"] },
  {
    title: "知识资产与项目",
    icon: LibraryBig,
    ids: ["knowledge", "directories", "maintenance", "ingest", "personal", "project"],
  },
  { title: "审核与原文访问", icon: ShieldCheck, ids: ["original-access", "review"] },
  {
    title: "管理员治理与安全",
    icon: Settings2,
    ids: ["admin", "release-notes", "models", "integration"],
  },
  { title: "功能边界", icon: CircleHelp, ids: ["roadmap"] },
] as const;

const SECTION_ICONS: Record<string, LucideIcon> = {
  "quick-start": Workflow,
  identity: UserRoundCheck,
  knowledge: LibraryBig,
  directories: LibraryBig,
  maintenance: BookOpenCheck,
  ingest: Upload,
  personal: UserRoundCheck,
  project: BriefcaseBusiness,
  "original-access": KeyRound,
  review: ShieldCheck,
  admin: Settings2,
  "release-notes": BookOpenCheck,
  models: Settings2,
  integration: Workflow,
  roadmap: CircleHelp,
};

const SECTION_BY_ID = new Map(SECTIONS.map((section) => [section.id, section]));

export default function HelpPage() {
  const [jumpTarget, setJumpTarget] = useState(SECTIONS[0].id);

  return (
    <ProductPage className="help-page help90-page">
      <PageHeader
        eyebrow="产品使用与权限边界"
        title="帮助中心"
        description="按实际工作流查找平台操作、角色权限与治理说明。"
      />

      <div className="help-jump-toolbar" role="search" aria-label="帮助内容定位">
        <label htmlFor="help-section-jump">
          <Search size={15} aria-hidden="true" />
          定位章节
        </label>
        <select
          id="help-section-jump"
          value={jumpTarget}
          onChange={(event) => setJumpTarget(event.target.value)}
        >
          {HELP_GROUPS.map((group) => (
            <optgroup label={group.title} key={group.title}>
              {group.ids.map((id) => {
                const section = SECTION_BY_ID.get(id);
                return section ? (
                  <option value={section.id} key={section.id}>
                    {section.title}
                  </option>
                ) : null;
              })}
            </optgroup>
          ))}
        </select>
        <a className="btn-small btn-small-primary" href={`#${jumpTarget}`}>
          跳转到章节
          <ChevronRight size={14} aria-hidden="true" />
        </a>
      </div>

      <div className="help-workspace">
        <aside className="help-directory" aria-label="帮助目录">
          <div className="help-directory-heading">
            <BookOpenCheck size={17} aria-hidden="true" />
            工作流目录
          </div>
          {HELP_GROUPS.map((group) => {
            const GroupIcon = group.icon;
            return (
              <div className="help-directory-group" key={group.title}>
                <div className="help-directory-group-title">
                  <GroupIcon size={14} aria-hidden="true" />
                  {group.title}
                </div>
                <nav aria-label={`${group.title}目录`}>
                  {group.ids.map((id) => {
                    const section = SECTION_BY_ID.get(id);
                    return section ? (
                      <a key={section.id} href={`#${section.id}`} className="help-toc-link">
                        {section.title}
                        <ChevronRight size={12} aria-hidden="true" />
                      </a>
                    ) : null;
                  })}
                </nav>
              </div>
            );
          })}
        </aside>

        <main className="help-content">
          {HELP_GROUPS.map((group) => (
            <div className="help-content-group" key={group.title}>
              <div className="help-content-group-label">{group.title}</div>
              {group.ids.map((id) => {
                const section = SECTION_BY_ID.get(id);
                if (!section) return null;
                const SectionIcon = SECTION_ICONS[section.id] ?? BookOpenCheck;
                return (
                  <section key={section.id} id={section.id} className="help-section">
                    <div className="help-section-heading">
                      <span className="help-section-icon">
                        <SectionIcon size={17} aria-hidden="true" />
                      </span>
                      <h3>{section.title}</h3>
                    </div>
                    {section.intro && <p className="help-section-intro">{section.intro}</p>}
                    <dl className="help-dl">
                      {section.items.map((item, index) => (
                        <div key={index} className="help-dl-row">
                          {item.term && <dt>{item.term}</dt>}
                          <dd>{item.text}</dd>
                        </div>
                      ))}
                    </dl>
                  </section>
                );
              })}
            </div>
          ))}

          <p className="help-footer">
            <BookOpenCheck size={15} aria-hidden="true" />
            返回 <Link to="/knowledge">知识资产库</Link>。生产部署与运维步骤见仓库 README
            和运维文档，不在此页展开。
          </p>
        </main>
      </div>
    </ProductPage>
  );
}
