import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useSearchParams } from "react-router-dom";
import {
  ArrowLeft,
  ArrowUpRight,
  BookOpen,
  ChevronDown,
  ChevronRight,
  FileUp,
  FolderOpen,
  Search,
  ShieldCheck,
  Users,
  Wrench,
  Layers,
  CircleHelp,
  X,
} from "lucide-react";
import { ProductPage } from "../components/ProductLayout";
import { useAuth } from "../auth/AuthContext";
import { can } from "../auth/permissions";
import { HELP_GUIDES, HELP_GROUPS, searchHelp } from "../content/helpGuides";
import "./HelpPage.css";

const byId = new Map(HELP_GUIDES.map((guide) => [guide.id, guide]));
const groupIcons = [BookOpen, Search, FileUp, Users, ShieldCheck, FolderOpen, Wrench, Layers];
const starts = ["quick-start", "ingest", "knowledge"];
const roleLinks = ["start-consultant", "start-manager", "start-boss", "start-admin"];
const commonQuestions = [
  { title: "文件传完了，为什么还没有入库？", id: "upload-history" },
  { title: "能看到摘要，为什么打不开原文？", id: "original-access" },
  { title: "找不到项目或审批入口怎么办？", id: "identity" },
  { title: "公司发布为什么还在等待确认？", id: "publication" },
  { title: "消息已读，为什么任务还在？", id: "notifications" },
  { title: "项目问答没有答案，怎么办？", id: "project-qa" },
];
export default function HelpPage() {
  const { capabilities } = useAuth();
  const [params, setParams] = useSearchParams();
  const location = useLocation();
  const [directoryOpen, setDirectoryOpen] = useState(false);
  const heading = useRef<HTMLHeadingElement>(null);
  const requestedId =
    params.get("article") ?? (location.hash.startsWith("#help-") ? "" : location.hash.slice(1));
  const current = byId.get(requestedId === "admin" ? "ingest-admin" : requestedId);
  const groupParam = params.get("category");
  const group = HELP_GROUPS.includes(groupParam ?? "") ? groupParam : null;
  const query = params.get("q") ?? "";
  const searching = !current && Boolean(query.trim());
  const home = !current && !group && !searching;
  const articles = group ? HELP_GUIDES.filter((guide) => guide.group === group) : searchHelp(query);
  const articleHref = (id: string) => `/help?article=${id}`;
  const categoryHref = (name: string) => `/help?category=${encodeURIComponent(name)}`;

  useEffect(() => {
    setDirectoryOpen(false);
    if (searching || location.hash.startsWith("#help-")) return;
    heading.current?.focus({ preventScroll: true });
    heading.current?.closest(".app-content")?.scrollTo?.({ top: 0 });
  }, [current, group, searching, location.hash]);

  const searchBox = (
    <div className="help-hub-search" role="search" aria-label="搜索使用帮助">
      <Search size={20} aria-hidden="true" />
      <input
        type="search"
        aria-label="搜索帮助"
        value={query}
        placeholder="搜索你的问题，例如：上传资料、申请原文"
        onChange={(event) =>
          setParams(event.target.value ? { q: event.target.value } : {}, { replace: true })
        }
      />
      {query && (
        <button type="button" aria-label="清空搜索" onClick={() => setParams({})}>
          <X size={18} />
        </button>
      )}
    </div>
  );
  return (
    <ProductPage className={`help-hub ${current ? "is-reading" : ""}`}>
      {!current ? (
        <>
          <header className="help-hub-header">
            {!home && (
              <Link to="/help" className="help-back">
                <ArrowLeft size={16} />
                帮助首页
              </Link>
            )}
            <h2 ref={heading} tabIndex={-1}>
              {searching ? "搜索帮助" : (group ?? "帮助中心")}
            </h2>
            <p>
              {home
                ? "了解平台，找到教程，把手头的工作顺利完成。"
                : group
                  ? "选择你要完成的操作，查看详细步骤。"
                  : `“${query}”的相关教程`}
            </p>
            {searchBox}
          </header>
          {home ? (
            <>
              <section className="help-start" aria-labelledby="help-start-title">
                <h3 id="help-start-title">新手入门</h3>
                <div className="help-start-grid">
                  {starts.map((id, index) => {
                    const guide = byId.get(id)!;
                    const Icon = [BookOpen, FileUp, Search][index];
                    return (
                      <Link key={id} to={articleHref(id)} className="help-start-link">
                        <span className="help-topic-icon">
                          <Icon size={25} />
                        </span>
                        <div>
                          <h4>{guide.title}</h4>
                          <p>
                            {
                              [
                                "了解三类知识库和常用入口。",
                                "从选择文件到确认入库。",
                                "用关键词找到需要的内容。",
                              ][index]
                            }
                          </p>
                        </div>
                        <ChevronRight size={17} />
                      </Link>
                    );
                  })}
                </div>
                <nav className="help-role-links" aria-label="按身份入门">
                  <span>按工作角色了解：</span>
                  {roleLinks.map((id) => (
                    <Link key={id} to={articleHref(id)}>
                      {byId.get(id)!.title}
                    </Link>
                  ))}
                </nav>
              </section>
              <section className="help-topics" aria-labelledby="help-topics-title">
                <h3 id="help-topics-title">功能教程</h3>
                <div className="help-topic-grid">
                  {HELP_GROUPS.filter((name) => name !== "开始使用").map((name) => {
                    const Icon = groupIcons[HELP_GROUPS.indexOf(name)] ?? BookOpen;
                    const items = HELP_GUIDES.filter((guide) => guide.group === name);
                    return (
                      <section className="help-topic" key={name}>
                        <h4>
                          <Icon size={20} />
                          <Link to={categoryHref(name)}>{name}</Link>
                        </h4>
                        <ul>
                          {items.slice(0, 3).map((guide) => (
                            <li key={guide.id}>
                              <Link to={articleHref(guide.id)}>{guide.title}</Link>
                            </li>
                          ))}
                        </ul>
                        <Link className="help-topic-more" to={categoryHref(name)}>
                          查看全部教程 <ChevronRight size={14} />
                        </Link>
                      </section>
                    );
                  })}
                </div>
              </section>
              <section className="help-common" aria-labelledby="help-common-title">
                <h3 id="help-common-title">常见问题</h3>
                <div>
                  {commonQuestions.map((item) => (
                    <Link key={item.id} to={articleHref(item.id)}>
                      <CircleHelp size={17} />
                      <span>{item.title}</span>
                      <ChevronRight size={15} />
                    </Link>
                  ))}
                </div>
              </section>
              <footer className="help-contact">
                仍需要帮助？请联系项目经理或平台管理员，说明操作入口、对象名称和页面提示。
              </footer>
            </>
          ) : (
            <section className="help-list" aria-label={searching ? "帮助搜索结果" : "分类教程"}>
              <p className="help-list-count">{articles.length} 篇教程</p>
              {articles.length ? (
                articles.map((guide) => (
                  <Link className="help-result" key={guide.id} to={articleHref(guide.id)}>
                    <span>{guide.group}</span>
                    <h3>{guide.title}</h3>
                    <p>{guide.summary}</p>
                    <ChevronRight size={18} />
                  </Link>
                ))
              ) : (
                <div className="help-empty">
                  <h3>没有找到相关教程</h3>
                  <p>换一个简短的关键词试试，例如“上传”“审批”或“原文”。</p>
                  <Link to="/help">返回帮助首页</Link>
                </div>
              )}
            </section>
          )}
        </>
      ) : (
        <>
          <nav className="help-breadcrumb" aria-label="帮助路径">
            <Link to="/help">帮助首页</Link>
            <ChevronRight size={14} />
            <Link to={categoryHref(current.group)}>{current.group}</Link>
            <ChevronRight size={14} />
            <span>{current.title}</span>
          </nav>
          <div className="help-reading-layout">
            <aside className="help-reading-directory" aria-label="帮助目录">
              <button
                type="button"
                className="help-directory-toggle"
                aria-expanded={directoryOpen}
                onClick={() => setDirectoryOpen(!directoryOpen)}
              >
                本类教程 <ChevronDown size={16} />
              </button>
              <nav className={directoryOpen ? "is-open" : ""} aria-label="本类教程">
                <h3>{current.group}</h3>
                {HELP_GUIDES.filter((guide) => guide.group === current.group).map((guide) => (
                  <Link
                    to={articleHref(guide.id)}
                    key={guide.id}
                    aria-current={guide.id === current.id ? "page" : undefined}
                  >
                    {guide.title}
                  </Link>
                ))}
                <Link className="help-all-topics" to="/help">
                  查看全部分类
                </Link>
              </nav>
            </aside>
            <article className="help-article" aria-labelledby="help-article-title">
              <header>
                <h2 id="help-article-title" ref={heading} tabIndex={-1}>
                  {current.title}
                </h2>
                <p className="help-article-lead">{current.summary}</p>
                {current.audience !== "所有用户" && (
                  <p className="help-audience">适用：{current.audience}</p>
                )}
              </header>
              <div className="help-entry">
                <span>{current.entry}</span>
                {can[current.capability](capabilities) && (
                  <Link to={current.to}>
                    打开功能 <ArrowUpRight size={14} />
                  </Link>
                )}
              </div>
              <nav className="help-inline-toc" aria-label="本文目录">
                <strong>本文内容</strong>
                {current.sections.map((section) => (
                  <a key={section.id} href={`#help-${section.id}`}>
                    {section.title}
                  </a>
                ))}
                {current.faq?.length ? <a href="#help-faq">常见问题</a> : null}
              </nav>
              {current.sections.map((section) => (
                <section
                  className="help-article-section"
                  key={section.id}
                  id={`help-${section.id}`}
                >
                  <h3>{section.title}</h3>
                  {section.paragraphs?.map((text) => (
                    <p key={text}>{text}</p>
                  ))}
                  {section.steps && (
                    <ol>
                      {section.steps.map((step) => (
                        <li key={step}>{step}</li>
                      ))}
                    </ol>
                  )}
                  {section.image && (
                    <figure>
                      <a
                        href={section.image.src}
                        target="_blank"
                        rel="noreferrer"
                        aria-label="放大操作截图"
                      >
                        <img src={section.image.src} alt={section.image.alt} loading="lazy" />
                      </a>
                      <figcaption>{section.image.caption}</figcaption>
                    </figure>
                  )}
                  {section.after && <p>{section.after}</p>}
                  {section.note && <p className="help-note">{section.note}</p>}
                </section>
              ))}
              {current.faq?.length ? (
                <section className="help-article-faq" id="help-faq">
                  <h3>常见问题</h3>
                  {current.faq.map((item) => (
                    <div key={item.question}>
                      <h4>{item.question}</h4>
                      <p>{item.answer}</p>
                    </div>
                  ))}
                </section>
              ) : null}
              {current.related.length > 0 && (
                <nav className="help-related" aria-label="相关教程">
                  <h3>{current.id.startsWith("start-") ? "按顺序开始学习" : "相关教程"}</h3>
                  {current.related.map((id) => (
                    <Link to={articleHref(id)} key={id}>
                      {byId.get(id)?.title}
                      <ChevronRight size={15} />
                    </Link>
                  ))}
                </nav>
              )}
              <footer className="help-article-footer">
                <Link to="/help">
                  <ArrowLeft size={15} />
                  返回帮助首页
                </Link>
              </footer>
            </article>
            <nav className="help-toc" aria-label="页内导航">
              <h3>本文内容</h3>
              {current.sections.map((section) => (
                <a key={section.id} href={`#help-${section.id}`}>
                  {section.title}
                </a>
              ))}
              {current.faq?.length ? <a href="#help-faq">常见问题</a> : null}
            </nav>
          </div>
        </>
      )}
    </ProductPage>
  );
}
