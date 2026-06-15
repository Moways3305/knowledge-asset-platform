// 企微微盘扫描页共享的中文标签 / 选项。纯展示常量。
export const scopeLabel: Record<string, string> = {
  company: "公司级",
  project: "项目级",
  personal: "个人级",
};

export const scopeOptions = [
  { value: "project", label: "项目知识库" },
  { value: "company", label: "公司知识库" },
  { value: "personal", label: "个人知识库" },
];

export const scanStatusLabel: Record<string, string> = {
  completed: "完成",
  failed: "失败",
  running: "进行中",
  partial: "部分成功",
};

export const scanStatusCls: Record<string, string> = {
  completed: "ws-result-success",
  failed: "ws-result-error",
  running: "ws-result-empty",
  partial: "ws-result-duplicate",
};
