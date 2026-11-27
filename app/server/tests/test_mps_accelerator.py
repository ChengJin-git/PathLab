import asyncio
import sys
import os
from unittest.mock import Mock
import pytest
import torch
from backend.common import accelerator, gpu_utils
from task_worker.gpu_scheduler import GpuScheduler


def test_mps_selection_and_conservative_memory(monkeypatch):
    monkeypatch.setattr(accelerator, 'mps_available', lambda: True)
    monkeypatch.setattr(gpu_utils, 'mps_available', lambda: True)
    monkeypatch.setattr(torch.cuda, 'is_available', lambda: False)
    monkeypatch.setattr(torch.mps, 'recommended_max_memory', lambda: 8 * 1024**3)
    monkeypatch.setattr(torch.mps, 'driver_allocated_memory', lambda: 1024**3)
    assert str(gpu_utils.get_optimal_device()) == 'mps'
    assert gpu_utils.get_gpu_count() == 1
    info = gpu_utils.get_all_gpu_info()[0]
    assert info['device'] == 'mps'
    assert 0 < info['free_mb'] <= info['total_mb'] <= 8 * 1024 * 0.7
    cuda_cache = Mock(side_effect=AssertionError('No CUDA calls on MPS'))
    monkeypatch.setattr(torch.cuda, 'empty_cache', cuda_cache)
    metal_cache = Mock(); monkeypatch.setattr(torch.mps, 'empty_cache', metal_cache)
    accelerator.empty_cache(); metal_cache.assert_called_once()


@pytest.mark.asyncio
async def test_scheduler_returns_mps_device_and_releases_lease():
    scheduler = GpuScheduler(lambda: [{'index': 0, 'device': 'mps', 'free_mb': 5000, 'total_mb': 6000}], lambda: {})
    try:
        device = await asyncio.wait_for(scheduler.acquire('training', 'fit', 1000), 3)
        assert device == 'mps'
        assert scheduler.details()['training:fit']['device'] == 'mps'
        scheduler.release_task('training')
        assert not scheduler.leases
    finally: await scheduler.stop()


@pytest.mark.skipif(not (sys.platform == 'darwin' and torch.backends.mps.is_available()), reason='Requires real Apple Metal GPU')
def test_real_mps_abmil_training_and_reload(tmp_path):
    from backend.ai.aggregators.abmil import ABMILAggregator
    try:
        assert (torch.ones(2, device='mps') + 1).sum().item() == 4
    except RuntimeError as exc:
        if os.environ.get('GITHUB_ACTIONS') == 'true':
            pytest.skip(f'Hosted macOS runner exposes no usable Metal compute device: {exc}')
        raise
    model = ABMILAggregator(16, 2, hidden_dim=32, attention_dim=8).to('mps')
    features = torch.randn(12, 16, device='mps')
    target = torch.tensor([1], device='mps')
    optimizer = torch.optim.Adam(model.parameters(), lr=0.01)
    for _ in range(5):
        optimizer.zero_grad()
        logits, _ = model(features)
        loss = torch.nn.functional.cross_entropy(logits, target)
        loss.backward(); optimizer.step()
    torch.mps.synchronize()
    assert torch.isfinite(loss)
    torch.save(model.state_dict(), tmp_path / 'model.pt')
    copy = ABMILAggregator(16, 2, hidden_dim=32, attention_dim=8).to('mps')
    copy.load_state_dict(torch.load(tmp_path / 'model.pt', map_location='mps', weights_only=True))
    assert torch.allclose(model(features)[0], copy(features)[0])
