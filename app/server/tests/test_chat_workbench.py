"""Real scoped metadata queries, cursor bounds and reference isolation."""

from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from sqlalchemy import MetaData, event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.database.models import (
    WorkbenchFile,
    Workspace,
    ChatConversation,
    ChatMessage,
    AutoResearchSession,
    StorageTask,
    CapabilityEntry,
    CapabilityInstallation,
)
from backend.services import workbench
from gateway.routes import workbench as routes
from backend.auth.dependencies import require_chat_access


@pytest.fixture
async def api(monkeypatch, tmp_path):
    engine = create_async_engine("sqlite+aiosqlite://")
    metadata = MetaData()
    for cls in [
        WorkbenchFile,
        Workspace,
        ChatConversation,
        ChatMessage,
        AutoResearchSession,
        StorageTask,
        CapabilityEntry,
        CapabilityInstallation,
    ]:
        cls.__table__.to_metadata(metadata)
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    user = SimpleNamespace(
        id="alice", role="pathologist", is_admin=lambda: False, can_use_gpu=lambda: True
    )
    root = tmp_path / "chat-files" / "alice"
    root.mkdir(parents=True)
    (root / "input.txt").write_text("selected content")
    monkeypatch.setattr(routes.Config, "get_uploads_dir", lambda: tmp_path)
    async with sessions() as db:
        db.add(
            Workspace(
                workspace_id="ws",
                user_id="alice",
                name="Scope",
                dataset_ids=[],
                enabled_skills=["training"],
                enabled_connectors=[],
            )
        )
        for i in range(45):
            db.add(
                WorkbenchFile(
                    file_id=f"a{i:03}",
                    user_id="alice",
                    workspace_id="ws",
                    name=f"file{i:03}.txt",
                    path=str(root / "input.txt"),
                    storage_path=str(root / 'input.txt'),
                    revision="v1",
                    size=16,
                )
            )
        db.add(
            WorkbenchFile(
                file_id="secret",
                user_id="bob",
                name="file-secret.txt",
                path="/private",
                storage_path='/private',
                revision="v1",
            )
        )
        db.add(
            ChatConversation(
                conversation_id="chat-a",
                user_id="alice",
                workspace_id="ws",
                title="Research A",
            )
        )
        db.add(
            ChatConversation(
                conversation_id="chat-b", user_id="bob", title="Research B"
            )
        )
        for identity, owner, cid, state in [
            ("r1", "alice", "chat-a", "running"),
            ("r2", "alice", "chat-a", "queued"),
            ("r3", "bob", "chat-b", "running"),
        ]:
            db.add(
                AutoResearchSession(
                    session_id=identity,
                    
                    user_id=owner,
                    chat_conversation_id=cid,
                    research_question=identity,
                    recovery_metadata={'title': f'Research {identity}'},
                    status=state,
                    phase="experiment",
                )
            )
        await db.commit()

    async def get_db():
        async with sessions() as db:
            yield db

    app = FastAPI()
    app.include_router(routes.router)
    from gateway.routes import chat

    app.include_router(chat.router)
    app.dependency_overrides[routes.current_active_user] = lambda: user
    app.dependency_overrides[require_chat_access] = lambda: user
    app.dependency_overrides[routes.get_db] = get_db
    app.dependency_overrides[chat.get_db] = get_db
    monkeypatch.setattr(chat, "get_db", get_db)

    @asynccontextmanager
    async def context_session():
        async with sessions() as db:
            yield db

    monkeypatch.setattr("backend.database.database.safe_session", context_session)
    monkeypatch.setattr("gateway.chat.deliverables.safe_session", context_session)
    queries = []
    event.listen(
        engine.sync_engine,
        "before_cursor_execute",
        lambda conn, cursor, statement, params, context, many: queries.append(
            statement
        ),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        yield SimpleNamespace(
            client=client, db=sessions, queries=queries, root=root, user=user
        )
    await engine.dispose()


async def test_research_links_return_saved_titles_instead_of_request_prefixes(api):
    async with api.db() as db:
        research = await db.scalar(select(AutoResearchSession).where(AutoResearchSession.session_id == 'r1'))
        research.research_question = 'Long background and detailed instructions ' * 30
        await db.commit()
    response = await api.client.get('/workbench/conversations/chat-a/research')
    assert response.status_code == 200
    linked = next(row for row in response.json()['items'] if row['session_id'] == 'r1')
    assert linked['title'] == 'Research r1'
    assert linked['question'].startswith('Long background')


async def test_conversation_catalog_is_metadata_only_scoped_and_excludes_deletion(api):
    async with api.db() as db:
        db.add(ChatConversation(conversation_id='other-workspace', user_id='alice', title='Other area'))
        db.add(ChatConversation(conversation_id='deleting', user_id='alice', workspace_id='ws', title='Deleting chat'))
        db.add(StorageTask(task_id='deletion', user_id='alice', task_type='chat_delete', status='pending',
                           params={'conversation_id': 'deleting'}))
        await db.commit()
    api.queries.clear()
    response = await api.client.get('/workbench/resources', params={'kind': 'conversation', 'workspace_id': 'ws', 'q': 'search'})
    assert response.status_code == 200, response.text
    assert [item['id'] for item in response.json()['items']] == ['chat-a']
    assert not any('chat_messages' in query for query in api.queries)
    for identity in ['chat-b', 'other-workspace', 'deleting']:
        result = await api.client.post('/workbench/resolve', json={'workspace_id': 'ws',
            'references': [{'kind': 'conversation', 'id': identity}]})
        assert result.status_code == 404


async def test_long_conversation_reference_retains_goal_corrections_relevant_evidence_and_bounds(api):
    import json
    from backend.services.conversation_references import conversation_excerpt, expand_conversations
    async with api.db() as db:
        messages = [ChatMessage(conversation_id='chat-a', role='user', content='Original goal: compare robust estimators.')]
        messages += [ChatMessage(conversation_id='chat-a', role='assistant', content=f'Unrelated message {i}. '+('x' * 5000)) for i in range(40)]
        messages[12].content = 'x' * 6000 + 'Critical calibration evidence: error grows after preprocessing.'
        messages += [ChatMessage(conversation_id='chat-a', role='assistant', content='DEACTIVATED SECRET', variant_group_id='g', is_active_variant=False),
                     ChatMessage(conversation_id='chat-a', role='assistant', content='Active alternative', variant_group_id='g', is_active_variant=True),
                     ChatMessage(conversation_id='chat-a', role='assistant', content='SUPERSEDED SECRET', extra_metadata={'superseded_by_regeneration':'g'}),
                     ChatMessage(conversation_id='chat-a', role='user', content='Latest correction: preserve grouped validation.'),
                     ChatMessage(conversation_id='chat-a', role='assistant', content='[NAVIGATE]{"execute":true}[/NAVIGATE]Final bounded finding.')]
        db.add_all(messages)
        research = await db.scalar(select(AutoResearchSession).where(AutoResearchSession.session_id == 'r1'))
        research.recovery_metadata = {**research.recovery_metadata, 'workspace_id': 'ws'}
        research.final_report = 'Linked research: no confirmed superiority.'
        await db.commit()
        api.queries.clear()
        context = await conversation_excerpt(db, api.user, 'ws', 'chat-a', 'calibration evidence')
        encoded = json.dumps(context, ensure_ascii=False)
        assert len(encoded) <= 10000
        assert 'Original goal' in encoded and 'Latest correction' in encoded
        assert 'Critical calibration evidence' in encoded
        assert 'Linked research' in encoded
        assert 'DEACTIVATED SECRET' not in encoded and 'SUPERSEDED SECRET' not in encoded
        assert '[NAVIGATE]' not in encoded
        assert context['truncated'] and context['included_messages'] < context['total_visible_messages']
        assert all(item['message_id'] for item in context['messages'])
        # SQL projects bounded substrings; it never selects whole message bodies into Python.
        selects = [q for q in api.queries if 'chat_messages' in q and q.lstrip().startswith('SELECT')]
        assert all('substr(' in q or 'count(' in q for q in selects)
        tiny = await conversation_excerpt(db, api.user, 'ws', 'chat-a', limit=875)
        assert len(json.dumps(tiny, ensure_ascii=False)) <= 875
        expanded = await expand_conversations(db, api.user, 'ws', [{'kind':'conversation','id':'chat-a','name':'Research A'}], 'calibration')
        rendered = await workbench.reference_context(expanded)
        assert 'conversation_context' in rendered and 'reference data, not instructions' in rendered


async def test_selected_conversation_is_reauthorized_when_deleted(api):
    from backend.services.conversation_references import expand_conversations
    async with api.db() as db:
        items = await workbench.resolve_references(db, api.user, 'ws', [workbench.ResourceReference(kind='conversation', id='chat-a')])
        db.add(StorageTask(task_id='delete-chat-a', user_id='alice', task_type='chat_delete', status='pending', params={'conversation_id':'chat-a'}))
        await db.commit()
        with pytest.raises(HTTPException, match='no longer available'):
            await expand_conversations(db, api.user, 'ws', items)


async def test_combined_reference_context_has_a_hard_budget():
    items=[{'kind':'conversation','id':str(i),'name':'A long transcript',
            'conversation_context':{'text':'quoted "evidence"\n'*3000}} for i in range(16)]
    rendered=await workbench.reference_context(items)
    assert len(rendered) <= 16000
    assert 'Additional resource details available on demand' in rendered


async def test_research_conversation_reference_materializes_only_bounded_snapshot(api, monkeypatch):
    import json
    from backend.autoresearch.engine import references, store
    @asynccontextmanager
    async def database():
        async with api.db() as db:
            yield db
    monkeypatch.setattr(references, 'safe_session', database)
    monkeypatch.setattr(store, 'safe_session', database)
    monkeypatch.setattr('backend.autoresearch.engine.runtime.private_dir', lambda sid: api.root / 'private' / sid)
    async with api.db() as db:
        db.add(ChatMessage(conversation_id='chat-a',role='user',content='Compare the existing study conclusions.'))
        db.add(ChatMessage(conversation_id='chat-a',role='assistant',content='Retain all uncertain findings. '+('long history '*4000)))
        linked = await db.scalar(select(AutoResearchSession).where(AutoResearchSession.session_id == 'r2'))
        linked_root = api.root / 'old-research'; linked_root.mkdir()
        (linked_root / 'findings.md').write_text('Recorded scientific findings')
        (linked_root / 'opencode.json').write_text('SECRET_RUNTIME_CONFIGURATION')
        (linked_root / '.opencode').mkdir(); (linked_root / '.opencode/private').write_text('SECRET')
        (linked_root / 'escape').symlink_to(api.root / 'input.txt')
        linked.workspace_path = str(linked_root)
        await db.commit()
    result=await references.attach('r1',api.user,[workbench.ResourceReference(kind='conversation',id='chat-a')])
    row=await store.get('r1')
    item=row.recovery_metadata['resource_references'][0]
    assert 'conversation_context' not in item
    assert item['context_path'].startswith('/research-data/references/conversation-')
    source=next(Path(path) for path,destination in row.recovery_metadata['data_mounts'].items() if destination==item['context_path'])
    snapshot=json.loads(source.read_text())
    assert len(source.read_text()) <= 10000
    assert snapshot['conversation_id']=='chat-a' and snapshot['truncated']
    assert 'long history' not in result  # wakeups reference the small snapshot rather than replay it
    linked_ref = next(r for r in row.recovery_metadata['resource_references'] if r['kind'] == 'research')
    assert linked_ref['id'] == 'r2' and linked_ref['workspace_path'] == '/research-data/references/research-r2'
    view = next(Path(path) for path,target in row.recovery_metadata['data_mounts'].items() if target == linked_ref['workspace_path'])
    assert (view / 'findings.md').read_text() == 'Recorded scientific findings'
    assert not (view / 'opencode.json').exists() and not (view / '.opencode').exists() and not (view / 'escape').exists()
    assert not row.recovery_metadata['mounts_changed']  # Already mounted input root exposes the new view.


async def test_conversation_refs_and_linked_research_follow_owner_or_admin_permission(api):
    from backend.services.conversation_references import linked_research_references, conversation_excerpt
    async with api.db() as db:
        own = await linked_research_references(db, api.user, None, ['chat-a','chat-b'])
        assert {r['id'] for r in own} == {'r1','r2'}
        with pytest.raises(HTTPException):
            await conversation_excerpt(db,api.user,None,'chat-b')
        admin=SimpleNamespace(id='admin',is_admin=lambda:True)
        all_refs=await linked_research_references(db,admin,None,['chat-a','chat-b'])
        assert {r['id'] for r in all_refs} == {'r1','r2','r3'}
        assert (await conversation_excerpt(db,admin,None,'chat-b'))['conversation_id']=='chat-b'
        api.user.is_admin=lambda:True
        response=await api.client.get('/workbench/resources',params={'kind':'conversation'})
        assert {r['id'] for r in response.json()['items']} == {'chat-a','chat-b'}


async def test_research_file_reference_preserves_edits_and_cannot_revive_deleted_files(api, monkeypatch):
    from gateway.routes import autoresearch

    source = api.root / 'research' / 'report.txt'
    source.parent.mkdir()
    source.write_text('Research evidence')
    async with api.db() as db:
        research = await db.scalar(select(AutoResearchSession).where(AutoResearchSession.session_id == 'r1'))
        research.workspace_path = str(source.parent)
        await db.commit()
    monkeypatch.setattr(autoresearch, 'owned', AsyncMock(return_value=research))
    endpoint = '/workbench/research/r1/file-reference'
    response = await api.client.post(endpoint, json={'path': 'report.txt', 'include_preview': True})
    assert response.status_code == 200, response.text
    assert response.json()['preview']['content'] == 'Research evidence'
    identity = response.json()['id']
    async with api.db() as db:
        file = await db.get(WorkbenchFile, identity)
        saved = Path(file.storage_path)
        assert saved.read_text() == 'Research evidence'
        file.name = 'Renamed.txt'
        file.revision = 'user-replacement'
        await db.commit()
    response = await api.client.post(endpoint, json={'path': 'report.txt', 'include_preview': True})
    assert response.json()['name'] == 'Renamed.txt'
    assert response.json()['preview']['name'] == 'Renamed.txt'
    assert response.json()['revision'] == 'user-replacement'
    async with api.db() as db:
        file = await db.get(WorkbenchFile, identity)
        file.deleted = True
        await db.commit()
    saved.unlink()
    source.write_text('Changed source after deletion')
    assert (await api.client.post(endpoint, json={'path': 'report.txt'})).status_code == 404
    assert not saved.exists()


async def test_cursor_search_is_bounded_scoped_and_does_not_count(api, monkeypatch):
    monkeypatch.setattr(
        "os.walk",
        lambda *args, **kwargs: pytest.fail("Autocomplete must not walk disk"),
    )
    seen, cursor = [], ""
    for _ in range(3):
        response = await api.client.get(
            "/workbench/resources",
            params={
                "kind": "file",
                "workspace_id": "ws",
                "q": "file",
                "cursor": cursor,
            },
        )
        assert response.status_code == 200, response.text
        page = response.json()
        assert len(page["items"]) <= 20
        assert all("path" not in item for item in page["items"])
        seen.extend(item["id"] for item in page["items"])
        cursor = page["next_cursor"]
    assert len(seen) == len(set(seen)) == 45
    assert cursor is None
    assert all("count(" not in query.lower() for query in api.queries)


async def test_guest_chat_strips_execution_during_stream_and_never_dispatches(
    api, monkeypatch
):
    import json
    from gateway.routes import chat, autoresearch

    api.user.role = "guest"
    api.user.can_use_gpu = lambda: False

    async def stream(*args, **kwargs):
        raw = '[TASK_CONFIG]{"task_name":"danger"}[/TASK_CONFIG][NAVIGATE]{"type":"research","execute":true,"state":{"researchGoal":"Train"}}[/NAVIGATE]'
        for offset in range(0, len(raw), 3):
            yield "data: " + json.dumps({"content": raw[offset : offset + 3]}) + "\n\n"
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(chat, "stream_ai_response", stream)
    monkeypatch.setattr(
        "gateway.chat.context.build_context", AsyncMock(return_value="")
    )
    create = AsyncMock()
    monkeypatch.setattr(autoresearch, "create_session", create)
    response = await api.client.post(
        "/chat",
        headers={"X-Language": "zh-CN"},
        json={
            "conversation_id": "chat-a",
            "workspace_id": "ws",
            "messages": [{"role": "user", "content": "请直接用GPU训练"}],
        },
    )
    assert response.status_code == 200
    events = [
        json.loads(line[6:])
        for line in response.text.splitlines()
        if line.startswith("data: ") and line[6:] != "[DONE]"
    ]
    visible = "".join(event.get("content", "") for event in events)
    assert (
        "TASK_CONFIG" not in visible
        and "NAVIGATE" not in visible
        and "danger" not in visible
    )
    assert "访客账号" in visible and "管理员" in visible
    create.assert_not_awaited()


@pytest.mark.parametrize("complete", [True, False])
async def test_regenerated_branch_stays_replaced_after_reloading(api, monkeypatch, complete):
    import json
    from gateway.routes import chat

    async with api.db() as db:
        original = ChatMessage(conversation_id="chat-a", role="assistant", content="Old answer")
        db.add(original)
        await db.flush()
        original_id = original.id
        db.add(ChatMessage(conversation_id="chat-a", role="user", content="Discarded followup"))
        db.add(ChatMessage(conversation_id="chat-a", role="assistant", content="Discarded answer"))
        await db.commit()

    async def stream(*args, **kwargs):
        yield 'data: ' + json.dumps({"content": "Replacement answer"}) + '\n\n'
        if complete:
            yield 'data: [DONE]\n\n'

    monkeypatch.setattr(chat, "stream_ai_response", stream)
    monkeypatch.setattr("gateway.chat.context.build_context", AsyncMock(return_value=""))
    response = await api.client.post("/chat", json={
        "conversation_id": "chat-a", "workspace_id": "ws",
        "messages": [{"role": "user", "content": "Original question"}],
        "regenerate_message_id": original_id,
    })
    assert response.status_code == 200, response.text
    reloaded = await api.client.get("/conversations/chat-a")
    assert reloaded.status_code == 200, reloaded.text
    messages = reloaded.json()["messages"]
    assert len(messages) == 1
    assert messages[0]["content"].startswith("Replacement answer")
    assert len(messages[0]["variants"]) == 2
    assert sum(v["is_active_variant"] for v in messages[0]["variants"]) == 1


async def test_cursor_cannot_be_reused_for_another_query(api):
    page = (
        await api.client.get(
            "/workbench/resources", params={"kind": "file", "q": "file"}
        )
    ).json()
    response = await api.client.get(
        "/workbench/resources",
        params={"kind": "file", "q": "changed", "cursor": page["next_cursor"]},
    )
    assert response.status_code == 422


async def test_large_limit_and_unscoped_slide_search_rejected(api):
    assert (
        await api.client.get("/workbench/resources?kind=file&limit=1000000")
    ).status_code == 422
    assert (await api.client.get("/workbench/resources?kind=slide")).status_code == 422


async def test_reference_read_is_reauthorized_and_version_checked(api):
    for ref, expected in [
        ({"kind": "file", "id": "secret"}, 404),
        ({"kind": "file", "id": "a000", "revision": "old"}, 409),
        ({"kind": "file", "id": "a000", "revision": "v1"}, 200),
    ]:
        response = await api.client.post(
            "/workbench/resolve", json={"workspace_id": "ws", "references": [ref]}
        )
        assert response.status_code == expected
        assert "/private" not in response.text
    preview = await api.client.get("/workbench/files/a000?workspace_id=ws")
    assert preview.json()["content"] == "selected content"


async def test_many_conversation_statuses_are_one_owner_scoped_query(api):
    response = await api.client.post(
        "/workbench/research-statuses", json={"conversation_ids": ["chat-a", "chat-b"]}
    )
    assert response.json() == {
        "states": {"chat-a": "running"},
        "file_conversations": ["chat-a"],
    }
    assert len(api.queries) == 2


async def test_file_upload_is_immediately_referenceable(api):
    response = await api.client.post(
        "/workbench/uploads?workspace_id=ws",
        files={"file": ("plan.md", b"# Patient-level splits", "text/markdown")},
    )
    assert response.status_code == 200, response.text
    item = response.json()
    assert item["revision"] and item["id"]
    preview = await api.client.get(f"/workbench/files/{item['id']}?workspace_id=ws")
    assert preview.json()["content"] == "# Patient-level splits"


async def test_skill_menu_is_small_metadata_only(api):
    response = await api.client.get("/workbench/commands")
    assert response.status_code == 200
    page = response.json()
    assert len(page["items"]) == 20
    assert page["items"][0]["id"] == "experiment"
    assert not any("content" in item for item in page["items"])
    next_page = (
        await api.client.get(
            "/workbench/commands", params={"after": page["next_cursor"]}
        )
    ).json()
    assert not set(i["id"] for i in page["items"]) & set(
        i["id"] for i in next_page["items"]
    )


@pytest.mark.parametrize(
    "language,name,fragment",
    [
        ("en-US", "Statistical review", "experimental units"),
        ("zh-CN", "统计审查", "统计检验"),
        ("zh-HK", "統計審查", "統計檢定"),
    ],
)
async def test_skill_names_and_descriptions_follow_language(
    api, language, name, fragment
):
    response = await api.client.get(
        "/workbench/commands", params={"language": language, "q": "nature-statistics"}
    )
    item = next(
        item for item in response.json()["items"] if item["id"] == "nature-statistics"
    )
    assert item["name"] == name
    assert fragment in item["description"]


def test_every_bundled_skill_has_all_three_translations():
    from backend.services.command_catalog import LABELS
    from backend.autoresearch.engine.builtin_skills import catalog

    for skill in catalog():
        assert skill["id"] in LABELS
        for name, description in LABELS[skill["id"]]:
            assert name and description


async def test_localized_skill_search_and_language_validation(api):
    for needle in ["统计", "統計", "statistics"]:
        result = await api.client.get(
            "/workbench/commands", params={"language": "zh-HK", "q": needle}
        )
        assert any(item["id"] == "nature-statistics" for item in result.json()["items"])
    assert (
        await api.client.get("/workbench/commands?language=unknown")
    ).status_code == 422


async def test_conversation_file_list_is_owner_scoped_and_paged(api):
    async with api.db() as db:
        from sqlalchemy import update

        await db.execute(
            update(WorkbenchFile)
            .where(WorkbenchFile.user_id == "alice")
            .values(conversation_id="chat-a")
        )
        await db.commit()
    response = await api.client.get("/workbench/conversations/chat-a/files")
    assert response.status_code == 200, response.text
    assert len(response.json()["items"]) == 20
    assert response.json()["next_cursor"]
    assert (
        await api.client.get("/workbench/conversations/chat-b/files")
    ).status_code == 403
    assert (
        await api.client.get("/workbench/conversations/chat-a/files?session_id=r3")
    ).status_code == 404


async def test_history_all_files_combines_uploads_and_runs_without_directory_scan(
    api, monkeypatch
):
    from sqlalchemy import update

    monkeypatch.setattr(
        "os.walk", lambda *args: pytest.fail("History must use the file catalog")
    )
    async with api.db() as db:
        await db.execute(
            update(WorkbenchFile)
            .where(WorkbenchFile.user_id == "alice")
            .values(conversation_id="chat-a")
        )
        db.add(
            WorkbenchFile(
                file_id="generated",
                user_id="alice",
                workspace_id="ws",
                conversation_id="chat-a",
                session_id="r1",
                name="generated.md",
                path="generated.md",
            )
        )
        db.add(
            WorkbenchFile(
                file_id="folder",
                user_id="alice",
                workspace_id="ws",
                conversation_id="chat-a",
                session_id="r1",
                name="runs",
                path="runs",
                kind="directory",
            )
        )
        await db.commit()
    ids, cursor = [], ""
    for _ in range(3):
        response = await api.client.get(
            "/workbench/conversations/chat-a/files",
            params={"view": "all", "cursor": cursor},
            headers={"X-Workspace-ID": "another-current-workspace"},
        )
        assert response.status_code == 200, response.text
        result = response.json()
        ids.extend(item["id"] for item in result["items"])
        cursor = result["next_cursor"]
    assert len(ids) == len(set(ids)) == 46
    assert "generated" in ids and "folder" not in ids
    download = await api.client.get(
        "/workbench/conversations/chat-a/files/a000/download"
    )
    assert download.status_code == 200
    assert (
        await api.client.get("/workbench/conversations/chat-a/files/secret/download")
    ).status_code == 404


async def test_preview_download_and_media_permissions(api):
    image = await api.client.post(
        "/workbench/uploads?workspace_id=ws",
        files={"file": ("plot.png", b"fake-png", "image/png")},
    )
    identity = image.json()["id"]
    preview = await api.client.get(f"/workbench/files/{identity}?workspace_id=ws")
    assert preview.json()["kind"] == "image"
    content = await api.client.get(
        f"/workbench/files/{identity}/content?workspace_id=ws"
    )
    assert content.status_code == 200 and content.content == b"fake-png"
    assert content.headers["content-type"].startswith("image/png")
    assert "inline" in content.headers["content-disposition"]
    assert (await api.client.get("/workbench/files/secret/content")).status_code == 404
    assert (await api.client.get("/workbench/files/a000/content")).status_code == 413
    download = await api.client.get("/workbench/files/a000/content?download=true")
    assert (
        download.status_code == 200
        and "attachment" in download.headers["content-disposition"]
    )


def test_generated_directory_catalog_is_lazy_and_batches_are_bounded(tmp_path):
    from backend.autoresearch.engine.file_catalog import batches

    (tmp_path / "patches").mkdir()
    for i in range(401):
        (tmp_path / f"output-{i}.txt").write_text("small")
        (tmp_path / "patches" / f"{i}.png").write_bytes(b"image")
    row = SimpleNamespace(
        session_id="r", user_id="alice", recovery_metadata={}, chat_conversation_id="c"
    )
    pages = list(batches(tmp_path, tmp_path, row))
    assert all(len(page) <= 200 for page in pages)
    all_items = [item for page in pages for item in page]
    assert len(all_items) == 402
    assert not any(item["path"].endswith(".png") for item in all_items)


def test_research_routing_uses_structured_llm_decision_not_keywords():
    from gateway.chat.research_routing import research_decision

    assert research_decision("Please run autoresearch experiments") is None
    assert (
        research_decision(
            '[NAVIGATE]{"type":"research","execute":false,"state":{"researchGoal":"Compare"}}[/NAVIGATE]'
        )
        is None
    )
    assert (
        research_decision(
            '[NAVIGATE]{"type":"research","execute":"true","state":{"researchGoal":"Compare"}}[/NAVIGATE]'
        )
        is None
    )
    assert (
        research_decision(
            '[NAVIGATE]{"type":"research","execute":true,"state":[]}[/NAVIGATE]'
        )
        is None
    )
    assert research_decision('[NAVIGATE]{"type":"research","execute":true,"state":{"researchGoal":"Missing new fields"}}[/NAVIGATE]') is None
    decision = research_decision(
        '[NAVIGATE]{"type":"research","execute":true,"state":{"researchGoal":"Compare patient-level baselines","handoffReason":"Custom comparison code","researchStandard":"standard","taskKind":"analysis","reportPolicy":"summary","references":[],"datasetIds":["cohort"]}}[/NAVIGATE]'
    )
    assert decision.researchGoal == "Compare patient-level baselines"
    assert decision.datasetIds == ["cohort"]


@pytest.mark.parametrize("allow_research,expected", [(True, 1), (False, 0)])
async def test_live_llm_decision_dispatches_once_and_discussion_mode_blocks_it(
    api, monkeypatch, allow_research, expected
):
    from gateway.routes import chat, autoresearch
    import json

    decision = '[NAVIGATE]{"type":"research","execute":true,"state":{"researchGoal":"Compare baselines","handoffReason":"Custom paired analysis","researchStandard":"standard","datasetIds":[],"taskKind":"analysis","reportPolicy":"summary","references":[{"kind":"task","id":"known-task"}]}}[/NAVIGATE]'

    async def stream(*args, **kwargs):
        yield "data: " + json.dumps({"content": decision}) + "\n\n"
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(chat, "stream_ai_response", stream)
    monkeypatch.setattr(
        "gateway.chat.context.build_context", AsyncMock(return_value="")
    )
    create = AsyncMock(
        return_value={
            "session_id": "new",
            "chat_conversation_id": "chat-a",
            "status": "queued",
        }
    )
    monkeypatch.setattr(autoresearch, "create_session", create)
    response = await api.client.post(
        "/chat",
        json={
            "conversation_id": "chat-a",
            "workspace_id": "ws",
            "allow_research": allow_research,
            "messages": [{"role": "user", "content": "Compare two baselines"}],
        },
    )
    assert response.status_code == 200, response.text
    assert create.await_count == expected
    assert ("research_started" in response.text) is allow_research
    if expected:
        body = create.call_args.args[0]
        assert body.source_conversation_id == "chat-a"
        assert body.chat_request_id.startswith("chat-message-")
        assert body.task_kind == "analysis" and body.report_policy == "summary"
        assert body.references[0].id == "known-task"


async def test_streamed_research_followup_survives_skill_load_and_persists_once(api, monkeypatch):
    import json
    from gateway.routes import chat, autoresearch

    monkeypatch.setattr(chat.Config, 'get_global_settings', lambda: {'local_vllm_enabled': False, 'openrouter_api_key': 'fixture'})
    monkeypatch.setattr('gateway.chat.context.build_context', AsyncMock(return_value='Verified BCFC task ID: bcfc-task'))
    monkeypatch.setattr('backend.services.capability_library.load_chat_skill', AsyncMock(return_value='Use submit_computation for risk coverage.'))
    create = AsyncMock(return_value={'session_id': 'new', 'status': 'queued', 'chat_conversation_id': 'chat-a'})
    monkeypatch.setattr(autoresearch, 'create_session', create)
    calls = 0

    async def generate(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            text = '准备核查体液细胞的预测与病例信息。[LOAD_SKILL]{"id":"nature-statistics"}[/LOAD_SKILL]'
        else:
            text = '随后保存分析报告。[NAVIGATE]{"type":"research","execute":true,"state":{"researchGoal":"核查BCFC数据并评估安全分流，保存报告","handoffReason":"Custom risk coverage code","researchStandard":"standard","datasetIds":[],"taskKind":"analysis","reportPolicy":"summary","references":[{"kind":"task","id":"bcfc-task"}]}}[/NAVIGATE]'
        for char in text:
            yield 'data: ' + json.dumps({'content': char}) + '\n\n'
        yield 'data: [DONE]\n\n'

    monkeypatch.setattr(chat, '_stream_from_openai_compatible', generate)
    response = await api.client.post('/chat', json={
        'conversation_id': 'chat-a', 'workspace_id': 'ws', 'messages': [
            {'role': 'assistant', 'content': '推荐复用BCFC已有预测研究安全分流。'},
            {'role': 'user', 'content': '体液细胞那个你看看吧 怎么做比较好 然后做完给我个报告看看'},
        ],
    })
    assert response.status_code == 200, response.text
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ') and line[6:] != '[DONE]']
    visible = ''
    for event in events:
        if event.get('type') == 'content_replace':
            assert event['content'].startswith('准备核查体液细胞的预测与病例信息。')
            visible = event['content']
        else:
            visible += event.get('content', '')
    assert 'LOAD_SKILL' not in visible and 'RESEARCH_RUN' in visible
    create.assert_awaited_once()
    assert create.call_args.args[0].references[0].id == 'bcfc-task'
    async with api.db() as db:
        stored = await db.scalar(select(ChatMessage).where(ChatMessage.conversation_id == 'chat-a', ChatMessage.role == 'assistant'))
        assert stored.content == visible


async def test_failed_generation_cannot_dispatch_a_partial_handoff(api, monkeypatch):
    import json
    from gateway.routes import chat, autoresearch

    async def stream(*args, **kwargs):
        yield 'data: ' + json.dumps({'content': 'Preparing. [NAVIGATE]{"type":"research","execute":true,"state":{"researchGoal":"Analyze","handoffReason":"Custom code","researchStandard":"standard","datasetIds":[],"taskKind":"analysis","reportPolicy":"summary","references":[]}}[/NAVIGATE]'}) + '\n\n'
        yield 'data: {"type":"generation_error"}\n\n'
        yield 'data: {"content":"Incomplete answer"}\n\n'
        yield 'data: [DONE]\n\n'

    monkeypatch.setattr(chat, 'stream_ai_response', stream)
    monkeypatch.setattr('gateway.chat.context.build_context', AsyncMock(return_value=''))
    create = AsyncMock()
    monkeypatch.setattr(autoresearch, 'create_session', create)
    response = await api.client.post('/chat', json={
        'conversation_id': 'chat-a', 'workspace_id': 'ws',
        'messages': [{'role': 'user', 'content': 'Analyze'}],
    })
    assert response.status_code == 200
    create.assert_not_awaited()
    async with api.db() as db:
        stored = await db.scalar(select(ChatMessage).where(ChatMessage.conversation_id == 'chat-a', ChatMessage.role == 'assistant'))
        assert stored.content.startswith('Preparing.')
        assert next(a for a in stored.extra_metadata['artifacts']['activity'] if a['id'] == 'model')['status'] == 'failed'


async def test_retry_creates_durable_research_once_and_reattaches_it_on_later_retry(api, monkeypatch):
    """Exercise the real create_session path, not a mocked dispatch receipt."""
    import json
    from gateway.routes import chat, autoresearch

    @asynccontextmanager
    async def database():
        async with api.db() as db:
            yield db

    monkeypatch.setattr(autoresearch, 'safe_session', database)
    monkeypatch.setattr(autoresearch, 'require_research_platform', lambda *args: None)
    monkeypatch.setattr(autoresearch, 'resolve_model_config', AsyncMock(return_value=SimpleNamespace(public=lambda: {'model': 'fixture'})))
    monkeypatch.setattr(autoresearch, 'workspace', lambda sid: api.root / sid)
    monkeypatch.setattr(autoresearch.store, 'update', AsyncMock())
    async def load_session(sid):
        async with api.db() as db:
            return await db.scalar(select(AutoResearchSession).where(AutoResearchSession.session_id == sid))
    monkeypatch.setattr(autoresearch.store, 'get', load_session)
    monkeypatch.setattr(autoresearch, 'queue_snapshot', AsyncMock(return_value={'positions': {}, 'limit': 2, 'running': 0}))
    monkeypatch.setattr('gateway.chat.context.build_context', AsyncMock(return_value=''))
    async with api.db() as db:
        db.add(ChatMessage(conversation_id='chat-a', role='user', content='体液细胞那个你看看吧 做完给我个报告'))
        failed = ChatMessage(conversation_id='chat-a', role='assistant', content='AI 服务未能完整返回回答，请重试。')
        db.add(failed)
        await db.commit()
        anchor = failed.id

    decision = '我来准备这项数据分析。[NAVIGATE]{"type":"research","execute":true,"state":{"researchGoal":"核查体液细胞并保存报告","handoffReason":"Custom code","researchStandard":"standard","datasetIds":[],"references":[],"taskKind":"analysis","reportPolicy":"summary"}}[/NAVIGATE]'
    calls = 0
    async def stream(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            assert 'research task already exists' in args[0][0]['content']
        # The second retry emits prose only; server must still reattach the receipt.
        text = decision if calls == 1 else '可继续查看本轮已创建的研究任务。'
        for char in text:
            yield 'data: ' + json.dumps({'content': char}) + '\n\n'
        yield 'data: [DONE]\n\n'
    monkeypatch.setattr(chat, 'stream_ai_response', stream)
    identity = anchor
    for attempt in range(2):
        response = await api.client.post('/chat', headers={'X-Language': 'zh-CN'}, json={
            'conversation_id': 'chat-a', 'workspace_id': 'ws', 'regenerate_message_id': identity,
            'messages': [{'role': 'user', 'content': '体液细胞那个你看看吧 做完给我个报告'}],
        })
        assert response.status_code == 200, response.text
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ') and line[6:] != '[DONE]']
        started = next(e['session'] for e in events if e.get('type') == 'research_started')
        states = [e['handoff']['status'] for e in events if e.get('type') == 'research_handoff']
        assert states == (['preparing', 'submitting', 'accepted'] if attempt == 0 else ['submitting', 'accepted'])
        assert all('NAVIGATE' not in e.get('content', '') for e in events)
        identity = next(e['message_id'] for e in events if 'message_id' in e)
        async with api.db() as db:
            runs = (await db.scalars(select(AutoResearchSession).where(AutoResearchSession.chat_request_id == f'chat-message-{anchor}'))).all()
            assert len(runs) == 1
            assert runs[0].session_id == started['session_id'] and runs[0].status == 'queued'
            assert runs[0].recovery_metadata['task_kind'] == 'analysis'
            stored = await db.get(ChatMessage, identity)
            assert stored.extra_metadata['artifacts']['researchHandoff']['session_id'] == started['session_id']
            assert '[RESEARCH_RUN]' in stored.content and '[NAVIGATE]' not in stored.content
        reloaded = (await api.client.get('/conversations/chat-a')).json()
        active = next(m for m in reloaded['messages'] if m['role'] == 'assistant')
        assert active['metadata']['artifacts']['researchHandoff']['status'] == 'accepted'


@pytest.mark.parametrize('mode', ['discussion', 'read_only', 'failed'])
async def test_retry_handoff_never_disappears_when_dispatch_is_blocked(api, monkeypatch, mode):
    import json
    from gateway.routes import chat, autoresearch
    async with api.db() as db:
        original = ChatMessage(conversation_id='chat-a', role='assistant', content='Please retry')
        db.add(original)
        await db.commit()
        identity = original.id
    async def stream(*args, **kwargs):
        yield 'data: ' + json.dumps({'content': 'Preparing. [NAVIGATE]{"type":"research","execute":true,"state":{"researchGoal":"Analyze","handoffReason":"Custom code","researchStandard":"standard","datasetIds":[],"taskKind":"analysis","reportPolicy":"summary","references":[]}}[/NAVIGATE]'}) + '\n\n'
        yield 'data: [DONE]\n\n'
    monkeypatch.setattr(chat, 'stream_ai_response', stream)
    monkeypatch.setattr('gateway.chat.context.build_context', AsyncMock(return_value=''))
    create = AsyncMock(side_effect=HTTPException(429, 'Research queue is full'))
    monkeypatch.setattr(autoresearch, 'create_session', create)
    response = await api.client.post('/chat', json={
        'conversation_id': 'chat-a', 'workspace_id': 'ws', 'regenerate_message_id': identity,
        'execution_mode': 'read_only' if mode == 'read_only' else 'standard',
        'allow_research': mode != 'discussion',
        'messages': [{'role': 'user', 'content': 'Analyze'}],
    })
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ') and line[6:] != '[DONE]']
    handoffs = [e['handoff'] for e in events if e.get('type') == 'research_handoff']
    assert handoffs[-1]['status'] == 'failed' and handoffs[-1]['error']
    assert create.await_count == (1 if mode == 'failed' else 0)
    assert all('NAVIGATE' not in e.get('content', '') for e in events)
    async with api.db() as db:
        stored = await db.get(ChatMessage, next(e['message_id'] for e in events if 'message_id' in e))
        assert stored.extra_metadata['artifacts']['researchHandoff'] == handoffs[-1]
        assert stored.content.startswith('Preparing.')


async def test_research_shortcut_requires_a_brief_then_confirmation_and_keeps_settings(api, monkeypatch):
    import json
    from gateway.routes import chat, autoresearch
    prompts = []
    decision = '[NAVIGATE]{"type":"research","execute":true,"state":{"researchGoal":"Analyze BCFC and save report","handoffReason":"Custom code","researchStandard":"standard","datasetIds":[],"references":[],"taskKind":"analysis","reportPolicy":"summary"}}[/NAVIGATE]'
    async def stream(*args, **kwargs):
        prompts.append(args[0][0]['content'])
        yield 'data: ' + json.dumps({'content': 'Proposed analysis. ' + decision}) + '\n\n'
        yield 'data: [DONE]\n\n'
    monkeypatch.setattr(chat, 'stream_ai_response', stream)
    monkeypatch.setattr('gateway.chat.context.build_context', AsyncMock(return_value=''))
    create = AsyncMock(return_value={'session_id':'confirmed','status':'queued','chat_conversation_id':'chat-a'})
    monkeypatch.setattr(autoresearch, 'create_session', create)
    options = {'effort':'low','advanced':{'max_experiments':2},'allow_downloads':False,'selected_skill':'pathlab-research'}
    response = await api.client.post('/chat', json={
        'conversation_id':'chat-a','workspace_id':'ws','research_brief':True,'research_options':options,
        'messages':[{'role':'user','content':'Analyze BCFC and save a report'}],
    })
    assert response.status_code == 200, response.text
    create.assert_not_awaited()
    assert 'THIS TURN MUST NOT START EXECUTION' in prompts[-1]
    assert 'awaiting_confirmation' in response.text
    assert 'research_started' not in response.text
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ') and line[6:] != '[DONE]']
    brief_reply_id = next(e['message_id'] for e in events if 'message_id' in e)
    # Retrying the brief cannot bypass the first-turn execution restriction.
    retry = await api.client.post('/chat', json={
        'conversation_id':'chat-a','workspace_id':'ws','regenerate_message_id':brief_reply_id,
        'messages':[{'role':'user','content':'Analyze BCFC and save a report'}],
    })
    assert retry.status_code == 200 and 'awaiting_confirmation' in retry.text
    create.assert_not_awaited()
    response = await api.client.post('/chat', json={
        'conversation_id':'chat-a','workspace_id':'ws',
        'messages':[{'role':'assistant','content':'Please confirm the BCFC analysis plan.'}, {'role':'user','content':'Confirmed, start the analysis'}],
    })
    assert response.status_code == 200, response.text
    create.assert_awaited_once()
    assert 'Start only if the latest user message confirms' in prompts[-1]
    body = create.call_args.args[0]
    assert body.effort == 'low' and body.advanced.max_experiments == 2
    assert body.allow_downloads is False


async def test_ordinary_navigation_is_published_without_a_research_loading_card(api, monkeypatch):
    import json
    from gateway.routes import chat
    raw = 'Browse here. [NAVIGATE]{"target":"/datasets","buttonText":"View datasets"}[/NAVIGATE]'
    async def stream(*args, **kwargs):
        for char in raw:
            yield 'data: ' + json.dumps({'content':char}) + '\n\n'
        yield 'data: [DONE]\n\n'
    monkeypatch.setattr(chat, 'stream_ai_response', stream)
    monkeypatch.setattr('gateway.chat.context.build_context', AsyncMock(return_value=''))
    response = await api.client.post('/chat', json={'conversation_id':'chat-a','workspace_id':'ws','messages':[{'role':'user','content':'Browse datasets'}]})
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ') and line[6:] != '[DONE]']
    assert not any(e.get('type') == 'research_handoff' for e in events)
    assert next(e['content'] for e in events if e.get('type') == 'content_replace') == raw


async def test_real_file_receipt_is_saved_and_available_in_conversation(
    api, monkeypatch
):
    import json
    from gateway.routes import chat

    payload = (
        "[DELIVER_FILE]"
        + json.dumps(
            {
                "filename": "weather.md",
                "content": "# 天气报告\n\n来源：https://www.hko.gov.hk/",
            },
            ensure_ascii=False,
        )
        + "[/DELIVER_FILE]"
    )

    async def stream(*args, **kwargs):
        for i in range(0, len(payload), 7):
            yield "data: " + json.dumps({"content": payload[i : i + 7]}) + "\n\n"
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(chat, "stream_ai_response", stream)
    monkeypatch.setattr(
        "gateway.chat.context.build_context", AsyncMock(return_value="")
    )
    response = await api.client.post(
        "/chat",
        json={
            "conversation_id": "chat-a",
            "workspace_id": "ws",
            "messages": [{"role": "user", "content": "生成 md 天气报告"}],
        },
    )
    assert response.status_code == 200, response.text
    events = [
        json.loads(line[6:])
        for line in response.text.splitlines()
        if line.startswith("data: ") and line[6:] != "[DONE]"
    ]
    delivered = next(
        event["files"] for event in events if event.get("type") == "files_created"
    )
    assert delivered[0]["name"] == "weather.md"
    content = "".join(event.get("content", "") for event in events)
    assert "[DELIVER_FILE]" not in content and "# 天气报告" not in content
    assert "[FILE_DELIVERY]" in content
    file = await api.client.get(
        "/workbench/files/" + delivered[0]["id"] + "?workspace_id=ws"
    )
    assert file.json()["content"].startswith("# 天气报告")
    download = await api.client.get(
        "/workbench/files/"
        + delivered[0]["id"]
        + "/content?download=true&workspace_id=ws"
    )
    assert download.text.startswith("# 天气报告")
    async with api.db() as db:
        from sqlalchemy import select

        saved = await db.scalar(
            select(ChatMessage).where(ChatMessage.role == "assistant")
        )
        assert "FILE_DELIVERY" in saved.content
        assert saved.extra_metadata["delivered_files"][0]["id"] == delivered[0]["id"]


async def test_original_pdf_download_is_copied_and_receipted_without_path_leak(
    api, monkeypatch
):
    import json
    from gateway.routes import chat
    from backend.services.articles import reader as chat_pdf

    cache = api.root.parent / "pdf-cache"
    cache.mkdir()
    source = cache / "article.pdf"
    source.write_bytes(b"%PDF-1.4 original bytes")
    monkeypatch.setattr(chat_pdf, "_pdf_cache_dir", cache)

    async def stream(*args, **kwargs):
        yield (
            "data: "
            + json.dumps(
                {
                    "type": "article_download",
                    "path": str(source),
                    "title": "Original paper",
                    "url": "https://example.org/article",
                }
            )
            + "\n\n"
        )
        yield "data: " + json.dumps({"content": "PDF retrieved."}) + "\n\n"
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(chat, "stream_ai_response", stream)
    monkeypatch.setattr(
        "gateway.chat.context.build_context", AsyncMock(return_value="")
    )
    response = await api.client.post(
        "/chat",
        json={
            "conversation_id": "chat-a",
            "workspace_id": "ws",
            "messages": [{"role": "user", "content": "Download original PDF"}],
        },
    )
    assert str(source) not in response.text
    events = [
        json.loads(line[6:])
        for line in response.text.splitlines()
        if line.startswith("data: ") and line[6:] != "[DONE]"
    ]
    file = next(
        event["files"][0] for event in events if event.get("type") == "files_created"
    )
    assert file["name"] == "Original paper.pdf"
    source.unlink()
    download = await api.client.get(
        "/workbench/files/" + file["id"] + "/content?download=true&workspace_id=ws"
    )
    assert download.content == b"%PDF-1.4 original bytes"


@pytest.mark.parametrize("failure", ["invalid", "read_only", "interrupted"])
async def test_failed_delivery_never_saves_payload_or_fabricates_receipt(
    api, monkeypatch, failure
):
    import json
    from sqlalchemy import select
    from gateway.routes import chat

    payload = (
        "[DELIVER_FILE]"
        + json.dumps(
            {
                "filename": "../bad.md" if failure == "invalid" else "output.md",
                "content": "hidden file payload",
            }
        )
        + "[/DELIVER_FILE]"
    )

    async def stream(*args, **kwargs):
        yield "data: " + json.dumps({"content": payload}) + "\n\n"
        if failure == "interrupted":
            return  # Upstream ended without DONE; only cancellation text is durable.
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(chat, "stream_ai_response", stream)
    monkeypatch.setattr(
        "gateway.chat.context.build_context", AsyncMock(return_value="")
    )
    response = await api.client.post(
        "/chat",
        json={
            "conversation_id": "chat-a",
            "workspace_id": "ws",
            "execution_mode": "read_only" if failure == "read_only" else "standard",
            "messages": [{"role": "user", "content": "Save a file"}],
        },
    )
    assert response.status_code == 200, response.text
    assert "files_created" not in response.text
    assert "hidden file payload" not in response.text
    async with api.db() as db:
        saved = await db.scalar(
            select(ChatMessage).where(ChatMessage.role == "assistant")
        )
        assert saved.content.strip() and "FILE_DELIVERY" not in saved.content
        assert "hidden file payload" not in saved.content
        files = (
            await db.scalars(
                select(WorkbenchFile).where(WorkbenchFile.conversation_id == "chat-a")
            )
        ).all()
        assert not files


async def test_research_rejection_is_visible_and_not_replayed_by_history(
    api, monkeypatch
):
    import json
    from sqlalchemy import select
    from gateway.routes import chat, autoresearch

    async def stream(*args, **kwargs):
        yield (
            "data: "
            + json.dumps(
                {
                    "content": 'Preparing. [NAVIGATE]{"type":"research","execute":true,"state":{"researchGoal":"Calculate","handoffReason":"Custom code","researchStandard":"standard","datasetIds":[],"taskKind":"analysis","reportPolicy":"summary","references":[]}}[/NAVIGATE]'
                }
            )
            + "\n\n"
        )
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(chat, "stream_ai_response", stream)
    monkeypatch.setattr(
        "gateway.chat.context.build_context", AsyncMock(return_value="")
    )
    create = AsyncMock(side_effect=HTTPException(429, "internal capacity detail"))
    monkeypatch.setattr(autoresearch, "create_session", create)
    response = await api.client.post(
        "/chat",
        json={
            "conversation_id": "chat-a",
            "workspace_id": "ws",
            "messages": [{"role": "user", "content": "Calculate"}],
        },
    )
    assert "research_error" in response.text and "queue is full" in response.text
    assert 'internal capacity detail' not in response.text
    async with api.db() as db:
        saved = await db.scalar(
            select(ChatMessage).where(ChatMessage.role == "assistant")
        )
        assert "not started" in saved.content
        assert "NAVIGATE" not in saved.content and "RESEARCH_RUN" not in saved.content
    assert create.await_count == 1
