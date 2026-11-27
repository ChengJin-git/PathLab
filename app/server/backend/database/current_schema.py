"""Fresh-install schema and built-in catalog. No historical upgrades/backfills."""

from sqlalchemy import text
from .models import Base, CapabilityEntry

SCHEMA_VERSION = "20261127_public_release"

INDEXES = [
    "CREATE INDEX IF NOT EXISTS ix_ai_result_analysis_rows ON ai_results(task_id,id)",
    "CREATE INDEX IF NOT EXISTS ix_task_wsi_split ON training_task_wsi(task_id,split,wsi_id)",
    "CREATE INDEX IF NOT EXISTS idx_wsi_dataset_case ON wsi_slides(dataset_id,case_id)",
    "CREATE INDEX IF NOT EXISTS idx_wsi_dataset_type_case ON wsi_slides(dataset_id,data_type,case_id)",
    'CREATE INDEX IF NOT EXISTS idx_dataset_mention_name ON datasets(lower(name) COLLATE "C",dataset_id)',
    'CREATE INDEX IF NOT EXISTS idx_wsi_mention_name ON wsi_slides(dataset_id,lower(original_filename) COLLATE "C",wsi_id)',
    'CREATE INDEX IF NOT EXISTS idx_task_mention_name ON training_tasks(user_id,lower(task_name) COLLATE "C",task_id)',
    'CREATE INDEX IF NOT EXISTS idx_model_mention_name ON trained_models(user_id,lower(model_name) COLLATE "C",model_id)',
    'CREATE INDEX IF NOT EXISTS idx_workbench_mention_name ON workbench_files(user_id,lower(name) COLLATE "C",file_id)',
    'CREATE INDEX IF NOT EXISTS idx_workbench_file_order ON workbench_files(user_id,session_id,parent,lower(name) COLLATE "C",file_id)',
    'CREATE INDEX IF NOT EXISTS idx_workbench_conversation_name ON workbench_files(conversation_id,lower(name) COLLATE "C",file_id)',
    'CREATE INDEX IF NOT EXISTS idx_research_mention_order ON auto_research_sessions(user_id,lower(substr(research_question,1,160)) COLLATE "C",session_id)',
    "CREATE INDEX IF NOT EXISTS ix_chat_navigation ON chat_conversations(user_id,folder_id,pinned DESC,updated_at DESC,conversation_id DESC)",
    "CREATE INDEX IF NOT EXISTS ix_chat_navigation_search ON chat_conversations(user_id,pinned DESC,updated_at DESC,conversation_id DESC)",
    "CREATE INDEX IF NOT EXISTS ix_library_owner_recent ON workbench_files(user_id,deleted,updated_at DESC,file_id)",
    "CREATE INDEX IF NOT EXISTS ix_library_folder ON workbench_files(folder_id,deleted,name,file_id)",
    "CREATE INDEX IF NOT EXISTS ix_library_index_jobs ON workbench_files(index_status,index_lease)",
    "CREATE INDEX IF NOT EXISTS idx_capability_search ON capability_entries USING gin ((lower(name || ' ' || description)) gin_trgm_ops)",
]


async def initialize(connection):
    import backend.auth.models  # noqa: F401 - register authentication tables
    from sqlalchemy import inspect

    schema = await connection.scalar(text("SELECT current_schema()"))
    existing = await connection.run_sync(
        lambda c: inspect(c).has_table("users", schema=schema)
    )
    if existing:
        ledger = await connection.run_sync(
            lambda c: inspect(c).has_table("pathlab_schema_migrations", schema=schema)
        )
        if not ledger or not await connection.scalar(
            text("SELECT 1 FROM pathlab_schema_migrations WHERE version=:v"),
            {"v": SCHEMA_VERSION},
        ):
            raise RuntimeError(
                "Database schema does not match this release; deploy the matching database snapshot"
            )
        return
    await connection.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
    await connection.run_sync(lambda c: Base.metadata.create_all(c, checkfirst=False))
    for statement in INDEXES:
        await connection.execute(text(statement))
    await seed_capabilities(connection)
    await connection.execute(
        text(
            "CREATE TABLE pathlab_schema_migrations(version VARCHAR(100) PRIMARY KEY,applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        )
    )
    await connection.execute(
        text("INSERT INTO pathlab_schema_migrations(version) VALUES(:v)"),
        {"v": SCHEMA_VERSION},
    )


async def seed_capabilities(connection):
    from backend.services.command_catalog import LABELS
    from backend.autoresearch.engine.builtin_skills import catalog

    languages = ["en-US", "zh-CN", "zh-HK"]
    rows = []
    for item in catalog():
        if item["id"] == "nature-shared":
            continue
        labels = LABELS[item["id"]]
        rows.append(
            dict(
                entry_id=item["id"],
                kind="skill",
                builtin=True,
                visibility="public",
                name=labels[0][0],
                description=labels[0][1],
                translations={
                    lang: {"name": labels[i][0], "description": labels[i][1]}
                    for i, lang in enumerate(languages)
                },
                config={"skill_id": item["id"]},
                content="",
            )
        )
    for identity, labels in {
        "web_search": [
            ("Web search", "Search current web sources using Exa."),
            ("网页搜索", "通过 Exa 检索最新网页资料。"),
            ("網頁搜尋", "透過 Exa 檢索最新網頁資料。"),
        ],
        "articles": [
            ("Article reader", "Download and read articles with stable citations."),
            ("文章阅读", "下载、阅读文章并保留稳定引用。"),
            ("文章閱讀", "下載、閱讀文章並保留穩定引用。"),
        ],
    }.items():
        rows.append(
            dict(
                entry_id=identity,
                kind="connector",
                builtin=True,
                visibility="public",
                name=labels[0][0],
                description=labels[0][1],
                translations={
                    lang: {"name": labels[i][0], "description": labels[i][1]}
                    for i, lang in enumerate(languages)
                },
                config={"provider": identity},
                content="",
            )
        )
    await connection.execute(CapabilityEntry.__table__.insert(), rows)
