// 统一时间展示工具（PBC-10C）。后端始终存 UTC；前端所有用户可见时间固定按
// 北京时间（Asia/Shanghai）展示，不依赖浏览器本地时区，输出稳定的 YYYY-MM-DD HH:mm:ss。

const _dateTimeFmt = new Intl.DateTimeFormat("zh-CN", {
  timeZone: "Asia/Shanghai",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  // h23：固定 00-23，避免某些引擎在午夜返回 "24:00:00"。
  hourCycle: "h23",
});

const _dateFmt = new Intl.DateTimeFormat("zh-CN", {
  timeZone: "Asia/Shanghai",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

function _parts(value: string | null | undefined): Record<string, string> | null {
  if (!value) return null;
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return null;
  // formatToParts 跨 locale 稳定地拿到各字段，避免 "2026/6/3 上午..." 这类不稳定形态。
  const out: Record<string, string> = {};
  for (const p of _dateTimeFmt.formatToParts(d)) {
    if (p.type !== "literal") out[p.type] = p.value;
  }
  return out;
}

// 北京时间日期时间：YYYY-MM-DD HH:mm:ss。空 / 非法返回 "—"。
export function formatBeijingTime(value?: string | null): string {
  const p = _parts(value);
  if (!p) return "—";
  return `${p.year}-${p.month}-${p.day} ${p.hour}:${p.minute}:${p.second}`;
}

// 北京时间日期（仅 YYYY-MM-DD）：用于只展示日期的场景。空 / 非法返回 "—"。
export function formatBeijingDate(value?: string | null): string {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "—";
  const out: Record<string, string> = {};
  for (const p of _dateFmt.formatToParts(d)) {
    if (p.type !== "literal") out[p.type] = p.value;
  }
  return `${out.year}-${out.month}-${out.day}`;
}
