export const UPLOAD_BATCH_SIZE = 200;
export const MACOS_METADATA_MESSAGE =
  "这是 macOS 元数据文件，不是原始资料；请选择不带 `._` 前缀的原文件";
export const UNREADABLE_FILE_MESSAGE = "文件内容当前不可读取；请先在本机完成下载后重新选择";

export function isMacosMetadataPath(value: string): boolean {
  const segments = value.replace(/\\/g, "/").split("/").filter(Boolean);
  const basename = segments[segments.length - 1] ?? value;
  return (
    basename.startsWith("._") ||
    basename.toLowerCase() === ".ds_store" ||
    segments.slice(0, -1).some((segment) => segment.toLowerCase() === "__macosx")
  );
}

export function safeRejectedDisplayName(value: string): string {
  const segments = value.replace(/\\/g, "/").split("/").filter(Boolean);
  const basename = safeSegment(segments[segments.length - 1] ?? value);
  return segments.slice(0, -1).some((segment) => segment.toLowerCase() === "__macosx")
    ? `__MACOSX/${basename}`
    : basename;
}

export interface DroppedFileCandidate {
  file: File;
  displayName: string;
  readError?: string;
}

export interface FolderDropResult {
  candidates: DroppedFileCandidate[];
  notice: string | null;
}

interface BrowserFileEntry {
  isFile: true;
  isDirectory: false;
  name: string;
  file: (success: (file: File) => void, failure?: () => void) => void;
}

interface BrowserDirectoryReader {
  readEntries: (success: (entries: BrowserFileSystemEntry[]) => void, failure?: () => void) => void;
}

interface BrowserDirectoryEntry {
  isFile: false;
  isDirectory: true;
  name: string;
  createReader: () => BrowserDirectoryReader;
}

type BrowserFileSystemEntry = BrowserFileEntry | BrowserDirectoryEntry;

type EntryAwareDataTransferItem = DataTransferItem & {
  webkitGetAsEntry?: () => BrowserFileSystemEntry | null;
};

function safeSegment(value: string): string {
  const withoutControls = Array.from(value)
    .filter((character) => {
      const codePoint = character.codePointAt(0) ?? 0;
      return codePoint > 31 && codePoint !== 127;
    })
    .join("");
  const normalized = withoutControls.replace(/[\\/]+/g, "_").trim();
  return normalized.replace(/^[A-Za-z]:/, "") || "未命名文件";
}

function fileFromEntry(entry: BrowserFileEntry): Promise<File | null> {
  return new Promise((resolve) => entry.file(resolve, () => resolve(null)));
}

function readDirectoryBatch(
  reader: BrowserDirectoryReader,
): Promise<BrowserFileSystemEntry[] | null> {
  return new Promise((resolve) => reader.readEntries(resolve, () => resolve(null)));
}

async function readDirectoryEntries(
  entry: BrowserDirectoryEntry,
): Promise<BrowserFileSystemEntry[] | null> {
  const reader = entry.createReader();
  const entries: BrowserFileSystemEntry[] = [];
  while (true) {
    const batch = await readDirectoryBatch(reader);
    if (batch === null) return null;
    if (batch.length === 0) return entries;
    entries.push(...batch);
  }
}

function unreadableCandidate(displayName: string): DroppedFileCandidate {
  const baseName = safeSegment(displayName.split("/").pop() || displayName);
  return {
    file: new File([], baseName),
    displayName,
    readError: UNREADABLE_FILE_MESSAGE,
  };
}

export async function readDroppedFiles(
  dataTransfer: DataTransfer,
  isCurrent: () => boolean,
): Promise<FolderDropResult> {
  const items = Array.from(dataTransfer.items ?? []) as EntryAwareDataTransferItem[];
  const supportsEntries =
    items.length > 0 && items.some((item) => typeof item.webkitGetAsEntry === "function");

  if (!supportsEntries) {
    const files = Array.from(dataTransfer.files ?? []);
    return {
      candidates: files.map((file) => ({
        file,
        displayName: safeSegment(file.name),
      })),
      notice:
        "当前浏览器不支持读取文件夹，已仅添加可直接读取的文件；请使用最新版 Chrome 或 Edge 拖入文件夹。",
    };
  }

  const candidates: DroppedFileCandidate[] = [];

  const append = (candidate: DroppedFileCandidate) => {
    candidates.push(candidate);
  };

  const visit = async (entry: BrowserFileSystemEntry, parent: string): Promise<void> => {
    if (!isCurrent()) return;
    const name = safeSegment(entry.name);
    const displayName = parent ? `${parent}/${name}` : name;
    if (entry.isFile) {
      const file = await fileFromEntry(entry);
      if (!isCurrent()) return;
      append(file ? { file, displayName } : unreadableCandidate(displayName));
      return;
    }

    const children = await readDirectoryEntries(entry);
    if (!isCurrent()) return;
    if (children === null) {
      append(unreadableCandidate(displayName));
      return;
    }
    for (const child of children) {
      await visit(child, displayName);
      if (!isCurrent()) return;
    }
  };

  for (const item of items) {
    if (!isCurrent()) break;
    const entry = item.webkitGetAsEntry?.() as BrowserFileSystemEntry | null | undefined;
    if (entry) {
      await visit(entry, "");
    } else {
      const file = item.getAsFile();
      if (file) append({ file, displayName: safeSegment(file.name) });
    }
  }

  return {
    candidates,
    notice: null,
  };
}
