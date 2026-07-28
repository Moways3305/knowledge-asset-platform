export const FOLDER_DROP_FILE_LIMIT = 200;

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
    readError: "无法读取该文件，请检查本机权限后重试",
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
    const limitNotice =
      files.length > FOLDER_DROP_FILE_LIMIT
        ? `一次最多添加 ${FOLDER_DROP_FILE_LIMIT} 个文件条目，其余未加入队列，请分批继续上传。`
        : "";
    return {
      candidates: files.slice(0, FOLDER_DROP_FILE_LIMIT).map((file) => ({
        file,
        displayName: safeSegment(file.name),
      })),
      notice: [
        "当前浏览器不支持读取文件夹，已仅添加可直接读取的文件；请使用最新版 Chrome 或 Edge 拖入文件夹。",
        limitNotice,
      ]
        .filter(Boolean)
        .join(" "),
    };
  }

  const candidates: DroppedFileCandidate[] = [];
  let limitReached = false;

  const append = (candidate: DroppedFileCandidate) => {
    if (candidates.length >= FOLDER_DROP_FILE_LIMIT) {
      limitReached = true;
      return;
    }
    candidates.push(candidate);
  };

  const visit = async (entry: BrowserFileSystemEntry, parent: string): Promise<void> => {
    if (!isCurrent() || limitReached) return;
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
      if (!isCurrent() || limitReached) return;
    }
  };

  for (const item of items) {
    if (!isCurrent() || limitReached) break;
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
    notice: limitReached
      ? `一次最多添加 ${FOLDER_DROP_FILE_LIMIT} 个文件条目，其余未加入队列，请拆分文件夹后继续上传。`
      : null,
  };
}
