"""Side questions read evidence without steering or persisting in research history."""
# ruff: noqa: PLC0414 -- shared pytest fixture exports.

from copy import deepcopy
from unittest.mock import AsyncMock

from test_research_privacy_and_refinement import research_api as research_api

from backend.autoresearch.engine import store
from backend.autoresearch.engine.reference_files import research_file_view
from backend.services import research_questions


async def test_side_question_reads_selected_record_and_never_mutates_live_session(research_api,monkeypatch):
    api=research_api
    await store.update('alice',status='running',meta={'finish_requested':False,'commands':[{'id':'kept','kind':'message','text':'Existing instruction'}]})
    before=await store.get('alice'); meta=deepcopy(before.recovery_metadata)
    events_before=deepcopy(await store.events('alice'))
    answer=AsyncMock(return_value='The saved evidence is exploratory; the experiment is continuing.')
    monkeypatch.setattr(research_questions,'answer_question',answer)
    response=await api.client.post('/workbench/research/alice/questions',json={'question':'Why this experiment?','event_seq':1,'language':'en-US'})
    assert response.status_code==200,response.text
    assert response.json()['research_unchanged']
    context=answer.await_args.args[0]
    assert context['selected_update']['text']=='alice private conversation'
    assert 'bob private' not in str(context)
    after=await store.get('alice')
    assert after.recovery_metadata==meta and after.status=='running'
    assert await store.events('alice')==events_before
    assert not await store.jobs('alice')


async def test_questions_reject_other_users_and_foreign_events_but_allow_admin(research_api,monkeypatch):
    api=research_api
    answer=AsyncMock(return_value='Read-only answer')
    monkeypatch.setattr(research_questions,'answer_question',answer)
    assert (await api.client.post('/workbench/research/bob/questions',json={'question':'Reveal private results'})).status_code==403
    answer.assert_not_awaited()
    assert (await api.client.post('/workbench/research/alice/questions',json={'question':'Explain','event_seq':999})).status_code==404
    api.actor.user=api.users['admin']
    response=await api.client.post('/workbench/research/bob/questions',json={'question':'Explain','event_seq':1})
    assert response.status_code==200
    assert answer.await_args.args[0]['selected_update']['text']=='bob private conversation'


async def test_model_failure_leaves_research_running(research_api,monkeypatch):
    await store.update('alice',status='running')
    before=deepcopy((await store.get('alice')).recovery_metadata)
    monkeypatch.setattr(research_questions,'answer_question',AsyncMock(side_effect=TimeoutError()))
    result=await research_api.client.post('/workbench/research/alice/questions',json={'question':'Explain this'})
    assert result.status_code==503
    after=await store.get('alice')
    assert after.status=='running' and after.recovery_metadata==before


def test_research_file_view_is_filtered_refreshable_and_does_not_follow_links(tmp_path):
    source=tmp_path/'old';view=tmp_path/'view';source.mkdir()
    (source/'runs/r/output').mkdir(parents=True)
    (source/'runs/r/output/result.json').write_text('{"auc":0.8}')
    (source/'runs/r/source').mkdir();(source/'runs/r/source/train.py').write_text('print("method")')
    (source/'runs/r/source/opencode.json').write_text('private config')
    (source/'.env').write_text('private credentials')
    (source/'outside').symlink_to(tmp_path)
    (source/'result-link').symlink_to(source/'runs/r/output/result.json')
    assert research_file_view(source,view)==2
    assert (view/'runs/r/output/result.json').read_text()=='{"auc":0.8}'
    assert not (view/'.env').exists() and not (view/'outside').exists() and not (view/'result-link').exists()
    (source/'runs/r/output/result.json').unlink()
    assert research_file_view(source,view)==1
    assert not (view/'runs/r/output/result.json').exists()
