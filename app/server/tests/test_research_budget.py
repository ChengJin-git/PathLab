from backend.autoresearch.engine.effort import EFFORT_BUDGETS, MAX_EXPERIMENTS
from backend.autoresearch.engine.request import AdvancedResearch
from backend.autoresearch.engine.study_contract import StudyStage


def test_every_effort_budget_fits_the_shared_ceiling():
    granted = [attempts for tiers in EFFORT_BUDGETS.values() for attempts, _ in tiers.values()]
    assert MAX_EXPERIMENTS == max(granted)


def test_largest_budget_is_valid_for_launch_and_study_stages():
    assert AdvancedResearch(max_experiments=MAX_EXPERIMENTS).max_experiments == MAX_EXPERIMENTS
    stage = StudyStage(
        id="validation",
        kind="validation",
        max_experiments=MAX_EXPERIMENTS,
        max_job_seconds=3600,
        advance_when="gain measured",
        stop_when="budget spent",
    )
    assert stage.max_experiments == MAX_EXPERIMENTS
