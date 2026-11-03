/** Reads the authenticated file URL returned by the controlled preview endpoint. */
export async function fetchPreviewText(fileUrl: string): Promise<string> {
  const response = await fetch(fileUrl, { credentials: "include" });
  if (!response.ok) throw new Error("原文读取失败");
  return response.text();
}
