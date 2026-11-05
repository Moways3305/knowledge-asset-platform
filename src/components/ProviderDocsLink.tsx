import { ArrowUpRight } from "lucide-react";

// Official public documentation, checked 2026-11-05. Never derive links from saved endpoints.
const providerDocs: Record<string, { name: string; url: string }> = {
  aliyun: { name: "阿里云百炼", url: "https://help.aliyun.com/zh/model-studio/models" },
  deepseek: { name: "DeepSeek", url: "https://api-docs.deepseek.com/zh-cn/" },
  siliconflow: { name: "硅基流动", url: "https://docs.siliconflow.cn/docs/userguide/quickstart" },
  openai: { name: "OpenAI", url: "https://developers.openai.com/api/docs/models" },
  moonshot: { name: "Moonshot / Kimi", url: "https://platform.kimi.com/docs/api/overview" },
  zhipu: { name: "智谱", url: "https://docs.bigmodel.cn/cn/guide/start/quick-start" },
  volcengine: {
    name: "火山方舟",
    url: "https://docs.volcengine.com/docs/ark/compatible-with-openai-sdk?lang=zh",
  },
};

export default function ProviderDocsLink({ provider }: { provider?: string }) {
  const docs = provider ? providerDocs[provider] : undefined;
  if (!docs) return null;
  return (
    <a
      className="onboarding-docs-link"
      href={docs.url}
      target="_blank"
      rel="noopener noreferrer"
      aria-label={`查看 ${docs.name} 官方文档（新标签页打开）`}
      title={`${docs.name} 官方文档 · 新标签页打开`}
    >
      查看文档 <ArrowUpRight size={15} aria-hidden="true" />
    </a>
  );
}
