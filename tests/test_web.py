from pathlib import Path
from types import SimpleNamespace

from kage.config import CommandDef, GlobalConfig, ProviderConfig
from kage.parser import TaskDef
from kage.web import INDEX_HTML, get_config_api


def test_get_config_api_includes_compiled_state(mocker, tmp_path: Path):
    project_dir = tmp_path / "proj"
    task_file = project_dir / ".kage" / "tasks" / "nightly.md"
    task_file.parent.mkdir(parents=True)

    cfg = GlobalConfig(
        default_ai_engine="codex",
        commands={"codex": CommandDef(template=["codex", "exec", "{prompt}"])},
        providers={"codex": ProviderConfig(command="codex")},
    )
    task = TaskDef(name="Nightly", cron="* * * * *", prompt="hello")

    mocker.patch(
        "kage.web.get_global_config",
        side_effect=lambda workspace_dir=None: cfg,
    )
    mocker.patch("kage.scheduler.get_projects", return_value=[project_dir])
    mocker.patch(
        "kage.parser.load_project_tasks",
        return_value=[(task_file, SimpleNamespace(task=task))],
    )
    mocker.patch(
        "kage.compiler.compiled_task_indicator",
        return_value={
            "state": "stale",
            "label": "stale",
            "path": str(task_file.with_suffix(".lock.sh")),
            "exists": True,
            "is_fresh": False,
            "needs_compile": True,
        },
    )

    payload = get_config_api()

    assert payload["tasks"][0]["compiled_state"] == "stale"
    assert payload["tasks"][0]["compiled_path"].endswith(".lock.sh")
    assert payload["tasks"][0]["compiled_needs_compile"] is True
    assert payload["tasks"][0]["provider_display"] == "codex (Inherited)"
    assert payload["tasks"][0]["type_display"] == "Prompt (Compiled)"
    assert payload["tasks"][0]["project_name"] == "proj"


def test_connector_setup_guides_escape_backticks_in_embedded_js():
    assert r"\`bot\`" in INDEX_HTML
    assert r"\`\`\`toml" in INDEX_HTML
    assert r"\`/newbot\`" in INDEX_HTML
