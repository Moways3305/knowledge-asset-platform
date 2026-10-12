"""Source provenance validation shared by history and final replacement."""

from sqlalchemy import select

from app.models.ingest import IngestTask


async def replacement_baseline_matches(session, source, target):
    tasks = (
        await session.scalars(
            select(IngestTask).where(
                IngestTask.result_asset_id == target.id,
                IngestTask.update_of_asset_id.is_not(None),
            )
        )
    ).all()
    # Legacy/manual uploads have no source-bound provenance.
    return all(
        task.update_of_asset_id == source.id
        and task.update_of_version_id == source.current_version_id
        for task in tasks
    )
