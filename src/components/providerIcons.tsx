// 模型供应商图标映射：优先使用收集的官方 SVG；未收集到图标的供应商
// 回退为"品牌色字母徽标"，保证下拉里任何选项都有视觉标识。
// 安全边界：本文件只放公开品牌标识，绝不放密钥 / 内部地址。
import aliyun from "../assets/providers/aliyun.svg";
import anthropic from "../assets/providers/anthropic.svg";
import deepseek from "../assets/providers/deepseek.svg";
import gemini from "../assets/providers/gemini.svg";
import hunyuan from "../assets/providers/hunyuan.svg";
import lkeap from "../assets/providers/lkeap.svg";
import minimax from "../assets/providers/minimax.svg";
import modelscope from "../assets/providers/modelscope.svg";
import moonshot from "../assets/providers/moonshot.svg";
import openai from "../assets/providers/openai.svg";
import qianfan from "../assets/providers/qianfan.svg";
import siliconflow from "../assets/providers/siliconflow.svg";
import volcengine from "../assets/providers/volcengine.svg";
import zhipu from "../assets/providers/zhipu.svg";

const KNOWN_PROVIDER_LOGOS: Record<string, string> = {
  aliyun,
  anthropic,
  deepseek,
  gemini,
  hunyuan,
  lkeap,
  minimax,
  modelscope,
  moonshot,
  openai,
  qianfan,
  siliconflow,
  volcengine,
  zhipu,
};

// 未收集图标的供应商：品牌色字母徽标兜底。
const FALLBACK_PROVIDER_COLORS: Record<string, string> = {
  generic: "#6b7280",
  weknoracloud: "#2f9e44",
  openrouter: "#7c3aed",
  requesty: "#0ea5e9",
  jina: "#16a34a",
  mimo: "#ea580c",
  longcat: "#d97706",
  gpustack: "#64748b",
  nvidia: "#76b900",
  novita: "#6d28d9",
  azure_openai: "#0078d4",
};
const DEFAULT_FALLBACK_COLOR = "#5b6472";

export function providerLogoUrl(provider: string): string | undefined {
  return KNOWN_PROVIDER_LOGOS[provider];
}

export function ProviderLogo({
  provider,
  label,
  size = 18,
}: {
  provider: string;
  label?: string;
  size?: number;
}) {
  const url = KNOWN_PROVIDER_LOGOS[provider];
  const monogram = (label || provider).trim().slice(0, 1).toUpperCase();
  if (url) {
    return (
      <span className="provider-logo" style={{ width: size, height: size }} aria-hidden="true">
        <img src={url} alt="" />
      </span>
    );
  }
  return (
    <span
      className="provider-logo provider-logo-monogram"
      style={{
        width: size,
        height: size,
        background: FALLBACK_PROVIDER_COLORS[provider] ?? DEFAULT_FALLBACK_COLOR,
      }}
      aria-hidden="true"
    >
      {monogram}
    </span>
  );
}
