"""开发态 seed 数据。

用于本地开发与测试的确定性身份数据。所有 UUID 固定，便于通过
`X-Dev-User-Id` 复现，也便于测试断言。仅用于 local/dev/test，不含真实信息。

覆盖场景：
- 顾问（consultant）：一个项目 consultant 角色 + 一个 inactive 项目成员关系（验证只返回 active）。
- 项目经理（project_manager）：一个项目 project_manager 角色。
- 老板（boss）：可发现 L5。
- 咨询总监（consulting_director）：可发现 L5。
- 纯 admin：is_business_user=false，can_discover_l5=false；并带一个 inactive
  的 consultant 角色（验证只统计 active 公司角色）。
- consultant + admin 双角色：is_business_user=true（来自 consultant，而非 admin）。
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import Project, ProjectMember, User, UserCompanyRole
from app.models.knowledge import (
    KnowledgeAsset,
    KnowledgeAssetSummary,
    KnowledgeAssetTag,
    KnowledgeAssetVersion,
)
from app.models.review import ReviewTask, ReviewTaskEvidence, ValidationEvidence
from app.models.weknora import WeknoraKbMapping

# ---- 固定 UUID（便于 X-Dev-User-Id 与测试断言）----
USER_CONSULTANT = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
USER_PROJECT_MANAGER = uuid.UUID("00000000-0000-0000-0000-0000000000a2")
USER_BOSS = uuid.UUID("00000000-0000-0000-0000-0000000000a3")
USER_DIRECTOR = uuid.UUID("00000000-0000-0000-0000-0000000000a4")
USER_ADMIN_ONLY = uuid.UUID("00000000-0000-0000-0000-0000000000a5")
USER_CONSULTANT_ADMIN = uuid.UUID("00000000-0000-0000-0000-0000000000a6")
# 开发态统一密码（仅 seed / 测试用；生产由 admin 设置，绝不写入 .env.example）。
DEV_PASSWORD = "dev-password-123"

PROJECT_ALPHA = uuid.UUID("00000000-0000-0000-0000-0000000000b1")
PROJECT_BETA = uuid.UUID("00000000-0000-0000-0000-0000000000b2")


async def seed_dev_identities(session: AsyncSession) -> None:
    """写入开发态身份数据。若已存在（按 USER_CONSULTANT 判断）则跳过，保证幂等。"""
    existing = await session.get(User, USER_CONSULTANT)
    if existing is not None:
        return

    # ---- 项目 ----
    alpha = Project(id=PROJECT_ALPHA, name="Alpha 项目", status="active")
    beta = Project(id=PROJECT_BETA, name="Beta 项目", status="active")
    session.add_all([alpha, beta])

    # ---- 顾问 A：consultant 公司角色；Alpha consultant(active) + Beta consultant(inactive) ----
    consultant_a = User(
        id=USER_CONSULTANT,
        name="顾问A",
        email="consultant.a@dev.local",
        status="active",
        # 绑定企微身份（OAuth 回调按 corp_id + wecom_user_id 解析平台用户）。
        wecom_corp_id="test_corp",
        wecom_user_id="ww_consultant_a",
    )
    consultant_a.company_roles.append(UserCompanyRole(company_role="consultant", status="active"))
    consultant_a.project_members.append(
        ProjectMember(project_id=PROJECT_ALPHA, project_role="consultant", status="active")
    )
    consultant_a.project_members.append(
        ProjectMember(project_id=PROJECT_BETA, project_role="consultant", status="inactive")
    )

    # ---- 经理 B：consultant 公司角色；Alpha project_manager(active) ----
    manager_b = User(
        id=USER_PROJECT_MANAGER,
        name="经理B",
        email="pm.b@dev.local",
        status="active",
    )
    manager_b.company_roles.append(UserCompanyRole(company_role="consultant", status="active"))
    manager_b.project_members.append(
        ProjectMember(project_id=PROJECT_ALPHA, project_role="project_manager", status="active")
    )

    # ---- 老板 C：boss，可发现 L5 ----
    boss_c = User(id=USER_BOSS, name="老板C", email="boss.c@dev.local", status="active")
    boss_c.company_roles.append(UserCompanyRole(company_role="boss", status="active"))

    # ---- 总监 D：consulting_director，可发现 L5 ----
    director_d = User(id=USER_DIRECTOR, name="总监D", email="director.d@dev.local", status="active")
    director_d.company_roles.append(
        UserCompanyRole(company_role="consulting_director", status="active")
    )

    # ---- 管理员 E：admin(active) + consultant(inactive) ----
    # 预期：is_business_user=false、can_discover_l5=false；inactive 的 consultant 不计入。
    admin_e = User(id=USER_ADMIN_ONLY, name="管理员E", email="admin.e@dev.local", status="active")
    admin_e.company_roles.append(UserCompanyRole(company_role="admin", status="active"))
    admin_e.company_roles.append(UserCompanyRole(company_role="consultant", status="inactive"))

    # ---- 双角色 F：consultant(active) + admin(active) ----
    # 预期：is_business_user=true（来自 consultant），can_discover_l5=false。
    dual_f = User(
        id=USER_CONSULTANT_ADMIN, name="双角色F", email="dual.f@dev.local", status="active"
    )
    dual_f.company_roles.append(UserCompanyRole(company_role="consultant", status="active"))
    dual_f.company_roles.append(UserCompanyRole(company_role="admin", status="active"))

    # 给开发态用户设置统一开发密码（仅 seed/测试可见，不写入 .env.example）。
    # 真实部署由 admin 经 /admin/people/{id}/password 设置，不依赖此开发密码。
    from datetime import datetime, timezone

    from app.services.passwords import hash_password

    _dev_hash = hash_password(DEV_PASSWORD)
    _set_at = datetime.now(timezone.utc)
    for _u in (consultant_a, manager_b, boss_c, director_d, admin_e, dual_f):
        _u.password_hash = _dev_hash
        _u.password_set_at = _set_at

    session.add_all([consultant_a, manager_b, boss_c, director_d, admin_e, dual_f])
    await session.commit()


async def is_seeded(session: AsyncSession) -> bool:
    """判断是否已写入 seed 数据。"""
    result = await session.execute(select(User.id).where(User.id == USER_CONSULTANT))
    return result.scalar_one_or_none() is not None


# ---- 知识资产固定 UUID----
KA_COMPANY_L2 = uuid.UUID("00000000-0000-0000-0000-0000000000e0")
KA_COMPANY_L4 = uuid.UUID("00000000-0000-0000-0000-0000000000c4")
KA_COMPANY_L5 = uuid.UUID("00000000-0000-0000-0000-0000000000c5")
KA_PROJECT_ALPHA = uuid.UUID("00000000-0000-0000-0000-0000000000e1")
KA_PROJECT_BETA_L3 = uuid.UUID("00000000-0000-0000-0000-0000000000e2")
KA_PERSONAL = uuid.UUID("00000000-0000-0000-0000-0000000000f1")
KA_COMPANY_ARCHIVED = uuid.UUID("00000000-0000-0000-0000-0000000000fa")
# 项目 material 资产
KA_PROJECT_ALPHA_MATERIAL = uuid.UUID("00000000-0000-0000-0000-0000000000e3")
KA_PROJECT_ALPHA_REVIEWABLE = uuid.UUID("00000000-0000-0000-0000-0000000000e4")
# 项目侧 Agent Gateway 边界资产
KA_PROJECT_ALPHA_A4 = uuid.UUID("00000000-0000-0000-0000-0000000000e8")
KA_PROJECT_ALPHA_L5 = uuid.UUID("00000000-0000-0000-0000-0000000000e9")
KA_PROJECT_ALPHA_ARCHIVED = uuid.UUID("00000000-0000-0000-0000-0000000000ea")
# 开发态 seed 的审核任务/证据（用于 /review 页面展示）
EVIDENCE_SEED = uuid.UUID("00000000-0000-0000-0000-0000000000e6")
REVIEW_SEED = uuid.UUID("00000000-0000-0000-0000-0000000000e7")


def _asset(
    asset_id,
    *,
    title,
    scope,
    level,
    ai="A1",
    status="active",
    owner=USER_CONSULTANT,
    project_id=None,
    maintainer=USER_CONSULTANT,
    phase=None,
    zone="asset",
):
    """构造一个知识资产（不含版本/摘要，调用方再补充）。"""
    return KnowledgeAsset(
        id=asset_id,
        title=title,
        scope=scope,
        zone=zone,
        asset_type="methodology",
        owner_user_id=owner,
        maintainer_user_id=maintainer,
        project_id=project_id,
        visibility="public" if scope == "company" else "project_only",
        confidentiality_level=level,
        ai_access_level=ai,
        asset_status=status,
        lifecycle_phase_key=phase,
    )


async def seed_dev_knowledge(session: AsyncSession) -> None:
    """写入开发态知识资产 seed（幂等）。覆盖列表/详情/个人知识三页权限场景。

    seed 不含真实客户数据、真实文件路径、真实对象存储 URL、真实 token。
    """
    existing = await session.get(KnowledgeAsset, KA_COMPANY_L2)
    if existing is not None:
        return

    def _version(asset_id):
        return KnowledgeAssetVersion(
            id=uuid.uuid4(),
            asset_id=asset_id,
            version_no="v1",
            version_status="active",
            created_by=USER_CONSULTANT,
        )

    def _kb_for(asset: KnowledgeAsset) -> str:
        """检索 seed：按 scope 给每个资产版本回写一个确定性 weknora_kb_id（server-only）。"""
        if asset.scope == "company":
            return "wk-kb-company"
        if asset.scope == "project":
            return f"wk-kb-proj-{asset.project_id}"
        return f"wk-kb-personal-{asset.owner_user_id}"

    specs = [
        # company L2：业务用户可发现/摘要/原文。
        (
            _asset(KA_COMPANY_L2, title="零售数字化成熟度评估框架", scope="company", level="L2"),
            {
                "one_liner": "5 维度 23 项指标的零售数字化成熟度评估方法论",
                "detailed": "覆盖战略、组织、流程、数据、技术五个维度的成熟度评估方法论。",
                "key_points": "5 维度模型\n23 项指标\n已在多个项目验证",
            },
            ["数字化转型", "成熟度模型"],
        ),
        # company L4：可发现/脱敏摘要，原文需申请。
        (
            _asset(
                KA_COMPANY_L4, title="医药集采渠道影响分析", scope="company", level="L4", ai="A4"
            ),
            {
                "redacted_summary": "（脱敏）集采政策对药企渠道策略的影响分析概要，不含客户敏感数据。",
                "detailed": "（内部原文，不对外摘要）",
            },
            ["医药", "集采"],
        ),
        # company L5：仅 boss / consulting_director 可发现。
        (
            _asset(KA_COMPANY_L5, title="公司级绝密战略备忘", scope="company", level="L5"),
            {"redacted_summary": "（脱敏）公司级战略备忘安全摘要。"},
            ["战略"],
        ),
        # project Alpha L2：Alpha 成员可发现/摘要/原文。
        (
            _asset(
                KA_PROJECT_ALPHA,
                title="Alpha 项目供应链优化交付报告",
                scope="project",
                level="L2",
                project_id=PROJECT_ALPHA,
                phase="交付",
            ),
            {
                "one_liner": "Alpha 项目供应链端到端优化交付报告",
                "detailed": "采购、仓储、物流三模块的诊断与优化建议。",
                "key_points": "采购优化\n仓储优化\n物流优化",
            },
            ["供应链", "流程优化"],
        ),
        # project Beta L3：consultant_a 非 Beta 成员 → 发现 + 脱敏摘要，原文需申请。
        (
            _asset(
                KA_PROJECT_BETA_L3,
                title="Beta 项目客户访谈洞察",
                scope="project",
                level="L3",
                project_id=PROJECT_BETA,
                phase="诊断",
            ),
            {"redacted_summary": "（脱敏）Beta 项目客户访谈关键洞察安全摘要。"},
            ["访谈", "洞察"],
        ),
        # personal：仅 owner（consultant）本人可见。
        (
            _asset(
                KA_PERSONAL,
                title="个人方法论草稿",
                scope="personal",
                level="L2",
                owner=USER_CONSULTANT,
            ),
            {
                "one_liner": "个人整理的方法论草稿",
                "detailed": "尚未提交到项目的个人知识草稿。",
                "key_points": "草稿\n待整理",
            },
            ["个人", "草稿"],
        ),
        # archived company：默认列表不返回。
        (
            _asset(
                KA_COMPANY_ARCHIVED,
                title="已归档的旧组织诊断指南",
                scope="company",
                level="L1",
                status="archived",
            ),
            {"one_liner": "已归档资产，默认不参与检索"},
            ["组织诊断"],
        ),
        # 项目 material 资产（审核流测试用，无 seed review）。
        (
            _asset(
                KA_PROJECT_ALPHA_MATERIAL,
                title="Alpha 项目资料区待确认材料",
                scope="project",
                level="L2",
                project_id=PROJECT_ALPHA,
                phase="诊断",
                zone="material",
            ),
            {"one_liner": "Alpha 项目资料区材料，待资产化确认", "detailed": "项目过程材料。"},
            ["资料区", "待确认"],
        ),
        # 项目 material 资产（带 seed review，用于 /review 页面展示）。
        (
            _asset(
                KA_PROJECT_ALPHA_REVIEWABLE,
                title="Alpha 项目可复用方法论（待审）",
                scope="project",
                level="L2",
                project_id=PROJECT_ALPHA,
                phase="行动辅导",
                zone="material",
            ),
            {"one_liner": "Alpha 项目内已分享、待项目经理确认为资产", "detailed": "项目内方法论。"},
            ["方法论", "待审"],
        ),
        # 项目 A4 资产：Agent 渠道请求 original 必须降级（不进原文上下文），human 不受限。
        (
            _asset(
                KA_PROJECT_ALPHA_A4,
                title="Alpha 项目 A4 受限交付物",
                scope="project",
                level="L2",
                ai="A4",
                project_id=PROJECT_ALPHA,
                phase="交付",
            ),
            {"one_liner": "Alpha 项目 A4 资产：Agent 仅可用摘要层", "detailed": "A4 受限内容。"},
            ["A4", "受限"],
        ),
        # 项目 L5 资产：普通 consultant 不可发现，不进 Agent 引用/可见明细。
        (
            _asset(
                KA_PROJECT_ALPHA_L5,
                title="Alpha 项目 L5 绝密材料",
                scope="project",
                level="L5",
                project_id=PROJECT_ALPHA,
                phase="诊断",
            ),
            {"redacted_summary": "（脱敏）Alpha 项目 L5 安全摘要。"},
            ["L5", "绝密"],
        ),
        # 项目 archived 资产：不进入 Agent 候选（asset_status=active 过滤）。
        (
            _asset(
                KA_PROJECT_ALPHA_ARCHIVED,
                title="Alpha 项目已归档旧材料",
                scope="project",
                level="L2",
                project_id=PROJECT_ALPHA,
                phase="售前",
                status="archived",
            ),
            {"one_liner": "已归档项目材料，不参与 Agent 检索"},
            ["归档"],
        ),
    ]

    for asset, summaries, tags in specs:
        version = _version(asset.id)
        # 回写 WeKnora 底座引用（server-only，绝不外泄）。doc id 用资产 id 派生，
        # 供 fake WeKnoraClient 在测试中把召回 chunk 的 knowledge_id 映射回该资产。
        version.weknora_kb_id = _kb_for(asset)
        version.weknora_doc_id = f"wk-doc-{asset.id}"
        version.weknora_parse_status = "completed"
        # seed 资产已有底座 doc + 解析完成 → 平台索引状态标 indexed。
        from datetime import datetime, timezone

        version.index_status = "indexed"
        version.indexed_at = datetime.now(timezone.utc)
        asset.current_version_id = version.id
        asset.versions.append(version)
        for stype, content in summaries.items():
            s = KnowledgeAssetSummary(summary_type=stype, content=content)
            s.version = version
            asset.summaries.append(s)
        for tag in tags:
            asset.tags.append(KnowledgeAssetTag(tag_name=tag))
        session.add(asset)

    # scope→KB 映射（供 retrieval.resolve_searchable_kbs 路由）。每个 scope 实体一条，
    # weknora_kb_id 与上面 _kb_for 一致。embedding_model_id 仅占位（测试用 fake，不需真值）。
    session.add_all(
        [
            WeknoraKbMapping(
                scope="company",
                owner_user_id=None,
                project_id=None,
                weknora_kb_id="wk-kb-company",
                embedding_model_id="seed-embed",
                kb_name="company_kb",
                status="active",
            ),
            WeknoraKbMapping(
                scope="project",
                owner_user_id=None,
                project_id=PROJECT_ALPHA,
                weknora_kb_id=f"wk-kb-proj-{PROJECT_ALPHA}",
                embedding_model_id="seed-embed",
                kb_name="project_alpha_kb",
                status="active",
            ),
            WeknoraKbMapping(
                scope="project",
                owner_user_id=None,
                project_id=PROJECT_BETA,
                weknora_kb_id=f"wk-kb-proj-{PROJECT_BETA}",
                embedding_model_id="seed-embed",
                kb_name="project_beta_kb",
                status="active",
            ),
        ]
    )
    # 注意：不在 seed 预建 personal KB 映射——个人库 KB 由入库时懒创建（resolve_or_create_kb），
    # 预建会破坏入库懒创建幂等用例。retrieval 个人 scope 在无映射时返回空 KB 集（安全降级）。

    await session.commit()


async def seed_dev_reviews(session: AsyncSession) -> None:
    """写入开发态审核任务 seed（幂等），用于 /review 页面展示。

    为 KA_PROJECT_ALPHA_REVIEWABLE 创建一条证据 + 一个 pending_reviewer 的
    material_to_asset 审核任务，审核人为 Alpha 项目经理（经理 B）。
    """
    existing = await session.get(ReviewTask, REVIEW_SEED)
    if existing is not None:
        return
    # 依赖知识 seed 已写入。
    asset = await session.get(KnowledgeAsset, KA_PROJECT_ALPHA_REVIEWABLE)
    if asset is None:
        return

    evidence = ValidationEvidence(
        id=EVIDENCE_SEED,
        evidence_type="internal_sharing",
        evidence_category="meeting_minutes",
        related_asset_id=KA_PROJECT_ALPHA_REVIEWABLE,
        project_id=PROJECT_ALPHA,
        submitted_by=USER_CONSULTANT,
        description="项目复盘会内部分享记录（seed 占位，无真实附件）",
        attachments=[{"name": "复盘会纪要", "note": "demo 占位"}],
    )
    session.add(evidence)
    review = ReviewTask(
        id=REVIEW_SEED,
        review_type="material_to_asset",
        trigger_source="internal_sharing",
        target_asset_id=KA_PROJECT_ALPHA_REVIEWABLE,
        target_project_id=PROJECT_ALPHA,
        target_scope="project",
        status="pending_reviewer",
        reviewer_user_id=USER_PROJECT_MANAGER,
        submitted_by=USER_CONSULTANT,
    )
    session.add(review)
    session.add(ReviewTaskEvidence(review_task_id=REVIEW_SEED, evidence_id=EVIDENCE_SEED))
    await session.commit()


async def seed_all(session: AsyncSession) -> None:
    """写入全部开发态 seed（身份 + 知识资产 + 审核），均幂等。"""
    await seed_dev_identities(session)
    await seed_dev_knowledge(session)
    await seed_dev_reviews(session)


# 仅供 local/dev/test 环境的开发态 seed 命令入口允许运行的 APP_ENV。
_DEV_SEED_ALLOWED_ENVS = frozenset({"local", "dev", "test"})


async def _run() -> None:
    """命令行入口实现：连接 DATABASE_URL，写入幂等 seed。

    复用应用配置与异步引擎（不复制数据库 URL 默认值）；仅限开发态环境。
    """
    from app.core.config import get_settings
    from app.db.session import get_engine, get_sessionmaker

    settings = get_settings()
    if settings.app_env not in _DEV_SEED_ALLOWED_ENVS:
        raise SystemExit(
            f"dev seed 仅允许在 {sorted(_DEV_SEED_ALLOWED_ENVS)} 环境运行，"
            f"当前 APP_ENV={settings.app_env}"
        )

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        await seed_all(session)
    await get_engine().dispose()
    print("dev seed 完成（identity + knowledge，幂等）")


def main() -> None:
    """同步包装，供 `python -m app.seed.dev_seed` 调用。"""
    import asyncio

    asyncio.run(_run())


if __name__ == "__main__":
    main()
