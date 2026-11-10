"""Identify isolated API connections separately from workers in PostgreSQL samples."""

from capacity_common import guard
from sqlalchemy import event

guard()
from app.db.session import get_engine  # noqa: E402


@event.listens_for(get_engine().sync_engine, "connect")
def identify(connection, _record):
    connection.run_async(lambda raw: raw.execute("SET application_name = 'kap-capacity-api'"))


from app.main import app as app  # noqa: E402
