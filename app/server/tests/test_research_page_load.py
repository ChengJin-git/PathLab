"""Research pages load bounded history: an incremental activity index and metric previews."""

from backend.autoresearch.engine import store
from backend.autoresearch.engine.metric_preview import (
    PREVIEW_KEYS,
    metric_preview,
    preview_experiment,
)
from backend.database.models import AutoResearchEvent
from sqlalchemy import delete
from test_manuscripts import api as api  # noqa: PLC0414 -- shared SQLite fixture.


def message(identity, text):
    return {'kind': 'message', 'message': {'id': identity, 'type': 'assistant', 'text': text}}


async def test_activity_index_extends_merges_snapshots_and_rebuilds_replaced_history(api):
    await store.update('alice', event=message('m1', 'first draft'))
    assert [item['message']['text'] for item in (await store.activity('alice'))['items']] == ['first draft']
    await store.update('alice', event=message('m1', 'final answer'))
    await store.update('alice', event={'kind': 'command', 'command_id': 'c1', 'text': 'Run the baseline'})
    items = (await store.activity('alice'))['items']
    assert [item.get('message', {}).get('text') or item.get('text') for item in items] == ['final answer', 'Run the baseline']
    first = items[0]['activity_seq']
    assert (await store.activity('alice', before=items[1]['activity_seq']))['items'][0]['activity_seq'] == first
    async with api.sessions() as db:
        await db.execute(delete(AutoResearchEvent).where(AutoResearchEvent.session_id == 'alice'))
        await db.commit()
    await store.update('alice', event=message('m2', 'new history'))
    assert [item['message']['text'] for item in (await store.activity('alice'))['items']] == ['new history']


async def test_activity_pages_keep_anchors_beyond_the_recent_window(api):
    await store.update('alice', event={'kind': 'command', 'command_id': 'goal', 'text': 'Find a publishable method'})
    for index in range(6):
        await store.update('alice', event={'kind': 'job', 'job_id': f'job-{index}', 'status': 'completed'})
    page = await store.activity('alice', limit=3, context=True)
    assert [item.get('job_id') for item in page['items'][-3:]] == ['job-3', 'job-4', 'job-5']
    assert page['items'][0]['text'] == 'Find a publishable method'
    assert page['next_before'] == page['items'][-3]['activity_seq']


def test_metric_preview_keeps_every_displayed_key_in_order():
    metrics = {'loss': 0.4, 'note': 'fold summary'}
    metrics.update({f'case.{index}.auc': index / 1000 for index in range(500)})
    metrics.update({'test.auc': 0.91, 'primary.delta.auroc': 0.03})
    preview = metric_preview(metrics, primary='primary.delta.auroc')
    assert len(preview) <= PREVIEW_KEYS
    assert {'loss', 'note', 'test.auc', 'primary.delta.auroc'} <= set(preview)
    assert list(preview) == [key for key in metrics if key in preview]
    assert metric_preview({'auc': 0.8}) == {'auc': 0.8}
    run = preview_experiment({'run_id': 'r', 'metrics': metrics,
                              'config': {'config': {'study_evaluation': {'metric': 'primary.delta.auroc'}}}})
    assert run['metrics_total'] == len(metrics) and 'primary.delta.auroc' in run['metrics']
