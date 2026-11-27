"""Cold-import checks: shared capabilities must be usable without the HTTP app."""

import subprocess
import sys

import pytest


@pytest.mark.parametrize("module", [
    "backend.services.articles.reader",
    "backend.services.web_search",
    "backend.common.analysis_state",
    "backend.common.service_health",
    "backend.autoresearch.engine.tools",
    "task_worker.recovery",
])
def test_shared_capability_does_not_initialize_gateway(module):
    subprocess.run(
        [sys.executable, "-c", f"import {module}; import sys; "
         "assert not any(name == 'gateway' or name.startswith('gateway.') for name in sys.modules)"],
        check=True, capture_output=True, text=True, timeout=60,
    )


def test_individual_route_does_not_initialize_unrelated_routes():
    subprocess.run(
        [sys.executable, "-c", "import gateway.routes.settings; import sys; "
         "assert 'gateway.routes.chat' not in sys.modules; "
         "assert 'gateway.routes.results' not in sys.modules; "
         "assert 'task_worker.task_queue' not in sys.modules"],
        check=True, capture_output=True, text=True, timeout=60,
    )
