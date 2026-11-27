"""Bounded, source-attributed conversation excerpts; never load a whole transcript."""

import json
import re

from fastapi import HTTPException
from sqlalchemy import case, exists, func, or_, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import aliased

from backend.database.models import (
    AutoResearchSession,
    ChatConversation,
    ChatMessage,
    StorageTask,
)

MAX_CONTEXT_CHARS = 10000


def conversation_query(user, workspace_id):
    query = select(ChatConversation.conversation_id.label('id'), ChatConversation.title.label('name'),
                   ChatConversation.updated_at.label('revision'))
    if not user.is_admin():
        query = query.where(ChatConversation.user_id == str(user.id))
    if workspace_id:
        query = query.where(ChatConversation.workspace_id == workspace_id)
    return query.where(~exists(select(StorageTask.task_id).where(
        StorageTask.task_type == 'chat_delete',
        StorageTask.params['conversation_id'].as_string() == ChatConversation.conversation_id,
        StorageTask.status != 'completed')))


async def linked_research_references(db, user, workspace_id, conversation_ids):
    """Only directly linked, currently authorized research; no transitive references."""
    from .workbench import resource_query
    from .workspaces import resolve_scope
    scope = await resolve_scope(db, user, workspace_id)
    allowed = conversation_query(user, workspace_id).where(ChatConversation.conversation_id.in_(conversation_ids)).subquery()
    query, _, _ = resource_query(user, scope, 'research')
    rows = (await db.execute(query.where(AutoResearchSession.chat_conversation_id.in_(select(allowed.c.id)))
        .order_by(AutoResearchSession.updated_at.desc()).limit(32))).mappings().all()
    return [{'kind': 'research', 'id': row['id']} for row in rows]


def visible_statement(conversation_id):
    newer = aliased(ChatMessage)
    return select(ChatMessage.id, ChatMessage.role).where(
        ChatMessage.conversation_id == conversation_id,
        ChatMessage.role.in_(['user', 'assistant']),
        ChatMessage.extra_metadata['superseded_by_regeneration'].as_string().is_(None),
        or_(ChatMessage.variant_group_id.is_(None),
            ChatMessage.is_active_variant.is_(True) & ~exists(select(newer.id).where(
                newer.conversation_id == conversation_id,
                newer.variant_group_id == ChatMessage.variant_group_id,
                newer.is_active_variant.is_(True), newer.id > ChatMessage.id,
                newer.extra_metadata['superseded_by_regeneration'].as_string().is_(None)))),
    )


def clean_excerpt(value):
    value = re.sub(r'\[(NAVIGATE|CONFIG|SEARCH_FILES|LOAD_SKILL|LOAD_CONNECTOR)\][\s\S]*?(?:\[/\1\]|$)', '', value, flags=re.IGNORECASE)
    value = re.sub(r'data:[^\s;]+;base64,[A-Za-z0-9+/=]*', '[attachment omitted]', value)
    return value.strip()


def query_terms(query):
    terms = []
    for word in re.findall(r'[a-zA-Z0-9_]{3,}|[\u4e00-\u9fff]{2,}', query.casefold()[:2000]):
        # CJK phrases may be unsegmented; bounded bigrams provide lexical retrieval.
        parts = [word] if not re.fullmatch(r'[\u4e00-\u9fff]{4,}', word) else [word[i:i+2] for i in range(len(word)-1)]
        for part in parts:
            if part not in terms and part not in {'the', 'this', 'that', 'with', 'from', 'please', '分析', '这个', '请问'}:
                terms.append(part)
    return terms[:8]


async def conversation_excerpt(db, user, workspace_id, conversation_id, query='', limit=MAX_CONTEXT_CHARS):
    limit = min(limit, MAX_CONTEXT_CHARS)
    row = (await db.execute(conversation_query(user, workspace_id).where(
        ChatConversation.conversation_id == conversation_id))).mappings().first()
    if not row:
        raise HTTPException(404, 'Referenced conversation is no longer available in this workspace')
    if db.bind.dialect.name == 'postgresql':
        from sqlalchemy import text
        await db.execute(text("SET LOCAL statement_timeout = '2000ms'"))
    base = visible_statement(conversation_id)
    total = await db.scalar(select(func.count()).select_from(base.subquery()))
    projection = base.add_columns(func.substr(ChatMessage.content, 1, 1600).label('text'),
                                  func.length(ChatMessage.content).label('length'))
    first = (await db.execute(projection.where(ChatMessage.role == 'user').order_by(ChatMessage.id).limit(1))).mappings().first()
    recent = (await db.execute(projection.order_by(ChatMessage.id.desc()).limit(8))).mappings().all()
    corrections = (await db.execute(projection.where(ChatMessage.role == 'user')
                                   .order_by(ChatMessage.id.desc()).limit(2))).mappings().all()
    relevant = []
    relevance_limited = False
    terms = query_terms(query)
    if terms:
        hits = [ChatMessage.content.icontains(term, autoescape=True) for term in terms]
        position = func.strpos if db.bind.dialect.name == 'postgresql' else func.instr
        start = case(*[(hit, position(func.lower(ChatMessage.content), term)) for hit, term in zip(hits, terms)], else_=1)
        offset = case((start > 300, start - 300), else_=1)
        statement = base.add_columns(func.substr(ChatMessage.content, offset, 1600).label('text'),
                                     func.length(ChatMessage.content).label('length'))
        rank = sum(case((hit, 1), else_=0) for hit in hits)
        try:
            async with db.begin_nested():
                relevant = (await db.execute(statement.where(or_(*hits)).order_by(rank.desc(), ChatMessage.id.desc()).limit(6))).mappings().all()
        except DBAPIError as error:
            if getattr(error.orig, 'sqlstate', None) != '57014':
                raise
            # A very large transcript must not prevent the current chat from running.
            relevance_limited = True
    research_query = select(
        AutoResearchSession.session_id, AutoResearchSession.status,
        func.substr(AutoResearchSession.final_report, 1, 1800).label('findings'),
    ).where(AutoResearchSession.chat_conversation_id == conversation_id,
            AutoResearchSession.recovery_metadata['delete_requested'].as_boolean().is_not(True))
    if not user.is_admin():
        research_query = research_query.where(AutoResearchSession.user_id == str(user.id))
    if workspace_id:
        research_query = research_query.where(AutoResearchSession.recovery_metadata['workspace_id'].as_string() == workspace_id)
    research = (await db.execute(research_query.order_by(AutoResearchSession.updated_at.desc()).limit(2))).mappings().all()
    result = {'conversation_id': conversation_id, 'title': (row['name'] or '')[:120],
              'selection': 'Extractive: first user goal, recent turns, query-matching excerpts and linked research findings. Not a complete transcript or a generated factual summary.',
              'total_visible_messages': total, 'included_messages': 0, 'messages': [], 'research_findings': [],
              'relevance_search_limited': relevance_limited, 'truncated': True}
    seen = set()
    # Preserve the original goal and latest corrections, then add relevant older context.
    ordered = [(first, 'original_goal')] if first else []
    ordered += [(r, 'recent_user') for r in corrections]
    ordered += [(r, 'recent') for r in recent[:2]]
    ordered += [(r, 'query_match') for r in relevant]
    ordered += [(r, 'recent') for r in recent[2:]]
    for entry, reason in ordered:
        if entry['id'] in seen:
            continue
        seen.add(entry['id'])
        text = clean_excerpt(entry['text'])
        if not text:
            continue
        item = {'message_id': entry['id'], 'role': entry['role'], 'selection': reason,
                'text': text, 'truncated': entry['length'] > len(entry['text'])}
        available = limit - min(2000, limit // 4) - len(json.dumps(result, ensure_ascii=False)) - 160
        if available < 100:
            break
        if len(item['text']) > available:
            item.update(text=item['text'][:available], truncated=True)
        result['messages'].append(item)
        if len(json.dumps(result, ensure_ascii=False)) > limit - 64:
            result['messages'].pop()
            break
    result['messages'].sort(key=lambda m: m['message_id'])
    for entry in research:
        result['research_findings'].append({**dict(entry), 'findings': clean_excerpt(entry['findings'] or '')})
        if len(json.dumps(result, ensure_ascii=False)) > limit - 64:
            result['research_findings'].pop()
    result['included_messages'] = len(result['messages'])
    result['truncated'] = total > len(result['messages']) or any(m['truncated'] for m in result['messages'])
    return result


async def expand_conversations(db, user, workspace_id, items, query=''):
    count = sum(item['kind'] == 'conversation' for item in items)
    if not count:
        return items
    allowance = min(MAX_CONTEXT_CHARS, 14000 // count)
    result = []
    for item in items:
        if item['kind'] == 'conversation':
            item = {**item, 'conversation_context': await conversation_excerpt(
                db, user, workspace_id, item['id'], query, allowance)}
        result.append(item)
    return result
