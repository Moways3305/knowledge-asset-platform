"""Add stable governed directory assignment to asset versions.

Revision ID: 0061_governed_directories
Revises: 0060_naming_category_asset_type
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0061_governed_directories"
down_revision: str | None = "0060_naming_category_asset_type"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DIRECTORIES = [
    {
        "directory_key": "company.introduction",
        "scope": "company",
        "display_name": "00 公司介绍",
        "sort_order": 0,
    },
    {
        "directory_key": "company.thoughts_knowledge",
        "scope": "company",
        "display_name": "01 思想与知识",
        "sort_order": 10,
    },
    {
        "directory_key": "company.methodology",
        "scope": "company",
        "display_name": "02 方法论",
        "sort_order": 20,
    },
    {
        "directory_key": "company.industry_research",
        "scope": "company",
        "display_name": "03 行业研究",
        "sort_order": 30,
    },
    {
        "directory_key": "company.client_cases",
        "scope": "company",
        "display_name": "04 客户案例",
        "sort_order": 40,
    },
    {
        "directory_key": "company.key_materials",
        "scope": "company",
        "display_name": "05 关键资料",
        "sort_order": 50,
    },
    {
        "directory_key": "company.investment_capital",
        "scope": "company",
        "display_name": "06 投融资与资本",
        "sort_order": 60,
    },
    {
        "directory_key": "company.ai_materials",
        "scope": "company",
        "display_name": "07 AI资料",
        "sort_order": 70,
    },
    {
        "directory_key": "project.basic_information",
        "scope": "project",
        "display_name": "01 项目基础信息",
        "sort_order": 10,
    },
    {
        "directory_key": "project.guidance_process",
        "scope": "project",
        "display_name": "02 辅导过程",
        "sort_order": 20,
    },
    {
        "directory_key": "project.deliverables",
        "scope": "project",
        "display_name": "03 交付成果",
        "sort_order": 30,
    },
    {
        "directory_key": "project.key_materials",
        "scope": "project",
        "display_name": "04 关键资料",
        "sort_order": 40,
    },
    {
        "directory_key": "project.retrospective",
        "scope": "project",
        "display_name": "05 项目复盘",
        "sort_order": 50,
    },
    {
        "directory_key": "personal.learning_notes",
        "scope": "personal",
        "display_name": "01 个人学习笔记",
        "sort_order": 10,
    },
    {
        "directory_key": "personal.project_materials",
        "scope": "personal",
        "display_name": "02 个人项目资料",
        "sort_order": 20,
    },
    {
        "directory_key": "personal.methodology_favorites",
        "scope": "personal",
        "display_name": "03 个人方法论收藏",
        "sort_order": 30,
    },
    {
        "directory_key": "personal.pending",
        "scope": "personal",
        "display_name": "04 待处理",
        "sort_order": 40,
    },
]
_DESCRIPTIONS = {
    "company.introduction": "简介 / 产品 / 宣传",
    "company.thoughts_knowledge": "阅读 / 写作 / 培训",
    "company.methodology": "二级分类与职能维度使用标签",
    "company.industry_research": "简析 / 政策 / 宏观 / 数据",
    "company.client_cases": "脱敏案例",
    "company.key_materials": "合同 / 经营 / 加密索引",
    "company.investment_capital": "投 / 融 / IPO 使用标签",
    "company.ai_materials": "前沿 / 工具 / 案例使用标签",
    "project.basic_information": "合同 / NDA / 立项",
    "project.guidance_process": "周报 / 月报 / 议题",
    "project.deliverables": "诊断 / 战略 / 方案",
    "project.key_materials": "数据 / 人事 / 纪要",
    "project.retrospective": "复盘 / 经验",
    "personal.learning_notes": "按主题以标签辅助分类",
    "personal.project_materials": "项目名称/年份以字段或标签辅助",
    "personal.methodology_favorites": "按类型以标签辅助分类",
    "personal.pending": "待处理 / 待脱敏的个人暂存位置",
}


def _config(raw: object) -> dict:
    if isinstance(raw, str):
        value = json.loads(raw)
        return dict(value) if isinstance(value, dict) else {}
    return dict(raw) if isinstance(raw, dict) else {}


def _update_rule_configs(*, remove: bool = False) -> None:
    connection = op.get_bind()
    rows = connection.execute(sa.text("SELECT id, config FROM naming_rule_revisions")).mappings()
    for row in rows:
        config = _config(row["config"])
        if remove:
            config.pop("directories", None)
        elif not config.get("directories"):
            config["directories"] = [
                {
                    **item,
                    "description": _DESCRIPTIONS[item["directory_key"]],
                    "enabled": True,
                }
                for item in _DIRECTORIES
            ]
        connection.execute(
            sa.text("UPDATE naming_rule_revisions SET config = :config WHERE id = :id").bindparams(
                sa.bindparam("config", type_=sa.JSON())
            ),
            {"id": row["id"], "config": config},
        )


def upgrade() -> None:
    op.add_column(
        "knowledge_asset_versions", sa.Column("directory_key", sa.String(length=100), nullable=True)
    )
    op.add_column(
        "knowledge_asset_versions", sa.Column("directory_rule_version", sa.Integer(), nullable=True)
    )
    op.add_column(
        "knowledge_asset_versions", sa.Column("directory_confirmed_by", sa.Uuid(), nullable=True)
    )
    op.create_foreign_key(
        "fk_asset_version_directory_confirmer",
        "knowledge_asset_versions",
        "users",
        ["directory_confirmed_by"],
        ["id"],
    )
    op.create_index("ix_asset_version_directory_key", "knowledge_asset_versions", ["directory_key"])
    _update_rule_configs()


def downgrade() -> None:
    _update_rule_configs(remove=True)
    op.drop_index("ix_asset_version_directory_key", table_name="knowledge_asset_versions")
    op.drop_constraint(
        "fk_asset_version_directory_confirmer", "knowledge_asset_versions", type_="foreignkey"
    )
    op.drop_column("knowledge_asset_versions", "directory_confirmed_by")
    op.drop_column("knowledge_asset_versions", "directory_rule_version")
    op.drop_column("knowledge_asset_versions", "directory_key")
