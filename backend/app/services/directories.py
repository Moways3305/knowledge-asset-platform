"""Governed directory templates, validation, display paths, and legacy mapping."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import Project
from app.models.knowledge import KnowledgeAssetVersion
from app.models.naming import NamingRuleRevision
from app.schemas.enums import KnowledgeScope
from app.schemas.permission import CallerContext
from app.services.discoverable_projects import list_knowledge_library_projects

UNCLASSIFIED_PROJECT_DIRECTORY_KEY = "project.unclassified"


@dataclass(frozen=True, slots=True)
class StandardDirectory:
    key: str
    scope: str
    name: str
    description: str
    sort_order: int


STANDARD_DIRECTORIES = (
    StandardDirectory("company.introduction", "company", "00 公司介绍", "简介 / 产品 / 宣传", 0),
    StandardDirectory(
        "company.thoughts_knowledge", "company", "01 思想与知识", "阅读 / 写作 / 培训", 10
    ),
    StandardDirectory(
        "company.methodology", "company", "02 方法论", "二级分类与职能维度使用标签", 20
    ),
    StandardDirectory(
        "company.industry_research", "company", "03 行业研究", "简析 / 政策 / 宏观 / 数据", 30
    ),
    StandardDirectory("company.client_cases", "company", "04 客户案例", "脱敏案例", 40),
    StandardDirectory(
        "company.key_materials", "company", "05 关键资料", "合同 / 经营 / 加密索引", 50
    ),
    StandardDirectory(
        "company.investment_capital", "company", "06 投融资与资本", "投 / 融 / IPO 使用标签", 60
    ),
    StandardDirectory(
        "company.ai_materials", "company", "07 AI资料", "前沿 / 工具 / 案例使用标签", 70
    ),
    StandardDirectory(
        "project.basic_information", "project", "01 项目基础信息", "合同 / NDA / 立项", 10
    ),
    StandardDirectory(
        "project.guidance_process", "project", "02 辅导过程", "周报 / 月报 / 议题", 20
    ),
    StandardDirectory("project.deliverables", "project", "03 交付成果", "诊断 / 战略 / 方案", 30),
    StandardDirectory("project.key_materials", "project", "04 关键资料", "数据 / 人事 / 纪要", 40),
    StandardDirectory("project.retrospective", "project", "05 项目复盘", "复盘 / 经验", 50),
    StandardDirectory(
        "personal.learning_notes", "personal", "01 个人学习笔记", "按主题以标签辅助分类", 10
    ),
    StandardDirectory(
        "personal.project_materials",
        "personal",
        "02 个人项目资料",
        "项目名称/年份等以字段或标签辅助",
        20,
    ),
    StandardDirectory(
        "personal.methodology_favorites",
        "personal",
        "03 个人方法论收藏",
        "按类型以标签辅助分类",
        30,
    ),
    StandardDirectory(
        "personal.pending", "personal", "04 待处理", "待处理 / 待脱敏的个人暂存位置", 40
    ),
)
STANDARD_BY_KEY = {item.key: item for item in STANDARD_DIRECTORIES}


def default_directory_config() -> list[dict]:
    return [
        {
            "directory_key": item.key,
            "scope": item.scope,
            "display_name": item.name,
            "description": item.description,
            "naming_code": item.name.removeprefix(f"{item.name[:2]} ")
            if item.name[:2].isdigit()
            else item.name,
            "default_confidentiality": "L2",
            "sort_order": item.sort_order,
            "enabled": True,
        }
        for item in STANDARD_DIRECTORIES
    ]


def legacy_directory_key(metadata: dict | None) -> str | None:
    """Explicit, reviewable mapping for historical naming metadata."""
    if not isinstance(metadata, dict):
        return None
    primary = str(metadata.get("category_primary") or "").strip()
    secondary = str(metadata.get("category_secondary") or "").strip()
    scope = str(metadata.get("scope") or "").strip()
    text = f"{primary} {secondary}".lower()
    mappings: tuple[tuple[tuple[str, ...], str], ...]
    if scope == "project":
        mappings = (
            (("基础", "合同", "nda", "立项"), "project.basic_information"),
            (("辅导", "周报", "月报", "议题"), "project.guidance_process"),
            (("交付", "诊断", "战略", "方案"), "project.deliverables"),
            (("关键", "数据", "人事", "纪要"), "project.key_materials"),
            (("复盘", "经验"), "project.retrospective"),
        )
    elif scope == "company":
        mappings = (
            (("公司介绍", "简介", "宣传", "产品"), "company.introduction"),
            (("思想", "知识", "阅读", "写作", "培训"), "company.thoughts_knowledge"),
            (("方法论", "模型工具", "模板"), "company.methodology"),
            (("行业", "政策", "宏观", "研究洞察"), "company.industry_research"),
            (("客户案例", "案例研究", "脱敏案例"), "company.client_cases"),
            (("关键资料", "合同", "经营"), "company.key_materials"),
            (("投融资", "资本", "ipo"), "company.investment_capital"),
            (("ai资料", "ai前沿", "ai工具"), "company.ai_materials"),
        )
    else:
        return None
    matches = {key for words, key in mappings if any(word.lower() in text for word in words)}
    return next(iter(matches)) if len(matches) == 1 else None


def version_directory_key(version: KnowledgeAssetVersion | None) -> str | None:
    """Return formal membership only; legacy mapping is never retrieval authority."""
    if version is None:
        return None
    return version.directory_key


async def published_directories(session: AsyncSession) -> tuple[int | None, list[dict]]:
    revision = (
        await session.execute(
            select(NamingRuleRevision)
            .where(NamingRuleRevision.status == "published")
            .order_by(NamingRuleRevision.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    raw = (
        revision.config.get("directories")
        if revision and isinstance(revision.config, dict)
        else None
    )
    directories = raw if isinstance(raw, list) and raw else default_directory_config()
    return (revision.version if revision else None), directories


async def validate_directory(
    session: AsyncSession,
    *,
    directory_key: str,
    scope: str,
    project_id: uuid.UUID | None,
) -> tuple[int | None, dict]:
    version, rows = await published_directories(session)
    if directory_key == UNCLASSIFIED_PROJECT_DIRECTORY_KEY:
        if scope != KnowledgeScope.project.value or project_id is None:
            raise HTTPException(
                status_code=422,
                detail={
                    "denied_reason": "directory_scope_mismatch",
                    "message": "未分类目录仅适用于指定项目",
                },
            )
        return version, {
            "directory_key": UNCLASSIFIED_PROJECT_DIRECTORY_KEY,
            "scope": KnowledgeScope.project.value,
            "display_name": "未分类 / 待治理",
            "description": "尚未映射正式目录的可见资料",
            "enabled": True,
        }
    item = next((row for row in rows if row.get("directory_key") == directory_key), None)
    if item is None or not item.get("enabled", True):
        raise HTTPException(
            status_code=422,
            detail={"denied_reason": "directory_unavailable", "message": "目录不存在或已停用"},
        )
    if item.get("scope") != scope:
        raise HTTPException(
            status_code=422,
            detail={
                "denied_reason": "directory_scope_mismatch",
                "message": "目录不适用于目标知识范围",
            },
        )
    if scope == KnowledgeScope.project.value and project_id is None:
        raise HTTPException(
            status_code=422,
            detail={
                "denied_reason": "directory_project_required",
                "message": "项目目录必须指定目标项目",
            },
        )
    if scope != KnowledgeScope.project.value and project_id is not None:
        raise HTTPException(
            status_code=422,
            detail={
                "denied_reason": "directory_project_mismatch",
                "message": "非项目目录不能绑定项目",
            },
        )
    return version, item


async def display_path(
    session: AsyncSession, directory_key: str | None, project_id: uuid.UUID | None
) -> str | None:
    if not directory_key:
        return "未分类 / 待治理"
    _, rows = await published_directories(session)
    item = next((row for row in rows if row.get("directory_key") == directory_key), None)
    if item is None:
        standard = STANDARD_BY_KEY.get(directory_key)
        if standard is None:
            return "未分类 / 待治理"
        name, scope = standard.name, standard.scope
    else:
        name, scope = str(item.get("display_name") or "未命名目录"), str(item.get("scope"))
    if scope == "project":
        project = await session.get(Project, project_id) if project_id else None
        return f"项目库 / {project.name if project else '项目'} / {name}"
    return f"{'公司库' if scope == 'company' else '个人库'} / {name}"


async def visible_directory_rows(
    session: AsyncSession,
    caller: CallerContext,
    *,
    allowed_scope: str | None = None,
    allowed_project_id: uuid.UUID | None = None,
) -> list[dict]:
    _, rows = await published_directories(session)
    # Directory navigation is structure inside an already-visible project, not
    # evidence that a project or asset exists. Content endpoints still apply
    # discovery and channel ceilings to every returned asset.
    projects = await list_knowledge_library_projects(
        session,
        caller,
        allowed_scope=allowed_scope,
        allowed_project_id=allowed_project_id,
    )
    out: list[dict] = []
    for row in rows:
        if not row.get("enabled", True):
            continue
        scope = row.get("scope")
        if allowed_scope not in (None, "all") and scope != allowed_scope:
            continue
        base = {
            "directory_key": row.get("directory_key"),
            "name": row.get("display_name"),
            "description": row.get("description"),
            "scope": scope,
            "parent_key": None,
        }
        if scope == "project":
            for project in projects:
                out.append(
                    {
                        **base,
                        "project_id": project.project_id,
                        "project_name": project.name,
                        "display_path": f"项目库 / {project.name} / {row.get('display_name')}",
                    }
                )
        elif scope == "personal":
            if caller.is_business_user:
                out.append(
                    {
                        **base,
                        "project_id": None,
                        "project_name": None,
                        "display_path": f"个人库 / {row.get('display_name')}",
                    }
                )
        else:
            out.append(
                {
                    **base,
                    "project_id": None,
                    "project_name": None,
                    "display_path": f"公司库 / {row.get('display_name')}",
                }
            )
    if allowed_scope in (None, "all", KnowledgeScope.project.value):
        for project in projects:
            out.append(
                {
                    "directory_key": UNCLASSIFIED_PROJECT_DIRECTORY_KEY,
                    "name": "未分类 / 待治理",
                    "description": "尚未映射正式目录的可见资料",
                    "scope": KnowledgeScope.project.value,
                    "parent_key": None,
                    "project_id": project.project_id,
                    "project_name": project.name,
                    "display_path": f"项目库 / {project.name} / 未分类 / 待治理",
                }
            )
    return out


async def directory_document_ids(
    session: AsyncSession,
    *,
    directory_key: str,
    scope: str | None,
    project_id: uuid.UUID | None,
) -> list[str]:
    """Resolve formal directory membership before semantic recall."""
    directory_condition = (
        KnowledgeAssetVersion.directory_key.is_(None)
        if directory_key == UNCLASSIFIED_PROJECT_DIRECTORY_KEY
        else KnowledgeAssetVersion.directory_key == directory_key
    )
    stmt = select(KnowledgeAssetVersion.weknora_doc_id).where(
        KnowledgeAssetVersion.version_status == "active",
        KnowledgeAssetVersion.index_status == "indexed",
        directory_condition,
        KnowledgeAssetVersion.weknora_doc_id.is_not(None),
    )
    from app.models.knowledge import KnowledgeAsset

    stmt = stmt.join(KnowledgeAsset, KnowledgeAsset.id == KnowledgeAssetVersion.asset_id).where(
        KnowledgeAsset.asset_status == "active",
        KnowledgeAsset.current_version_id == KnowledgeAssetVersion.id,
        KnowledgeAssetVersion.directory_key != "personal.pending",
    )
    if scope not in (None, "all"):
        stmt = stmt.where(KnowledgeAsset.scope == scope)
    if project_id:
        stmt = stmt.where(KnowledgeAsset.project_id == project_id)
    return [row[0] for row in (await session.execute(stmt)).all() if row[0]]
