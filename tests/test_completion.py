from pathlib import Path
from types import SimpleNamespace

from kage.main import _complete_run_ids, _complete_task_names
from kage.runs import RunRecord


def test_complete_task_names_collapses_duplicates_and_filters(mocker, tmp_path: Path):
    proj_a = tmp_path / "proj-a"
    proj_b = tmp_path / "proj-b"

    mocker.patch("kage.scheduler.get_projects", return_value=[proj_a, proj_b])

    fake_tasks = {
        proj_a: [
            (
                proj_a / ".kage/tasks/nightly.md",
                SimpleNamespace(task=SimpleNamespace(name="Nightly Research")),
            ),
            (
                proj_a / ".kage/tasks/shared.md",
                SimpleNamespace(task=SimpleNamespace(name="Shared Task")),
            ),
        ],
        proj_b: [
            (
                proj_b / ".kage/tasks/shared.md",
                SimpleNamespace(task=SimpleNamespace(name="Shared Task")),
            )
        ],
    }

    mocker.patch(
        "kage.parser.load_project_tasks", side_effect=lambda proj: fake_tasks[proj]
    )

    items = _complete_task_names(None, [], "sh")

    assert items == [("Shared Task", "2 projects")]


def test_complete_run_ids_returns_recent_matching_runs(mocker):
    runs = [
        RunRecord(
            id="abcd1234-0000-0000-0000-000000000001",
            project_path="/tmp/proj-a",
            task_name="Nightly Research",
            run_at="2026-03-14T00:00:00+00:00",
            status="SUCCESS",
        ),
        RunRecord(
            id="beef5678-0000-0000-0000-000000000002",
            project_path="/tmp/proj-b",
            task_name="Shared Task",
            run_at="2026-03-14T00:01:00+00:00",
            status="FAILED",
        ),
    ]
    mocker.patch("kage.runs.list_runs", return_value=runs)

    items = _complete_run_ids(None, [], "ab")

    assert items == [
        ("abcd1234-0000-0000-0000-000000000001", "Nightly Research [SUCCESS] proj-a")
    ]
