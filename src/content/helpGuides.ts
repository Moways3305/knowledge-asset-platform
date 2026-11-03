import type { can } from "../auth/permissions";
export interface HelpImage {
  src: string;
  alt: string;
  caption: string;
}
export interface HelpSection {
  id: string;
  title: string;
  paragraphs?: string[];
  steps?: string[];
  after?: string;
  note?: string;
  image?: HelpImage;
}
export interface HelpGuide {
  id: string;
  group: string;
  title: string;
  summary: string;
  audience: string;
  entry: string;
  to: string;
  capability: keyof typeof can;
  sections: HelpSection[];
  faq?: { question: string; answer: string }[];
  related: string[];
}
export const HELP_GUIDES: HelpGuide[] = [
  {
    id: "quick-start",
    group: "开始使用",
    summary:
      "把工作中的资料整理为可查找、可复用的知识。先了解资料存放在哪里，再选择你要完成的事情。",
    audience: "所有用户",
    entry: "登录后 → 工作台",
    to: "/",
    capability: "viewHome",
    title: "认识知识资产平台",
    sections: [
      {
        id: "libraries",
        title: "资料存放在哪里",
        paragraphs: [
          "个人库保存自己的资料，适合整理尚未共享的内容。只有本人能查看和主动提交到项目。",
          "项目库汇集一个项目的资料。过程材料保存在资料区，完成验证并由项目经理确认的内容进入资产区。",
          "公司库保存完成公司发布的知识，供跨项目复用。能看到摘要，不一定能打开原文件。",
        ],
      },
      {
        id: "navigation",
        title: "从哪个入口开始",
        paragraphs: [
          "知识库：按目录浏览、搜索正文，打开资料详情。我的知识用于管理个人资料，知识维护用于查找需要复核或纠错的事项。",
          "项目空间：选择项目后，查看概览、项目知识、问答和设置。知识库中的项目库侧重查资料，项目空间侧重项目内协作。",
          "审批中心：办理项目入库、资产化、公司发布与原文访问申请。",
          "工作台：查看需要你处理的任务和最近动态。管理中心供有管理职责的人维护人员、目录与系统配置。",
        ],
      },
      {
        id: "first-task",
        title: "第一次使用可以做什么",
        paragraphs: [
          "想找资料，从搜索正文或目录浏览开始。想保存文件，从上传资料到个人库开始。",
          "需要参与项目工作，先请项目经理确认成员关系，再阅读项目空间教程。",
        ],
      },
    ],
    faq: [
      {
        question: "为什么我和同事看到的入口不一样？",
        answer:
          "找不到菜单或按钮时，先核对当前身份和项目成员关系。请向项目经理或业务治理人员说明需要办理的具体事项。",
      },
    ],
    related: ["knowledge", "browse", "ingest", "project"],
  },
  {
    id: "identity",
    group: "开始使用",
    summary: "使用自己的账号进入平台，区分公司身份和项目角色。",
    audience: "所有用户",
    entry: "登录页 / 账号菜单",
    to: "/",
    capability: "viewHome",
    title: "登录与切换工作身份",
    sections: [
      {
        id: "login",
        title: "登录平台",
        steps: [
          "打开公司提供的平台地址，使用邮箱和密码登录。已配置企业微信时，可选择企业微信登录。",
          "进入后先检查账号菜单显示的当前身份。",
        ],
      },
      {
        id: "switch",
        title: "切换工作身份",
        steps: [
          "桌面打开左下角账号菜单；手机进入“我的”。",
          "从系统提供的有效身份中选择需要使用的身份。",
          "回到业务页面，查看更新后的菜单和任务。",
        ],
        note: "公司身份和项目角色分别管理。在一个项目中是经理，不代表在其他项目中也是经理。",
      },
    ],
    faq: [
      {
        question: "登录过期或没有可选身份怎么办？",
        answer:
          "会话到期请重新登录；服务不可用时按页面提示重新连接。没有身份或项目时，请由业务治理人员核对账号和成员关系。",
      },
    ],
    related: ["mobile", "people", "project-settings"],
  },
  {
    id: "notifications",
    group: "开始使用",
    summary: "区分需要办理的任务与告知消息，找到具体处理对象。",
    audience: "所有用户，内容按权限展示",
    entry: "工作台 / 顶栏任务与铃铛图标",
    to: "/",
    capability: "viewHome",
    title: "查看任务和通知",
    sections: [
      {
        id: "steps",
        title: "查看任务和通知",
        steps: [
          "工作台按待处理、进行中和已完成展示事项。点击具体任务，核对对象、当前状态和下一步。",
          "顶栏任务图标可随时打开任务中心，从对应任务进入确认、审批或维护页面。",
          "铃铛打开通知中心。「待处理」显示需行动的提醒，「动态」显示其他变化；点击标题或「前往处理」进入对应记录。",
          "办理后返回列表或刷新，核对最新结果。将消息标为已读不会完成审批、入库确认或维护。",
        ],
        after: "提醒能对应到具体业务记录，完成状态以业务记录为准。",
      },
    ],
    faq: [
      {
        question: "消息已读，为什么任务还在？",
        answer: "已读但待处理并不矛盾。目标失效或权限变化时按页面提示处理，避免重复提交。",
      },
    ],
    related: ["review", "original-access", "upload-history"],
  },
  {
    id: "knowledge",
    group: "查找与使用知识",
    summary:
      "知道正文中的关键词、编号或独特标记时，用全库搜索查找资料。例如，查找正文中出现“设备点检”的资料。",
    audience: "业务用户",
    entry: "知识库 → 知识资产库",
    to: "/knowledge",
    capability: "viewKnowledge",
    title: "搜索资料正文",
    sections: [
      {
        id: "search",
        title: "输入正文关键词",
        steps: [
          "进入知识库，在左侧选择“全库搜索”。手机上使用资料范围切换区。",
          "在“正文关键词或内容描述”中输入关键词，例如“设备点检”，点击“检索内容”。",
        ],
        image: {
          src: "/help-images/knowledge-search.png",
          alt: "全库搜索范围、正文关键词输入框与检索内容按钮",
          caption: "选择全库搜索后，在正文关键词输入框中检索。",
        },
      },
      {
        id: "read",
        title: "查看搜索结果",
        steps: [
          "点击结果标题打开资料详情，核对摘要、所属范围和版本。",
          "需要查找历史资料时，勾选“包含归档”后重新检索。",
        ],
        after: "结果只包含有权发现的资料。需要原文件时，再从详情办理原文访问。",
      },
    ],
    faq: [
      {
        question: "完整标题能搜到，正文关键词搜不到怎么办？",
        answer:
          "先确认使用的是“全库搜索”，而不是目录中的标题或标签搜索。新资料还需要完成索引；可在详情检查问答索引状态，异常时联系管理员。",
      },
    ],
    related: ["browse", "detail", "original-access"],
  },
  {
    id: "detail",
    group: "查找与使用知识",
    summary: "打开资料后，先读摘要和适用范围，再查看版本、原文与维护信息。",
    audience: "可访问资料的用户；编辑仅限有管理权限的人",
    entry: "知识库 → 点击资料标题",
    to: "/knowledge",
    capability: "viewKnowledge",
    title: "查看资料详情",
    sections: [
      {
        id: "summary",
        title: "阅读内容摘要",
        steps: [
          "从知识库点击资料标题，进入详情。",
          "在“内容摘要”中阅读摘要和要点，核对所属项目、保密等级、适用范围及版本。",
        ],
      },
      {
        id: "preview",
        title: "打开原文预览",
        steps: [
          "需要核对原文件时，打开原文预览入口。只有摘要权限时，先提交原文申请。",
          "阅读后关闭预览，回到资料详情。",
        ],
        note: "原文预览是只读的。需要更新文件内容时，请上传新版本。",
      },
      {
        id: "tabs",
        title: "查看版本与维护信息",
        paragraphs: [
          "打开“版本记录”查看关联版本和更新任务。需要安排复核、提交纠错或公司发布时，打开“维护与发布”。",
        ],
      },
    ],
    faq: [
      {
        question: "有权限却打不开预览怎么办？",
        answer:
          "授权过期或撤销时需要重新申请；文件格式不支持或预览服务未配置，则需要管理员处理。重复申请不能解决预览服务故障。",
      },
    ],
    related: ["original-access", "edit", "versions", "maintenance"],
  },
  {
    id: "original-access",
    group: "查找与使用知识",
    summary: "能看到摘要，但需要查看原文件时这样操作。",
    audience: "页面提供申请入口的业务用户",
    entry: "资料详情 → 申请原文访问",
    to: "/original-access?box=mine",
    capability: "viewOriginalAccess",
    title: "申请原文访问",
    sections: [
      {
        id: "steps",
        title: "申请原文访问",
        steps: [
          "在资料详情选择「申请原文访问」，核对资料标题，说明用途后提交。",
          "进入「审批中心 → 原文访问 → 我的申请」查看进度，不要为同一资料重复申请。",
          "通过后回到资料详情，在有效期内查看原文。单份原文授权不等于加入整个项目。",
          "在「授权记录」核对期限和状态；到期或撤销后，按业务需要重新申请。",
        ],
        after: "申请有明确状态，是否能预览由当前有效权限决定。",
      },
    ],
    faq: [
      {
        question: "申请通过后仍不能预览怎么办？",
        answer:
          "审批通过仍打不开时，检查授权期限、资料状态和预览服务提示。摘要可见不等于原文可见。",
      },
    ],
    related: ["access-rules", "detail"],
  },
  {
    id: "ingest",
    group: "上传与整理资料",
    summary: "把本地文件保存到自己的个人库，供后续查找、整理或提交给项目。",
    audience: "业务用户",
    entry: "知识库 → 上传资产 → 本地上传",
    to: "/upload",
    capability: "viewUpload",
    title: "上传资料到个人库",
    sections: [
      {
        id: "select",
        title: "选择本地文件",
        steps: [
          "在知识库右上角点击“上传资产”，进入上传工作区，选择“本地上传”。",
          "点击“选择文件”添加文件，也可以拖入上传区域。文件夹可通过“选择文件夹”添加。",
        ],
        image: {
          src: "/help-images/upload-start.png",
          alt: "选择文件、选择文件夹入口及左侧上传记录",
          caption: "先选择文件，再在下方文件任务中跟踪处理进度。",
        },
      },
      {
        id: "confirm",
        title: "核对并确认入库",
        steps: [
          "在“文件任务”中找到刚上传的文件。处理完成后打开待确认项，进入“确认入库”。",
          "将“目标知识库”选为个人库。检查标题、摘要、要点、标签与保密等级，修正不准确的建议。",
          "确认字段完整后，点击底部“确认入库”。",
        ],
        after: "看到“资产已入库”后，可进入详情，也可在“我的知识”中找到它。",
      },
      {
        id: "next",
        title: "需要共享到项目时",
        paragraphs: [
          "个人资料不会自动对项目成员开放。需要共享时，由本人从“我的知识”提交到目标项目，项目经理确认后进入项目库。",
        ],
      },
    ],
    faq: [
      {
        question: "文件传完了，为什么还没出现在个人库？",
        answer:
          "传输后还要提取内容、核对信息并确认入库。先在文件任务中查看状态；显示待确认时，打开记录继续办理。",
      },
      {
        question: "摘要建议不准确怎么办？",
        answer: "在确认页修改摘要、要点或标签，再提交。建议是辅助内容，需要你核对。",
      },
    ],
    related: ["upload-project", "upload-history", "personal"],
  },
  {
    id: "upload-history",
    group: "上传与整理资料",
    summary: "断线、等待审批或失败时，找到已有任务继续办理。",
    audience: "上传或确认资料的业务用户",
    entry: "上传资料 → 上传记录",
    to: "/upload",
    capability: "viewUpload",
    title: "查看上传进度与失败原因",
    sections: [
      {
        id: "steps",
        title: "查看上传进度与失败原因",
        steps: [
          "打开上传记录，定位之前提交的文件或任务。",
          "查看记录处于待确认、待审批、处理中、已完成、已拒绝还是失败。",
          "待确认的继续核对字段；待审批的跟踪进度；失败任务先读原因，再使用该记录提供的修正或重试入口。",
          "已拒绝是明确的业务结果，先查看拒绝原因，不要把它当作仍在处理中。",
        ],
        after: "继续已有任务并看清下一步，避免重复入库。",
      },
    ],
    faq: [
      {
        question: "失败后需要重新上传吗？",
        answer:
          "刷新后仍有异常时，向管理员提供任务名称、发生时间和错误提示。没有重试按钮可能是状态或权限不允许。",
      },
    ],
    related: ["ingest", "review", "ingest-admin"],
  },
  {
    id: "personal",
    group: "上传与整理资料",
    summary: "已有个人资料需要与项目共享时，由本人提交给项目经理审核。",
    audience: "资料所有者",
    entry: "知识库 → 我的知识",
    to: "/my/knowledge",
    capability: "viewMyKnowledge",
    title: "把个人资料提交到项目",
    sections: [
      {
        id: "select",
        title: "找到个人资料",
        steps: [
          "进入知识库，点击“我的知识”。",
          "搜索标题或标签，打开需要提交的资料。尚待本人确认的记录，先完成确认。",
        ],
      },
      {
        id: "submit",
        title: "提交到目标项目",
        steps: [
          "使用资料的提交项目入口，选择你参与的目标项目。",
          "检查提交信息后确认，随后在“待项目审批”中跟踪进度。",
        ],
        after: "项目经理通过后，资料进入项目范围；拒绝时先查看原因，再修正信息。",
      },
    ],
    faq: [
      {
        question: "为什么不能选择目标项目？",
        answer: "没有目标项目时核对有效成员关系。项目经理不能拿他人的私有资料代为提交。",
      },
    ],
    related: ["ingest", "upload-project", "review"],
  },
  {
    id: "versions",
    group: "上传与整理资料",
    summary: "正文发生变化时，从原资料发起更新，把新文件与旧版关联起来。",
    audience: "有该资料管理权限的人",
    entry: "资料详情 → 更新这份资料 / 版本记录",
    to: "/knowledge",
    capability: "viewKnowledge",
    title: "上传新版本",
    sections: [
      {
        id: "upload",
        title: "上传新文件",
        steps: [
          "进入原资料详情，选择“更新这份资料”。",
          "填写高于当前版本的版本号并选择新文件。",
          "完成内容处理和入库确认，检查沿用的库、资料区、目录与密级。",
        ],
      },
      {
        id: "verify",
        title: "核验新版",
        steps: [
          "进入“版本记录”，打开新版，核对内容和入库状态。",
          "完成必要的审批与复核。确认新版可以使用后，再办理替代旧版。",
        ],
        after: "上传成功只代表新增版本，不会立即替代或归档旧版。",
      },
    ],
    faq: [
      {
        question: "上传成功后，旧版会自动归档吗？",
        answer: "不会。先核对新版并完成必要复核，再明确确认替代和归档旧版。",
      },
    ],
    related: ["version-compare", "version-replace", "upload-history"],
  },
  {
    id: "maintenance",
    group: "上传与整理资料",
    summary: "让资料有人维护，让提出问题的人核验处理结果。",
    audience: "资料管理人、维护人和纠错提交人，各按权限操作",
    entry: "知识维护 → 资料详情 → 维护与发布 → 知识维护与复核",
    to: "/knowledge-maintenance",
    capability: "viewKnowledge",
    title: "复核资料与处理纠错",
    sections: [
      {
        id: "steps",
        title: "复核资料与处理纠错",
        steps: [
          "在「知识维护」查看待安排、待复核、待纠错或待验证事项，点击进入资料详情。",
          "在「维护与发布」页签中，有管理权限时打开「知识维护与复核」，安排维护人和日期；核对内容、密级与适用范围后登记复核。",
          "发现错误时填写具体问题和依据并提交纠错。管理人应实际更正内容或关联新版，再处理反馈。",
          "提交人查看更新后的资料，确认解决；仍有问题时按条件继续反馈。只改日期或维护人不算修正内容。",
        ],
        after: "维护人 → 到期复核 → 内容更新 → 纠错处理 → 提出者验证，过程可跟踪。",
      },
    ],
    faq: [
      {
        question: "为什么不能登记复核？",
        answer: "有未处理纠错时不能直接标记已复核；维护人安排不额外授予原文或管理权限。",
      },
    ],
    related: ["versions", "detail"],
  },
  {
    id: "project",
    group: "项目协作与问答",
    summary: "围绕一个项目查看工作、资料和成员，区分两个项目入口。",
    audience: "有效项目成员；治理角色按允许范围查看",
    entry: "项目空间 → 选择项目",
    to: "/projects",
    capability: "viewProject",
    title: "使用项目空间",
    sections: [
      {
        id: "steps",
        title: "使用项目空间",
        steps: [
          "进入项目空间，查找并打开自己的项目，概览集中展示项目工作和最近资料。",
          "通过固定导航切换概览、知识库、问答和设置；项目切换器只选择本人有权进入的项目。",
          "项目知识库区分资料区与资产区：过程材料在资料区，完成验证与确认的知识在资产区。",
          "从概览进入上传、入库审批或原文申请等具体任务，操作前再次核对目标项目。",
        ],
        after: "知识库中的项目库用于查资料，项目空间用于成员协作；摘要权限不等于成员资格。",
      },
    ],
    faq: [
      {
        question: "为什么能看到摘要，却进不了项目空间？",
        answer: "能看摘要但进不了项目空间时，请项目经理核对成员关系。不要通过改网址尝试访问。",
      },
    ],
    related: ["project-qa", "project-settings", "knowledge"],
  },
  {
    id: "project-qa",
    group: "项目协作与问答",
    summary: "让回答基于当前项目知识，逐条检查引用是否支持结论。",
    audience: "有效项目成员，且问答模型可用",
    entry: "项目空间 → 项目 → 问答",
    to: "/projects",
    capability: "viewProject",
    title: "项目问答与引用",
    sections: [
      {
        id: "steps",
        title: "项目问答与引用",
        steps: [
          "核对当前项目名称和可用问答模型，避免在错误项目中提问。",
          "输入具体问题，例如「这份方案的验收条件是什么？请列出依据」。计算问题应说明基数、单位和时间范围。",
          "阅读回答与限制，点击引用打开有权查看的资料，核对版本、摘要和适用范围。",
          "缺少资料或计算基数时补充条件再问；模型不可用时联系管理员，不把错误提示或资料列表视为已回答。",
        ],
        after: "获得可追溯到项目资料的答案，或明确的依据不足、缺失信息、不可用提示。",
      },
    ],
    faq: [
      {
        question: "没有答案或没有引用怎么办？",
        answer:
          "没有模型先检查配置；有资料未被引用时核对索引、解析与权限。资料区内容还需业务判断。",
      },
    ],
    related: ["project", "knowledge", "models"],
  },
  {
    id: "project-create",
    group: "项目协作与问答",
    summary: "为新项目建立空间和负责人。",
    audience: "总经理 / 咨询总监",
    entry: "项目空间 → 新建项目",
    to: "/projects",
    capability: "viewCompanyKnowledge",
    title: "创建项目",
    sections: [
      {
        id: "steps",
        title: "创建项目",
        steps: [
          "点击「新建项目」，填写项目名称、客户及页面要求的信息。",
          "核对项目代码等校验要求，从有效业务用户中指定项目经理。",
          "确认后创建项目，进入概览核对信息与成员关系。",
          "后续经理任命或撤销在有权限的人员治理入口办理。",
        ],
        after: "项目空间建立，指定经理形成对应成员关系。",
      },
    ],
    faq: [
      {
        question: "找不到要指定的项目经理怎么办？",
        answer: "用户不在候选中时检查账号及业务身份。系统管理员不能代替业务治理角色创建项目。",
      },
    ],
    related: ["people", "project-settings", "project"],
  },
  {
    id: "project-settings",
    group: "项目协作与问答",
    summary: "维护本项目的配置、顾问和辅导老师。",
    audience: "目标项目经理；治理角色按页面权限操作",
    entry: "项目空间 → 项目 → 设置",
    to: "/projects",
    capability: "viewProject",
    title: "管理项目配置和成员",
    sections: [
      {
        id: "steps",
        title: "管理项目配置和成员",
        steps: [
          "打开目标项目设置，先确认项目名称。",
          "在基本配置中修改允许编辑的字段，检查后保存。",
          "在成员分区选择业务用户，按权限添加或调整顾问、辅导老师。",
          "移除成员前核对交接；项目经理任命或撤销由总经理或咨询总监办理。",
        ],
        after: "成员与配置按最新结果生效，项目角色不会自动用于其他项目。",
      },
    ],
    faq: [
      {
        question: "为什么没有编辑成员的按钮？",
        answer: "没有编辑操作时检查项目角色与状态；公司职务不自动授予项目原文权限。",
      },
    ],
    related: ["people", "project-create"],
  },
  {
    id: "review",
    group: "审批与资产发布",
    summary: "核对资料内容和目标范围，决定是否进入项目。",
    audience: "该项目经理；提交人可跟踪本人进度",
    entry: "审批中心 → 审核待办",
    to: "/review",
    capability: "viewReview",
    title: "审批项目入库",
    sections: [
      {
        id: "steps",
        title: "审批项目入库",
        steps: [
          "按审核类型和状态筛选，打开具体事项查看资料、来源与目标项目。",
          "核对标题、摘要、目录、密级和适用性，需要原文时按权限查看。",
          "使用详情的确认或拒绝操作，按表单要求补充说明，不只根据通知标题作决定。",
          "在「已完成任务」或上传任务核对结果。批准后仍需处理入库、索引，失败时按任务提示处理。",
        ],
        after: "通过的进入后续处理，拒绝有明确终态，不作为已入库资料参与检索。",
      },
    ],
    faq: [
      {
        question: "为什么审核列表中没有任务？",
        answer: "没有事项时检查身份、项目与筛选。待补证据的资产化任务需先登记真实验证依据。",
      },
    ],
    related: ["assetization", "publication", "upload-history"],
  },
  {
    id: "assetization",
    group: "审批与资产发布",
    summary: "完成真实分享或客户验证，登记证据后确认资产化。",
    audience: "项目成员提交，项目经理确认",
    entry: "项目资料 → 资产化操作 / 审核待办",
    to: "/review",
    capability: "viewReview",
    title: "确认项目知识资产化",
    sections: [
      {
        id: "steps",
        title: "确认项目知识资产化",
        steps: [
          "选择适合复用的项目资料，检查内容与信息完整性。",
          "完成真实内部分享或客户验证，再在页面提供的证据入口记录依据。",
          "项目经理打开审核任务核验证据，符合条件后确认；证据不足先补充。",
          "在项目知识库资产区核对结果，入库成功或复核通过不等于资产化完成。",
        ],
        after: "有真实验证依据并经确认的资料进入项目资产区。",
      },
    ],
    faq: [
      {
        question: "为什么不能确认资产化？",
        answer: "无法确认时检查资料状态、证据和当前项目角色，不能用虚构说明替代业务验证。",
      },
    ],
    related: ["review", "publication"],
  },
  {
    id: "publication",
    group: "审批与资产发布",
    summary: "将适合跨项目复用的项目资产发布到公司范围。",
    audience: "项目经理申请，总经理和咨询总监分别确认",
    entry: "资料详情 → 维护与发布 → 发布到公司知识库",
    to: "/review",
    capability: "viewReview",
    title: "发布到公司知识库",
    sections: [
      {
        id: "steps",
        title: "发布到公司知识库",
        steps: [
          "项目经理打开项目资产，检查发布条件，先处理未满足项。",
          "点击「发布到公司知识库」，选择正式目录，填写主题、适用对象、形成日期、版本和保密等级，预览规范名后提交。",
          "总经理与咨询总监分别在审核待办中核对资料并确认，每种身份各需一席。",
          "在审核待办跟踪最终状态。被拒绝时先查看原因；需要调整申请时，由申请人撤回，再核对内容后重新提交。",
        ],
        after: "满足条件且双席确认后进入公司范围；单席确认不代表发布成功。",
      },
    ],
    faq: [
      {
        question: "总经理已确认，为什么还没有发布？",
        answer:
          "公司发布需要总经理和咨询总监各一席确认。只有一方确认时仍在等待另一方；任一方拒绝或撤回都不能完成发布。",
      },
    ],
    related: ["assetization", "directories", "access-review"],
  },
  {
    id: "access-review",
    group: "审批与资产发布",
    summary: "核对申请用途，管理已有授权的期限与撤销。",
    audience: "当前申请审批人、有授权管理权限的人",
    entry: "审批中心 → 原文访问 / 授权记录",
    to: "/original-access?box=inbox",
    capability: "viewOriginalAccess",
    title: "审批原文申请",
    sections: [
      {
        id: "find",
        title: "打开待审批申请",
        steps: [
          "进入审批中心的“原文访问”，切换“待我审批”。",
          "打开申请，核对申请人、资料范围、用途和密级。",
        ],
      },
      {
        id: "decide",
        title: "通过或拒绝",
        steps: [
          "按业务需要通过或拒绝，填写要求的说明。",
          "提交后核对申请状态，通过的申请会形成原文授权。",
        ],
        after: "可在授权记录查看实际期限。需要收回访问权时，撤销对应的授权记录。",
      },
    ],
    faq: [
      {
        question: "授权什么时候失效？",
        answer:
          "实际到期时间在授权记录中查看。到期后自动失效；有管理权限的人也可以提前撤销对应授权。",
      },
    ],
    related: ["original-access", "revoke-access", "permissions"],
  },
  {
    id: "directories",
    group: "业务治理",
    summary: "先人工核验候选，再归档陈旧资料或恢复历史内容。",
    audience: "总经理 / 咨询总监",
    entry: "管理中心 → 公司库治理",
    to: "/company-governance",
    capability: "viewCompanyKnowledge",
    title: "归档公司资料",
    sections: [
      {
        id: "review",
        title: "核验待归档资料",
        steps: [
          "进入公司库治理，在“待核验”或“全部在库”查找资料。",
          "打开资料，核对内容是否仍适用、是否已有新版；不要仅因同名或年份较早就归档。",
        ],
      },
      {
        id: "archive",
        title: "预览并确认归档",
        steps: [
          "选择需要归档的资料，打开归档预览。",
          "核对清单并填写原因，确认归档。",
          "查看逐项结果，单独处理失败项。",
        ],
        after: "归档资料进入归档中心，退出默认检索与问答，原文件和历史仍保留。",
      },
    ],
    faq: [
      {
        question: "候选资料一定要归档吗？",
        answer: "候选只是管理建议，不会自动归档。归档不是删除原文件；已被替代的旧版不能直接恢复。",
      },
    ],
    related: ["restore", "version-replace", "company-settings"],
  },
  {
    id: "company-settings",
    group: "业务治理",
    summary: "在公司库治理打开设置，无需寻找独立配置页。",
    audience: "总经理 / 咨询总监；删除仅总经理",
    entry: "公司库治理 → 右上角设置",
    to: "/company-governance?settings=knowledge-base",
    capability: "viewCompanyKnowledge",
    title: "初始化公司知识库",
    sections: [
      {
        id: "steps",
        title: "初始化公司知识库",
        steps: [
          "打开公司库治理，点击右上角「设置」。",
          "核对名称、可用性、初始化状态和创建时间，需要时点「刷新状态」。",
          "未创建时按提示创建；初始化失败先排查底座配置，再使用重试入口。",
          "正常使用无需操作危险区域。确需删除时先满足清空资产等条件，输入库名并二次确认；日常整理应归档资料。",
        ],
        after: "初始化完成且可用后，才用于公司知识入库。",
      },
    ],
    faq: [
      {
        question: "初始化失败怎么办？",
        answer:
          "联系配置人员检查模型与服务连接，修复后使用“重试初始化”。不要反复删除并创建知识库。",
      },
    ],
    related: ["directories", "models"],
  },
  {
    id: "naming",
    group: "业务治理",
    summary: "区分新增目录和全局标准变更，避免误发布。",
    audience: "治理角色维护全局标准，项目经理管理本人项目允许的目录",
    entry: "知识库 → 新建目录；管理中心 → 目录治理",
    to: "/admin/naming-rules",
    capability: "viewNamingRules",
    title: "管理正式目录",
    sections: [
      {
        id: "steps",
        title: "管理正式目录",
        steps: [
          "日常新增目录：在有管理权的公司库或项目库点「新建目录」，选择标准分类并填写表单。",
          "修改全局标准：进入目录治理，核对当前版本，在对应分区编辑草稿。",
          "保存草稿后还需发布才能生效；核对差异后再发布，不会自动移动旧资料。",
          "单份资料通过编辑资料调整目录；批量迁移先核验候选和预检，再执行并核对结果。",
        ],
        after: "目录标准和资料归属分别有明确的版本与变更结果。",
      },
    ],
    faq: [
      {
        question: "草稿冲突时怎么办？",
        answer: "草稿冲突时重新加载，不能覆盖他人刚保存的版本。新建单个正式目录不会发布其他草稿。",
      },
    ],
    related: ["ingest", "detail"],
  },
  {
    id: "people",
    group: "业务治理",
    summary: "分别管理账号、公司角色和项目任职。",
    audience: "总经理 / 咨询总监，按可管理层级操作",
    entry: "管理中心 → 人员权限",
    to: "/admin/people",
    capability: "viewPeople",
    title: "管理人员身份和项目任职",
    sections: [
      {
        id: "steps",
        title: "管理人员身份和项目任职",
        steps: [
          "搜索并打开人员详情，核对账号，避免操作同名用户。",
          "在账号和公司角色分区调整允许管理的身份，提交前核对职责。",
          "在项目任职中选择项目，按权限任命或撤销经理；普通项目成员由对应经理在项目设置管理。",
          "检查返回结果与最新状态；已打开的业务页面也应按最新权限核对。",
        ],
        after: "公司身份与具体项目职责各自生效。",
      },
    ],
    faq: [
      {
        question: "哪些身份不能管理人员？",
        answer:
          "咨询总监不能修改总经理，系统管理员不能进入业务人员治理。公司角色不能绕过项目原文边界。",
      },
    ],
    related: ["identity", "project-settings", "permissions"],
  },
  {
    id: "permissions",
    group: "业务治理",
    summary: "区分可编辑规则、固定策略和只读参考值。",
    audience: "治理角色可修改允许的规则，系统管理员只读",
    entry: "管理中心 → 权限规则",
    to: "/admin/permissions",
    capability: "viewPermissions",
    title: "设置权限规则",
    sections: [
      {
        id: "steps",
        title: "设置权限规则",
        steps: [
          "按分组查找原文、申请或授权规则，阅读当前值和说明。",
          "只编辑有入口的规则，核对单位、范围和影响后保存。",
          "授权期限与自动通过时限按服务端流程执行，已有授权的实际状态在授权记录检查。",
          "外部助手白名单在对应分区办理；参考值不代表当前运行规则。",
        ],
        after: "允许修改的规则由服务端校验执行，系统固定策略保持只读。",
      },
    ],
    faq: [
      {
        question: "为什么有些规则不能编辑？",
        answer: "无编辑按钮可能是身份或规则本身只读。归档预警条件在告警设置，归档仍需人工确认。",
      },
    ],
    related: ["access-review", "alerts", "integration"],
  },
  {
    id: "ingest-admin",
    group: "运行与系统管理",
    summary: "先判断资料为什么不可检索，再使用对应恢复动作。",
    audience: "有入库管理权限的治理人员或系统管理员",
    entry: "管理中心 → 入库管理",
    to: "/admin/ingest",
    capability: "viewIngestAdmin",
    title: "恢复索引与解析",
    sections: [
      {
        id: "steps",
        title: "恢复索引与解析",
        steps: [
          "查看状态摘要和待恢复任务，区分提交中断、解析中和解析中断。",
          "筛选具体任务，核对原因、处理阶段及已有结果。",
          "对允许恢复的任务发起索引恢复；已提交但解析异常时使用重新解析，执行前核对确认信息。",
          "持续查看作业记录，必要时查看运行诊断；已提交后台作业不等于恢复完成。",
        ],
        after: "恢复处理并核对是否可检索，不扩大资料访问权。",
      },
    ],
    faq: [
      {
        question: "恢复操作提交后还搜不到怎么办？",
        answer: "无对账记录、模型不兼容或连接异常时先解决环境问题。不要重复上传代替修复已有任务。",
      },
    ],
    related: ["upload-history", "models", "audit"],
  },
  {
    id: "wecom-scan",
    group: "运行与系统管理",
    summary: "从受控目录发现文件，再进入正常入库流程。",
    audience: "有对应扫描配置权限的人；项目经理限本人项目",
    entry: "管理中心 → 微盘扫描；上传 → 企微微盘待确认",
    to: "/admin/wecom-scan",
    capability: "viewWecomScan",
    title: "配置微盘扫描",
    sections: [
      {
        id: "steps",
        title: "配置微盘扫描",
        steps: [
          "确认企业微信连接已配置，在微盘扫描新建或编辑允许范围的目录配置。",
          "指定目录、业务范围和合法的待确认归属人，核对后保存。",
          "按页面运行入口发起扫描或查看记录，检查是否生成任务。",
          "归属人在上传工作区选择「企微微盘待确认」，打开文件核对建议与必填字段，再提交入库。",
        ],
        after: "扫描生成待确认任务，不绕过人工核对或项目审批。",
      },
    ],
    faq: [
      {
        question: "扫描后为什么没有待确认文件？",
        answer: "未发现文件时检查目录权限、连接和归属人资格；运维身份不因此获得业务原文权。",
      },
    ],
    related: ["ingest", "ingest-admin"],
  },
  {
    id: "models",
    group: "运行与系统管理",
    summary: "生成服务、底座模型和具体知识库分别配置。",
    audience: "有模型配置权限的人，项目经理限本人项目允许的配置",
    entry: "管理中心 → 模型配置",
    to: "/admin/weknora-models",
    capability: "viewModels",
    title: "配置生成模型与知识检索",
    sections: [
      {
        id: "steps",
        title: "配置生成模型与知识检索",
        steps: [
          "查看连接状态和当前身份可用操作。",
          "系统管理员在「管理外部 LLM」配置生成服务和默认用途；只读身份可核对状态，凭证只填入受控输入框。",
          "有修改权限时在「管理 WeKnora 模型」维护检索所需模型，再核对默认底座；只读身份请联系系统管理员。",
          "在「管理知识库配置」查找具体库，按权限调整；修改默认模型不会自动重建已有库。保存后回实际任务验证。",
        ],
        after: "生成与检索使用各自有效配置，失败显示实际提示。",
      },
    ],
    faq: [
      {
        question: "问答或检索不可用，应检查什么？",
        answer:
          "问答不可用先查生成模型，检索异常还要查索引解析。停用平台保存的默认模型后需重新配置，不依赖旧配置自动恢复。",
      },
    ],
    related: ["project-qa", "ingest-admin", "company-settings"],
  },
  {
    id: "alerts",
    group: "运行与系统管理",
    summary: "调整何时提醒，区分规则级别与当前故障。",
    audience: "治理人员维护，其他身份以页面权限为准",
    entry: "管理中心 → 告警设置",
    to: "/admin/alert-settings",
    capability: "viewAlerts",
    title: "设置告警阈值",
    sections: [
      {
        id: "steps",
        title: "设置告警阈值",
        steps: [
          "按级别和状态筛选，核对规则名称、阈值单位和通知渠道。",
          "点对应行最右侧「编辑」，输入新值后「保存阈值」；放弃则点「取消」。",
          "要调整启用状态，操作该规则的状态按钮并核对结果。",
          "在通知中心看相关提醒。规则显示「严重」只表示等级，不意味着此刻发生了故障。",
        ],
        after: "仅保存成功的阈值和状态生效，取消不提交修改。",
      },
    ],
    faq: [
      {
        question: "保存失败或通知没收到怎么办？",
        answer: "保存失败按提示修正；站内通知不代表企业微信已送达，企微通知需另外配置。",
      },
    ],
    related: ["notifications", "audit", "ingest-admin"],
  },
  {
    id: "audit",
    group: "运行与系统管理",
    summary: "按时间和事件定位操作或异常，取得必要排查线索。",
    audience: "治理人员和系统管理员按范围查看；登录安全仅管理员",
    entry: "管理中心 → 审计日志 / 登录安全",
    to: "/admin/audit",
    capability: "viewAudit",
    title: "查询审计日志",
    sections: [
      {
        id: "steps",
        title: "查询审计日志",
        steps: [
          "选择有权查看的操作或异常记录，用时间与其他条件筛选。",
          "打开详情核对事件、对象、结果和时间，只使用页面提供的安全信息排查。",
          "管理员排查登录问题时进入「登录安全」，检查对应时间窗口与尝试记录。",
          "反馈故障时提供时间、入口、对象名称和错误提示，勿附凭证、密码或无关敏感数据。",
        ],
        after: "获得可追溯的依据，不因审计权限获得业务原文权。",
      },
    ],
    faq: [
      {
        question: "为什么查不到某条操作？",
        answer: "未找到记录先检查时间和角色范围。审计不是办理入口，需要操作时回对应业务页面。",
      },
    ],
    related: ["alerts", "ingest-admin", "identity"],
  },
  {
    id: "release-notes",
    group: "账号与外部工具",
    summary: "了解已发布变化，找到当前功能的操作教程。",
    audience: "所有用户",
    entry: "桌面帮助与更新；手机我的 → 全部功能",
    to: "/release-notes",
    capability: "viewReleaseNotes",
    title: "查看更新日志",
    sections: [
      {
        id: "open",
        title: "打开更新日志",
        steps: [
          "桌面打开“帮助与更新 → 更新日志”；手机从“我的”进入全部功能查找更新日志。",
          "阅读版本说明，了解变化；需要更早的内容时分页查看历史记录。",
        ],
      },
    ],
    faq: [
      {
        question: "为什么看不到刚部署的版本？",
        answer: "没有某版本公告不等于服务未更新；公告发布后普通用户才可见。",
      },
    ],
    related: ["quick-start", "notifications"],
  },
  {
    id: "release-admin",
    group: "运行与系统管理",
    summary: "部署验证后审核面向用户的更新说明。",
    audience: "系统管理员",
    entry: "管理中心 → 版本日志管理",
    to: "/admin/release-notes",
    capability: "manageReleaseNotes",
    title: "发布版本公告",
    sections: [
      {
        id: "steps",
        title: "发布版本公告",
        steps: [
          "打开待审核草稿或新建草稿。",
          "填写版本与面向用户的变化，保存后预览检查。",
          "确认该版本完成部署验证，核对业务验收结果和未读提醒选项，再发布。",
          "到公开更新日志检查展示；已发布内容不可直接改写。",
        ],
        after: "普通用户看到已发布公告，部署生成草稿不会立即通知用户。",
      },
    ],
    faq: [
      {
        question: "为什么不能发布公告？",
        answer: "不满足部署验证条件时先完成验证；提醒不会发送邮件或企业微信消息。",
      },
    ],
    related: ["release-notes", "audit"],
  },
  {
    id: "integration",
    group: "账号与外部工具",
    summary: "使用支持 MCP 的助手，在本人权限内查询或代办明确授权的事项。",
    audience: "业务用户",
    entry: "账号菜单 → 个人工具接入",
    to: "/my/workbuddy",
    capability: "viewWorkbuddy",
    title: "连接外部助手",
    sections: [
      {
        id: "steps",
        title: "连接外部助手",
        steps: [
          "先确认客户端支持哪种方式，以及需要只读查询还是操作权限。",
          "手动凭证接入：生成本人配置，按客户端要求填写，保留其他连接。仅生成时展示的凭证请妥善保存，不发到群聊或公开文档。",
          "OAuth 登录授权：客户端填写平台 /mcp 地址，跟随跳转登录，核对应用、返回地址和申请权限，再选择「同意并连接」。",
          "在「已授权应用」查看权限和到期时间，不再使用时撤销授权。OAuth 与手动凭证分别管理；重新生成手动凭证会使旧手动凭证失效。",
          "默认只读。代办前显式启用需要的操作权限，每次业务操作仍需本人明确授权并核对对象；助手不能代替其他身份或提升本人权限。",
        ],
        after: "助手按实时权限工作；资料卡片不等于问题已有答案，仍应检查引用。",
      },
    ],
    faq: [
      {
        question: "客户端授权失败怎么办？",
        answer:
          "平台尚未启用 OAuth 时联系管理员；请求失效则回客户端重连，不能用「无需身份验证」绕过。页面功能不代表都已开放为 MCP 工具。",
      },
    ],
    related: ["permissions", "project-qa"],
  },
  {
    id: "browse",
    group: "查找与使用知识",
    title: "按目录查找资料",
    summary: "按公司、项目或个人范围逐层浏览，适合查找某一类资料。",
    audience: "业务用户",
    entry: "知识库 → 公司库 / 项目库 / 个人库",
    to: "/knowledge",
    capability: "viewKnowledge",
    sections: [
      {
        id: "scope",
        title: "选择资料范围",
        steps: [
          "进入知识库，选择公司库、项目库或个人库。",
          "选择项目库时，再用“当前项目”选择器选定项目。",
        ],
      },
      {
        id: "folder",
        title: "打开目录与资料",
        steps: [
          "展开目录，点击需要浏览的目录名称。",
          "在当前目录中搜索标题或标签，点击资料标题查看详情。",
          "返回上层时，点击目录路径中的库名、项目名或上级目录名。",
        ],
        after: "当前目录搜索用于定位标题和标签；查正文请切换全库搜索。",
      },
    ],
    related: ["knowledge", "detail", "naming"],
  },
  {
    id: "upload-project",
    group: "上传与整理资料",
    title: "上传资料到项目库",
    summary: "直接把本地工作资料提交到指定项目，供项目成员使用。",
    audience: "目标项目的有效成员",
    entry: "知识库 → 上传资产 → 本地上传",
    to: "/upload",
    capability: "viewUpload",
    sections: [
      {
        id: "file",
        title: "上传并打开确认页",
        paragraphs: [
          "添加文件后，在文件任务中等待处理完成，再打开待确认项。选择文件的方法见“上传资料到个人库”。",
        ],
      },
      {
        id: "project",
        title: "选择项目与正式目录",
        steps: [
          "将“目标知识库”选为项目库，再选择“目标项目”。",
          "选择正式目录，检查主题、形成日期、版本、保密等级和内容建议。规范名需要有效的项目代码。",
          "核对生成的名称和目标项目，点击“确认入库”。",
        ],
      },
      {
        id: "approval",
        title: "查看入库结果",
        paragraphs: [
          "普通顾问提交后显示“已提交，等待项目经理确认”。经理确认后才进入项目库；拒绝时可查看原因。",
          "项目经理提交自己负责项目的资料，可按当前入库流程直接确认。入库后还需要完成索引，才能用于正文检索和问答。",
        ],
      },
    ],
    related: ["upload-history", "review", "personal"],
    faq: [
      {
        question: "目标项目列表里没有我要选的项目怎么办？",
        answer:
          "请项目经理检查你是否为该项目的有效成员。仅能查看跨项目摘要，不代表可以向该项目上传资料。",
      },
    ],
  },
  {
    id: "edit",
    group: "上传与整理资料",
    title: "编辑资料信息",
    summary: "更正标题、目录、标签或摘要，不需要重新上传原文件。",
    audience: "资料所有者或有该资料管理权限的人",
    entry: "资料详情 → 编辑资料",
    to: "/knowledge",
    capability: "viewKnowledge",
    sections: [
      {
        id: "edit",
        title: "修改信息",
        steps: [
          "打开资料详情，点击“编辑资料”。",
          "修改需要更正的标题、正式目录、标签或摘要。调整保密等级前，核对内容是否适合新的访问范围。",
          "填写修改原因，例如“更正方案适用对象”，检查后保存。",
        ],
        after: "回到详情核对最新信息。原文件内容保持不变。",
      },
      {
        id: "content",
        title: "正文也需要修改时",
        paragraphs: ["使用“更新这份资料”上传新版，不要只改摘要来代替文件更新。"],
      },
    ],
    related: ["versions", "maintenance"],
    faq: [
      {
        question: "提示资料已被修改，怎么办？",
        answer: "重新加载最新资料，再核对你的修改。不要覆盖他人刚保存的内容或目录调整。",
      },
    ],
  },
  {
    id: "version-compare",
    group: "上传与整理资料",
    title: "比较资料版本",
    summary: "查看两个版本的摘要和元信息差异，辅助核验新版。",
    audience: "有相应资料查看权的业务用户",
    entry: "资料详情 → 版本记录",
    to: "/knowledge",
    capability: "viewKnowledge",
    sections: [
      {
        id: "compare",
        title: "选择两个版本比较",
        steps: [
          "打开资料详情的“版本记录”。",
          "选择要比较的两个关联版本。",
          "逐项核对摘要与元信息；需要检查原文时，分别打开有权预览的文件。",
        ],
        note: "这里比较的是摘要和元信息，不是原文件全文差异。",
      },
    ],
    related: ["versions", "version-replace"],
  },
  {
    id: "version-replace",
    group: "上传与整理资料",
    title: "用新版替代旧版",
    summary: "新版完成核验后，明确处理旧版，避免继续使用过时内容。",
    audience: "有该资料管理权限的人",
    entry: "资料详情 → 维护与发布",
    to: "/knowledge",
    capability: "viewKnowledge",
    sections: [
      {
        id: "ready",
        title: "确认新版已准备好",
        paragraphs: ["先完成新版的入库、审批与必要复核，核对新版适用于旧资料的使用场景。"],
      },
      {
        id: "replace",
        title: "确认替代并归档",
        steps: [
          "在资料的维护操作中选择关联新版或替代操作，核对新旧资料。",
          "确认替代关系并归档旧版。",
          "回到详情核对关系和状态。",
        ],
        after: "旧版退出默认检索与问答，历史文件继续保留。解除替代关系也不会自动恢复旧版。",
      },
    ],
    related: ["versions", "version-compare", "restore"],
  },
  {
    id: "restore",
    group: "业务治理",
    title: "恢复已归档资料",
    summary: "资料仍有使用价值时，核验后恢复到在库状态。",
    audience: "总经理 / 咨询总监",
    entry: "管理中心 → 公司库治理 → 归档中心",
    to: "/company-governance",
    capability: "viewCompanyKnowledge",
    sections: [
      {
        id: "check",
        title: "检查归档原因",
        steps: [
          "打开公司库治理的“归档中心”，找到资料。",
          "查看归档原因和替代关系，确认现在恢复的用途。",
        ],
      },
      {
        id: "restore",
        title: "预览并恢复",
        steps: ["选择资料，预览恢复清单。", "确认恢复后检查逐项结果，并在全部在库中核对。"],
        note: "已被新版替代的旧资料不能直接恢复。先核对并处理替代关系，避免新旧内容同时造成误用。",
      },
    ],
    related: ["directories", "version-replace"],
  },
  {
    id: "mobile",
    group: "开始使用",
    title: "在手机上使用平台",
    summary: "从企业微信或手机浏览器打开平台，查资料、提问和处理审批。",
    audience: "所有用户",
    entry: "手机浏览器 / 企业微信内打开平台",
    to: "/",
    capability: "viewHome",
    sections: [
      {
        id: "open",
        title: "登录与切换模块",
        steps: [
          "打开公司提供的平台地址，使用企业微信登录或账号登录。",
          "底部“工作、知识、项目、审批”用于切换常用模块；“我的”中查看账号和全部功能。",
        ],
      },
      {
        id: "read",
        title: "查资料与返回",
        steps: [
          "在知识库选择范围，浏览目录或搜索正文；点资料标题阅读详情。",
          "从项目进入问答，提交问题后点击引用核对资料。",
          "使用页面顶部返回按钮回到上一层。",
        ],
      },
      {
        id: "approve",
        title: "处理待办",
        paragraphs: [
          "从工作台、任务中心或审批模块打开记录，先查看资料与理由，再确认或拒绝。长表单可上下滚动，提交前检查必填信息。",
        ],
      },
    ],
    related: ["identity", "knowledge", "review"],
  },
  {
    id: "start-consultant",
    group: "开始使用",
    title: "普通顾问入门",
    summary: "找资料、上传知识、项目问答。按下面的顺序熟悉常用功能。",
    audience: "普通顾问",
    entry: "工作台",
    to: "/",
    capability: "viewHome",
    sections: [
      {
        id: "find",
        title: "先找到一份有用的资料",
        paragraphs: [
          "进入知识库，用正文关键词搜索，或按项目和目录浏览。打开资料后先读摘要；需要原文时，从详情申请访问。",
        ],
      },
      {
        id: "upload",
        title: "保存自己的工作资料",
        paragraphs: [
          "尚未共享的内容先上传到个人库。明确要交给项目的文件，可以直接上传到项目库，等待项目经理确认。",
        ],
      },
      {
        id: "project",
        title: "参与项目工作",
        paragraphs: [
          "进入自己参与的项目空间，查看项目资料或向项目知识提问。阅读答案时检查引用和版本；缺少计算基数等信息时，补齐条件再问。",
        ],
      },
    ],
    related: ["knowledge", "ingest", "project-qa", "original-access"],
  },
  {
    id: "start-manager",
    group: "开始使用",
    title: "项目经理入门",
    summary: "管理项目、审批入库、沉淀资产。按下面的顺序熟悉常用功能。",
    audience: "项目经理",
    entry: "工作台",
    to: "/",
    capability: "viewHome",
    sections: [
      {
        id: "setup",
        title: "检查项目与成员",
        paragraphs: [
          "进入负责的项目，核对项目配置和成员。在项目设置管理顾问、辅导老师；经理任命由总经理或咨询总监办理。",
        ],
      },
      {
        id: "review",
        title: "处理项目入库审批",
        paragraphs: [
          "从工作台或审批中心打开待办，检查资料内容、目录和密级后确认或拒绝。批准后的任务还需要完成入库与索引，继续查看处理结果。",
        ],
      },
      {
        id: "reuse",
        title: "沉淀可以复用的资产",
        paragraphs: [
          "项目资料经过真实内部分享或客户验证后，登记证据并确认资产化。适合跨项目使用的资产，再提交公司发布申请。",
        ],
      },
    ],
    related: ["project", "review", "assetization", "publication"],
  },
  {
    id: "start-boss",
    group: "开始使用",
    title: "总经理 / 咨询总监入门",
    summary: "建项目、任命人员、治理公司知识。按下面的顺序熟悉常用功能。",
    audience: "总经理 / 咨询总监",
    entry: "工作台",
    to: "/",
    capability: "viewHome",
    sections: [
      {
        id: "people",
        title: "建立项目与分工",
        paragraphs: [
          "创建项目时指定项目经理；通过人员权限管理公司身份和项目经理任职。普通项目成员交由对应经理维护。",
        ],
      },
      {
        id: "publish",
        title: "核验公司发布申请",
        paragraphs: [
          "在审核待办检查项目资产的适用范围和发布条件。总经理与咨询总监分别确认，满足双席条件后才能完成公司发布。",
        ],
      },
      {
        id: "govern",
        title: "维护公司知识",
        paragraphs: [
          "在公司库治理核验资料，归档不再适用的内容。需要更改正式分类时进入目录治理，先保存草稿，再核对差异后发布。",
        ],
      },
    ],
    related: ["project-create", "people", "publication", "directories"],
  },
  {
    id: "start-admin",
    group: "开始使用",
    title: "系统管理员入门",
    summary: "检查运行状态、排障与系统维护。按下面的顺序熟悉常用功能。",
    audience: "系统管理员",
    entry: "工作台",
    to: "/",
    capability: "viewHome",
    sections: [
      {
        id: "setup",
        title: "检查生成与检索服务",
        paragraphs: [
          "在模型配置核对生成服务、底座模型和具体知识库配置。配置完成后，通过实际任务检查是否可用。",
        ],
      },
      {
        id: "recover",
        title: "定位处理异常",
        paragraphs: [
          "资料无法检索时，从入库管理查看阶段和失败原因，区分索引恢复与重新解析。结合审计日志和告警查找异常线索。",
        ],
      },
      {
        id: "release",
        title: "发布面向用户的更新说明",
        paragraphs: [
          "版本完成部署验证后，在版本日志管理审核说明、预览并发布。系统管理身份不额外获得业务原文或审批权限。",
        ],
      },
    ],
    related: ["ingest-admin", "models", "audit", "release-admin"],
  },
  {
    id: "access-rules",
    group: "查找与使用知识",
    title: "了解摘要与原文权限",
    summary:
      "阅读摘要、查看原文和管理资料分别受权限控制。遇到“看得到但打不开”的情况，可以先对照这里。",
    audience: "业务用户",
    entry: "知识库",
    to: "/knowledge",
    capability: "viewKnowledge",
    sections: [
      {
        id: "scope",
        title: "个人、项目与公司范围",
        paragraphs: [
          "个人知识仅本人可见。项目有效成员可访问本项目资料；其他业务用户只能发现允许展示的安全摘要。跨项目高密级资料还受脱敏和发现范围限制。",
          "公司职务或系统管理员身份，不会自动授予其他项目原文权限。公司资料按保密等级和当前规则开放访问。",
        ],
      },
      {
        id: "request",
        title: "单份原文授权能做什么",
        paragraphs: [
          "原文申请通过后，在有效期内可访问对应资料。单份授权不会开放整个项目空间，也不会增加编辑、审批或成员管理权限。",
          "授权到期或撤销后，后续访问会重新校验。如果仍有其他合法访问依据，例如有效项目成员关系，单条授权撤销不一定阻止访问。",
        ],
      },
      {
        id: "manage",
        title: "谁能管理资料",
        paragraphs: [
          "个人资料由本人管理，项目资料由该项目的有效项目经理管理，公司资料由总经理或咨询总监管理。维护人安排不额外授予原文或资料管理权限。",
          "提高保密等级会影响原有访问授权。修改摘要不等于修改原文件，原文预览也是只读的。",
        ],
      },
    ],
    related: ["original-access", "access-review", "permissions"],
  },
  {
    id: "revoke-access",
    group: "审批与资产发布",
    title: "查看与撤销原文授权",
    summary: "不再需要某项原文访问时，找到对应授权并收回。",
    audience: "有该授权管理权限的人",
    entry: "审批中心 → 授权记录",
    to: "/original-access/grants",
    capability: "viewOriginalAccess",
    sections: [
      {
        id: "find",
        title: "找到授权记录",
        steps: [
          "进入审批中心，打开“授权记录”。",
          "核对资料、被授权人、有效期和状态，找到需要撤销的记录。",
        ],
      },
      {
        id: "revoke",
        title: "撤销授权",
        steps: ["使用撤销入口，填写理由。", "确认操作后检查该条授权是否已撤销。"],
        note: "撤销只影响这一条授权。对方如果仍有其他有效访问依据，可能仍能查看原文；已加载或已下载的内容无法收回。",
      },
    ],
    related: ["access-review", "original-access", "access-rules"],
  },
];
export const HELP_GROUPS = [...new Set(HELP_GUIDES.map((guide) => guide.group))];
export function searchHelp(query: string) {
  const terms = query.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  return HELP_GUIDES.filter((guide) => {
    const text = [
      guide.title,
      guide.summary,
      guide.entry,
      ...guide.sections.flatMap((section) => [
        section.title,
        ...(section.paragraphs ?? []),
        ...(section.steps ?? []),
        section.after ?? "",
        section.note ?? "",
      ]),
      ...(guide.faq ?? []).flatMap((item) => [item.question, item.answer]),
    ]
      .join(" ")
      .toLocaleLowerCase();
    return terms.every((term) => text.includes(term));
  });
}
