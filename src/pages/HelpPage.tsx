import { Link } from "react-router-dom";

import { useState } from "react";
import {
  BookOpenCheck,
  BriefcaseBusiness,
  ChevronRight,
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

// 只说明当前可用的操作；未发布能力、开发规划和部署细节不进入用户帮助。

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
    title: "登录与工作身份",
    items: [
      {
        term: "登录方式",
        text: "使用公司账号的邮箱和密码登录；企业微信登录需要管理员先配置。登录服务暂不可用时，点击「重新连接」；企业微信登录失败时可尝试账号登录或联系管理员。",
      },
      {
        term: "切换工作身份",
        text: "有多个身份时，从侧栏底部账号入口选择当前工作身份。菜单和操作范围随身份变化；角色或项目成员关系调整后，以最新权限为准。身份异常时只选择系统提供的有效身份，不需要自行清理浏览器数据。",
      },
      {
        term: "业务身份",
        text: "公司业务身份与项目成员角色共同决定操作范围。个人资料由本人管理；项目资料由该项目的有效项目经理管理；公司资料由总经理或咨询总监管理。维护人安排不会额外授予知识管理或原文权限。",
      },
      {
        term: "系统管理员",
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
        text: "个人知识仅本人可见。项目有效成员可读取本项目原文；其他有效业务用户可发现项目 L1–L4 资料，但只能查看获准展示的安全摘要。跨项目 L3、L4 没有脱敏摘要时不展示普通摘要，L5 不可发现。公司职务或系统管理员身份不会自动授予其他项目原文权限。",
      },
      {
        term: "语义检索",
        text: "通过全库搜索查找有权限的知识，结果按权限裁剪并脱敏。准确标题与标签可帮助定位；较长的口语问题可补充有限的检索词组，转换失败仍保留原查询。结果数量有限，未命中不等于资料不存在，可缩小目录或使用更具体的标题、标签。搜索与问答不会因为使用自然语言而绕过保密等级或原文授权。未完成索引或解析的资料可能暂时无法参与问答，可查看详情中的可用状态。",
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
        text: "删除后资料退出检索、问答和预览，并保留审计记录。个人资料由本人删除；项目资料由该项目的有效项目经理删除；公司资料由总经理或咨询总监删除。陈旧资料需保留历史时，优先归档而不是删除。",
      },
    ],
  },
  {
    id: "directories",
    title: "正式目录与公司库治理",
    items: [
      {
        term: "使用正式目录",
        text: "上传和编辑资料时选择正式目录。公司知识资产页的「新建目录」由总经理或咨询总监使用；项目知识资产页由该项目的有效项目经理使用。选择标准分类并创建后，目录即可用于浏览、上传和编辑，不发布其他草稿。全局标准分类仍在「目录治理」维护，保存草稿后还需发布才能生效。",
      },
      {
        term: "目录与资料分开管理",
        text: "发布目录配置不会自动移动旧资料。单份资料可通过「编辑资料」调整正式目录；「目录治理」中的迁移操作需要核验候选再执行。目录配置与资料变更均保留操作记录。",
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
        text: "在资料详情点击「知识维护与复核」，在弹窗内安排维护人和下次复核日期；「知识维护」页面用于查找待办并进入资料处理。到期只提醒，不自动删除或归档。调整维护人或复核日期不视为内容更新，不会让已复核资料变成「修改后待复核」。",
      },
      {
        term: "复核资料",
        text: "先指定维护人，由有管理权限的人检查内容、密级、目录及适用范围后登记复核，并设置未来的下次复核日期。真实内容或元信息修改后需要重新复核；存在未处理纠错时不能直接标记为已复核。历史资料不会仅因启用此功能就自动成为已验证资料。",
      },
      {
        term: "关联新版并处理旧版",
        text: "正文变化时，在原资料详情选择「更新这份资料」，填写高于原版本的新版本号并上传文件。新版沿用原库、资料区、目录和密级，继续完成处理、确认入库与复核；此时旧版仍保持有效。从「版本历史与差异」核对新版后，明确确认替代并归档旧版。旧版退出默认检索与问答，历史文件保留，旧版链接指向当前版本；不会自动改写原文件或扩大权限。",
      },
      {
        term: "查看版本历史与差异",
        text: "资料详情的「版本历史与差异」显示关联版本和新版任务，可选择两个版本比较可见摘要与版本元信息。比较不是原文件全文差异，不会绕过原文或密级权限；上传成功也不等于已经替代旧版。",
      },
      {
        term: "反馈错误",
        text: "从资料详情的「知识维护与复核」按钮打开弹窗，填写具体问题后提出纠错。纠错不会赋予原文访问权，也不会开放其他人的反馈记录；提交人和有管理权限的人可跟踪自己有权查看的反馈。",
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
    intro:
      "上传或确认微盘文件后，检查内容建议和必填字段，再提交入库；需要审批的资料会进入审核流程。",
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
    ],
  },
  {
    id: "project",
    title: "项目知识与问答",
    items: [
      {
        term: "项目创建",
        text: "由总经理或咨询总监创建项目空间，指定有效业务用户为项目经理，系统同时建立项目成员关系。仅有系统管理员身份不能创建业务项目。",
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
        text: "项目经理在「项目设置」修改本项目配置、管理辅导老师与顾问；总经理或咨询总监负责任命或撤销项目经理。",
      },
    ],
  },
  {
    id: "original-access",
    title: "原文访问申请",
    items: [
      {
        term: "申请与审批",
        text: "摘要可见不等于原文可见。资料详情出现「申请原文访问」时，可逐项申请，并在「原文访问审批」查看进度；审批人按本人权限处理申请。获准查看某份原文不代表可以进入整个项目空间。",
      },
      {
        term: "授权有效期",
        text: "审批通过后可在有效期内查看原文，过期后自动失效。在「原文访问审批 → 授权记录」查看本人或当前可管理的授权；有撤销权时填写理由并确认撤销。撤销只影响这一条授权，不改变人员角色，已有其他访问依据时仍可能查看原文；已加载或缓存的内容无法收回，后续访问会重新校验权限。",
      },
      {
        term: "超时申请",
        text: "L1、L2 申请超过配置的自动通过时限且仍未审批时，可由后台生成授权；L3、L4、L5 不会超时自动通过。实际是否已授权以申请状态为准。",
      },
      {
        term: "在线预览",
        text: "原文预览为只读，不用于直接修改文件。预览服务未启用或文件类型不支持时，页面会给出提示；请联系管理员或资料维护人处理，不要重复申请来尝试绕过限制。",
      },
    ],
  },
  {
    id: "review",
    title: "升级审核与入库确认",
    items: [
      {
        term: "资产化确认",
        text: "项目过程资料进入资产区前，先完成真实内部分享或客户验证并登记证据，再由项目经理确认。入库成功或复核通过不等于完成资产化，证据登记也不替代真实业务验证。",
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
        term: "发布到公司知识库",
        text: "符合条件的项目资产由项目经理提交公司发布申请，须一名总经理和一名咨询总监分别确认。任一方拒绝或撤回均不能完成发布，可在「升级审核」跟踪处理状态。",
      },
    ],
  },
  {
    id: "admin",
    title: "管理与运行维护",
    intro: "以下入口按当前工作身份开放；系统管理员的运维权限不等于业务知识访问权限。",
    items: [
      {
        term: "入库管理",
        text: "在「入库管理」查看上传、确认、审批、解析和索引状态。失败时先核对任务原因及已有结果，再使用页面提供的重试操作；不要把文件上传完成当作入库完成。",
      },
      {
        term: "检索索引运维",
        text: "对失败、跳过或待索引资料，可在运维入口发起索引恢复；已上传但解析异常时，可选择「重新解析」。操作由后台执行，需继续查看作业结果；恢复或重新解析不会扩大知识访问权限。",
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
        text: "总经理或咨询总监可在「权限规则」调整公司低密级原文规则和访问申请自动通过时限，系统管理员只读。跨项目原文仍需逐份授权，不因规则配置取得整个项目的访问权。",
      },
      {
        term: "人员权限",
        text: "总经理可管理总经理、咨询总监和顾问；咨询总监可管理咨询总监和顾问，但不可修改总经理。总经理 / 咨询总监任命项目经理，项目经理独立管理本项目辅导老师与顾问。系统管理员仅查看审计与必要运行状态，不进入人员、角色或项目成员治理。",
      },
      {
        term: "公司知识库",
        text: "总经理或咨询总监在「公司知识库」创建并检查知识库状态，初始化完成前不能用于公司范围入库。资料归档在「公司库治理」进行，目录配置在「目录治理」进行。",
      },
      {
        term: "告警设置",
        text: "在「告警设置」查看规则与通知记录。企业微信消息需要启用通知配置；站内通知存在不代表企业微信消息已送达。",
      },
    ],
  },
  {
    id: "release-notes",
    title: "版本日志与公告",
    items: [
      {
        term: "查看更新",
        text: "点击侧栏底部「更新日志」查看已发布说明。未读提示按账号记录；只有已发布的日志会展示给普通用户。",
      },
      {
        term: "审核日志草稿",
        text: "系统管理员在「版本日志管理」编辑和预览草稿。完成对应版本的部署验证后才允许发布公告；部署生成草稿不会立即通知用户。发布前核对业务验收结果、说明和未读提醒选项；发布后记录不可直接改写，提醒不会发送邮件或企业微信消息。",
      },
    ],
  },
  {
    id: "models",
    title: "模型配置",
    intro: "在「模型配置」分别检查内容生成模型与检索底座状态。",
    items: [
      {
        term: "内容生成模型",
        text: "用于内容建议、项目问答以及统一检索和 MCP 问答，由管理员配置。统一检索和 MCP 问答沿用平台保存的默认模型；停用默认模型后需重新配置，不能依赖旧配置自动恢复。生成失败时先检查模型状态，内容建议不完整可人工补全；不应将失败结果视为已生成成功。",
      },
      {
        term: "WeKnora 底座模型",
        text: "用于知识库初始化和检索，与内容生成模型分开配置。修改默认模型不会自动重建已有知识库；检索异常时需继续核对索引及解析状态。",
      },
    ],
  },
  {
    id: "integration",
    title: "MCP 接入",
    intro:
      "从「MCP 接入」连接 WorkBuddy、Codex 等支持 MCP 的助手，访问和操作始终以调用人的当前权限为准。",
    items: [
      {
        term: "手动凭证接入",
        text: "支持手动 Bearer 凭证的客户端，可在「MCP 接入」生成本人配置并按客户端格式接入，保留已有的其他连接配置。请妥善保存仅生成时展示的凭证，不要发到群聊或公开文档；重新生成会使原手动凭证失效，使用它的助手需要更新配置。",
      },
      {
        term: "OAuth 登录授权",
        text: "支持 OAuth 的客户端可在其 MCP 连接设置选择 OAuth，填写本平台地址的 /mcp 接口，按跳转登录 KAP，核对应用名称和返回地址后选择「同意并连接」。这种方式不需要复制手动 Bearer 凭证；不能用「无需身份验证」绕过。平台尚未启用 OAuth 或授权请求失效时，请联系管理员或回到客户端重新连接，不要分享登录信息或授权链接。",
      },
      {
        term: "管理应用授权",
        text: "在「MCP 接入」的「已授权应用」查看 OAuth 应用的权限与到期时间，不再使用时选择「撤销授权」。OAuth 授权和手动凭证分别管理；撤销后需要重新连接并授权才能恢复。应用申请上传、入库确认或审批权限时，须在授权页明确同意，每次业务操作仍需本人明确授权，不能代替他人审批。",
      },
      {
        term: "只读与操作权限",
        text: "默认只读。需要助手代办时显式启用上传与审批操作权限；授权不会提升本人业务权限。支持的流程包括上传、命名预览、确认入库和有权限的审核操作，具体可用工具及限制以连接后返回的能力为准。重新生成凭证前应检查权限选项，提交或审批前核对对象和操作内容。",
      },
      {
        term: "操作边界",
        text: "助手上传文件前应读取限制，按工具提供的流程执行。资料维护、新版关联和纠错等页面能力不代表都已开放为 MCP 工具，未列出的操作仍在平台对应入口办理。外部助手不能代替他人身份或绕过审批。",
      },
      {
        term: "核对问答结果",
        text: "助手返回资料卡片不等于问题已有答案。问答会区分有依据答案、可访问资料不足和模型暂不可用；资料不足时明确拒答，不用无关资料凑引用。收到答案仍需核对引用内容和适用范围，异常引用或生成失败不视为回答成功。",
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
            返回 <Link to="/knowledge">知识资产库</Link>，或通过上方目录查找操作说明。
          </p>
        </main>
      </div>
    </ProductPage>
  );
}
