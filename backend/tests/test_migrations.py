from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def test_initial_migration_creates_profile_tables(tmp_path: Path) -> None:
    database_path = tmp_path / "migration.db"
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("script_location", str(Path(__file__).parents[1] / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")

    command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    tables = set(inspect(engine).get_table_names())
    assert {
        "user_profile",
        "subscription_preferences",
        "rss_source",
        "news_item",
        "alembic_version",
    } <= tables
    assert "recipient_email" in {
        column["name"] for column in inspect(engine).get_columns("user_profile")
    }
    assert "excluded_keywords" in {
        column["name"] for column in inspect(engine).get_columns("subscription_preferences")
    }
    assert "url_hash" in {column["name"] for column in inspect(engine).get_columns("news_item")}
    news_columns = {column["name"] for column in inspect(engine).get_columns("news_item")}
    assert {
        "original_url",
        "published_at_field",
        "content_truncated",
        "included_at",
    } <= news_columns
    engine.dispose()
