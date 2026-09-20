import type { ReleaseDraft, ReleaseNote } from "../api/releaseNotes";

export const releaseKinds = { new: "新增", improved: "优化", fixed: "修复" } as const;
export function releaseDate(value: string) {
  return new Date(value).toLocaleDateString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
}
export default function ReleaseNoteCard({
  note,
  latest = false,
}: {
  note: ReleaseDraft | ReleaseNote;
  latest?: boolean;
}) {
  const published = "published_at" in note && note.published_at;
  return (
    <article className={`release-card${latest ? " is-latest" : ""}`}>
      <header className="release-card-meta">
        <strong className="release-version">{note.version || "版本号"}</strong>
        {latest && <span className="release-badge">最新发布</span>}
        {"is_unread" in note && note.is_unread && <span className="release-new-label">未读</span>}
        {published && <time dateTime={published}>{releaseDate(published)}</time>}
      </header>
      <h3>{note.title || "更新标题"}</h3>
      <ul className="release-entries">
        {note.entries.map((entry, index) => (
          <li key={index}>
            <span className={`release-kind is-${entry.kind}`}>{releaseKinds[entry.kind]}</span>
            <p>{entry.text}</p>
          </li>
        ))}
      </ul>
      {!note.entries.length && <p className="release-muted">尚未添加更新内容。</p>}
    </article>
  );
}
