import typer
from click.shell_completion import CompletionItem
from . import config as config_mod, daemon, db
from typing import Optional
from importlib import metadata
from pathlib import Path
import json
import time
from typer import completion as typer_completion

app = typer.Typer(
    help="kage - AI Native Cron Task Runner",
    add_completion=True,
)

cron_app = typer.Typer(help="OS-level scheduler (cron/launchd) management")
app.add_typer(cron_app, name="cron")

task_app = typer.Typer(help="Manage kage tasks")
app.add_typer(task_app, name="task")


@task_app.callback()
def task_app_callback():
    """Task commands are scoped to the current agent (if running inside one)."""
    pass


def _guard_task_command_for_project(project_path: Optional[str | Path]) -> None:
    """現 agent が想定 project を所有するか検証。人間は skip。"""
    from .agent import assert_task_command_allowed
    from .config import get_global_config

    config = get_global_config()
    p = Path(project_path).resolve() if project_path else Path.cwd().resolve()
    assert_task_command_allowed(config, p)


def _guard_task_command_by_name(task_name: str | None) -> None:
    """task 名から属する project を解決し agent 配下か検証。"""
    if task_name is None:
        return
    from .config import KAGE_PROJECTS_LIST, get_global_config

    config = get_global_config()
    for line in (
        KAGE_PROJECTS_LIST.read_text(encoding="utf-8").splitlines()
        if KAGE_PROJECTS_LIST.exists()
        else []
    ):
        proj = Path(line.strip())
        if not proj.exists():
            continue
        tasks_dir = proj / ".kage" / "tasks"
        if not tasks_dir.exists():
            continue
        # task 名でファイルを探索
        candidates = list(tasks_dir.glob(f"{task_name}.*"))
        if candidates:
            from .agent import assert_task_command_allowed

            assert_task_command_allowed(config, proj.resolve())
            return


project_app = typer.Typer(help="Manage registered projects")
app.add_typer(project_app, name="project")

connector_app = typer.Typer(
    help="Manage chat connectors (Discord, Slack, Telegram, etc.), including realtime chat, artifact uploads and incoming attachment downloads"
)
app.add_typer(connector_app, name="connector")

migrate_app = typer.Typer(help="Run install/data migrations")
app.add_typer(migrate_app, name="migrate")

quest_app = typer.Typer(
    help="Manage quests: event-driven, team-based mind-map lifecycles that run alongside cron tasks"
)
app.add_typer(quest_app, name="quest")

runs_app = typer.Typer(
    help="View and manage execution runs",
    invoke_without_command=True,
)
app.add_typer(runs_app, name="runs")

completion_app = typer.Typer(
    help="Shell completion helpers, including task and run ID suggestions"
)
app.add_typer(completion_app, name="completion")

agent_app = typer.Typer(
    help="Manage agents (independent personas bound to connectors and projects)"
)
app.add_typer(agent_app, name="agent")

memory_app = typer.Typer(
    help="Manage agent memory: durable topic-keyed notes scoped per agent"
)
app.add_typer(memory_app, name="memory")


def _completion_script(shell: str) -> str:
    target_shell = shell.lower().strip()
    if target_shell not in ("bash", "zsh"):
        raise typer.BadParameter("shell must be one of: bash, zsh")
    return typer_completion.get_completion_script(
        prog_name="kage",
        complete_var="_KAGE_COMPLETE",
        shell=target_shell,
    )


def _append_source_line_if_missing(rc_file: Path, source_line: str) -> bool:
    rc_file.parent.mkdir(parents=True, exist_ok=True)
    if not rc_file.exists():
        rc_file.write_text("", encoding="utf-8")
    content = rc_file.read_text(encoding="utf-8")
    if source_line in content:
        return False
    with rc_file.open("a", encoding="utf-8") as f:
        if content and not content.endswith("\n"):
            f.write("\n")
        f.write(source_line + "\n")
    return True


@completion_app.command("show")
def completion_show(
    shell: str = typer.Argument(..., help="Target shell: bash or zsh"),
):
    """Print a completion script that also supports task/run argument suggestions."""
    typer.echo(_completion_script(shell))


@completion_app.command("install")
def completion_install(
    shell: str = typer.Argument(..., help="Target shell: bash or zsh"),
):
    """Install completion script and update shell rc file."""
    target_shell = shell.lower().strip()
    script = _completion_script(target_shell)

    comp_dir = Path.home() / ".kage" / "completions"
    comp_dir.mkdir(parents=True, exist_ok=True)
    script_path = comp_dir / f"kage.{target_shell}"
    script_path.write_text(script, encoding="utf-8")

    if target_shell == "bash":
        rc_file = Path.home() / ".bashrc"
    else:
        rc_file = Path.home() / ".zshrc"
    source_line = f'source "{script_path}"'
    appended = _append_source_line_if_missing(rc_file, source_line)

    typer.echo(f"Installed completion script: {script_path}")
    if appended:
        typer.echo(f"Updated shell config: {rc_file}")
    else:
        typer.echo(f"Shell config already contains source line: {rc_file}")
    typer.echo("Reload your shell: exec $SHELL -l")


def _resolve_version() -> str:
    for pkg in ("kage-ai", "kage"):
        try:
            return metadata.version(pkg)
        except metadata.PackageNotFoundError:
            continue
    return "unknown"


def _version_callback(value: bool):
    if value:
        typer.echo(_resolve_version())
        raise typer.Exit()


def _project_short_name(project_path: str) -> str:
    return Path(project_path).name or project_path


def _effective_task_provider(task, merged_cfg) -> tuple[str | None, bool]:
    explicit_provider = task.provider or (task.ai.engine if task.ai else None)
    effective_provider = explicit_provider or merged_cfg.default_ai_engine
    return effective_provider, bool(effective_provider and not explicit_provider)


def _task_type_label(task, compiled_state: str | None = None) -> str:
    if task.prompt and not task.command:
        if compiled_state in {"fresh", "stale"}:
            return "Prompt (Compiled)"
        return "Prompt"
    return "Shell"


def _suspension_table_value(status) -> str:
    if status.is_invalid:
        return "[red]invalid[/red]"
    if status.is_suspended and status.until:
        return f"[yellow]until {status.until.isoformat(timespec='seconds')}[/yellow]"
    if status.raw_until:
        return "[dim]expired[/dim]"
    return "-"


def _execution_result_message(result) -> str:
    result_value = getattr(result, "value", str(result))
    messages = {
        "skipped_inactive": "task is inactive",
        "skipped_suspended": "task is suspended",
        "skipped_concurrency": "task is already running",
        "failed_config": "task configuration is incomplete",
    }
    return messages.get(result_value, "task did not start")


def _task_completion_items(incomplete: str) -> list[CompletionItem]:
    from .parser import load_project_tasks
    from .scheduler import get_projects

    task_projects: dict[str, set[str]] = {}
    needle = incomplete.lower()

    try:
        projects = get_projects()
    except Exception:
        return []

    for proj_dir in projects:
        try:
            tasks = load_project_tasks(proj_dir)
        except Exception:
            continue
        for _task_file, local_task in tasks:
            task_name = local_task.task.name
            if not task_name:
                continue
            if needle and needle not in task_name.lower():
                continue
            task_projects.setdefault(task_name, set()).add(str(proj_dir))

    items: list[CompletionItem] = []
    for task_name, project_paths in sorted(task_projects.items()):
        if len(project_paths) == 1:
            project_hint = _project_short_name(next(iter(project_paths)))
        else:
            project_hint = f"{len(project_paths)} projects"
        items.append(CompletionItem(task_name, help=project_hint))
    return items


def _run_id_completion_items(incomplete: str, limit: int = 50) -> list[CompletionItem]:
    from .runs import list_runs

    needle = incomplete.lower()
    items: list[CompletionItem] = []
    try:
        records = list_runs(limit=limit)
    except Exception:
        return []

    for record in records:
        run_id = record.id
        if needle and not run_id.lower().startswith(needle):
            continue
        summary = f"{record.task_name} [{record.status}]"
        if record.project_path:
            summary += f" {_project_short_name(record.project_path)}"
        items.append(CompletionItem(run_id, help=summary))
    return items


def _complete_task_names(ctx, args, incomplete: str):
    del ctx, args
    return [
        (item.value, item.help or "") for item in _task_completion_items(incomplete)
    ]


def _complete_run_ids(ctx, args, incomplete: str):
    del ctx, args
    return [
        (item.value, item.help or "") for item in _run_id_completion_items(incomplete)
    ]


@app.callback()
def app_callback(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        help="Show version and exit.",
        is_eager=True,
        callback=_version_callback,
    ),
):
    """kage CLI."""
    return None


def _run_status_markup(status: str) -> str:
    if status == "SUCCESS":
        return "[green]SUCCESS[/green]"
    if status == "FAILED":
        return "[red]FAILED[/red]"
    if status == "RUNNING":
        return "[yellow]RUNNING[/yellow]"
    if status == "STOPPED":
        return "[yellow]STOPPED[/yellow]"
    return status


def _print_runs(
    records,
    json_output: bool = False,
    absolute_time: bool = False,
):
    if json_output:
        typer.echo(
            json.dumps(
                [record.to_dict() for record in records], ensure_ascii=False, indent=2
            )
        )
        return

    from rich.console import Console
    from rich.table import Table
    from .runs import format_local_timestamp, format_relative_timestamp

    is_ja = _is_ja()

    if not records:
        typer.echo("実行履歴がありません。" if is_ja else "No runs found.")
        return

    console = Console()
    table = Table(
        show_header=True,
        header_style="bold magenta",
        padding=(0, 1),
    )
    table.add_column("日時" if is_ja else "When", style="dim", no_wrap=True)
    table.add_column("状態" if is_ja else "Status", no_wrap=True)
    table.add_column("タスク" if is_ja else "Task", style="bold")
    table.add_column("Project", style="dim")
    table.add_column("所要時間" if is_ja else "Duration", no_wrap=True)
    table.add_column("概要" if is_ja else "Summary")

    for record in records:
        payload = record.to_dict()
        when = (
            format_local_timestamp(record.run_at)
            if absolute_time
            else format_relative_timestamp(record.run_at, is_ja=is_ja)
        )
        table.add_row(
            when,
            _run_status_markup(record.status),
            record.task_name,
            payload["project_short"],
            payload["duration_display"],
            record.output_summary or "",
        )

    console.print(table)


def _print_run_details(record, json_output: bool = False):
    from .runs import format_local_timestamp, load_run_metadata

    metadata = load_run_metadata(record)
    connector_meta = metadata.get("connector", {}) if isinstance(metadata, dict) else {}
    artifacts_meta = metadata.get("artifacts", {}) if isinstance(metadata, dict) else {}
    incoming_meta = (
        artifacts_meta.get("incoming", {}) if isinstance(artifacts_meta, dict) else {}
    )

    if json_output:
        payload = record.to_dict()
        payload["metadata"] = metadata
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    details = [
        ("id", record.id),
        ("task", record.task_name),
        ("project", record.project_path),
        ("working_dir", record.working_dir or "-"),
        ("status", record.status),
        ("run_at", record.to_dict()["run_at_local"]),
        (
            "finished_at",
            "-"
            if not record.finished_at
            else format_local_timestamp(record.finished_at),
        ),
        ("duration", record.to_dict()["duration_display"]),
        ("source", record.to_dict()["source"]),
        ("kind", record.execution_kind or "-"),
        ("provider", record.provider_name or "-"),
        ("exit_code", "-" if record.exit_code is None else str(record.exit_code)),
        ("summary", record.output_summary or "-"),
        ("stdout_log", record.stdout_path or "-"),
        ("stderr_log", record.stderr_path or "-"),
        ("events_log", record.events_path or "-"),
    ]
    if connector_meta:
        details.extend(
            [
                ("connector", connector_meta.get("name", "-")),
                ("connector_type", connector_meta.get("type", "-")),
                ("conversation_id", connector_meta.get("conversation_id", "-")),
                ("source_message_id", connector_meta.get("source_message_id", "-")),
                ("source_user", connector_meta.get("source_user_name", "-")),
                ("source_user_id", connector_meta.get("source_user_id", "-")),
                ("reply_id", connector_meta.get("posted_reply_id", "-")),
            ]
        )
    if incoming_meta:
        details.extend(
            [
                ("incoming_attachment_dir", incoming_meta.get("dir", "-")),
                (
                    "incoming_attachment_count",
                    str(incoming_meta.get("count", 0)),
                ),
            ]
        )
    for key, value in details:
        typer.echo(f"{key}: {value}")


def _resolve_log_target(task_name: str | None, run_id: str | None, project: str | None):
    from .runs import get_run, resolve_latest_run_for_task

    if run_id:
        run = get_run(run_id)
        if not run:
            typer.echo(f"Run not found: {run_id}")
            raise typer.Exit(1)
        return run

    if not task_name:
        typer.echo("Specify a task name or use --run <exec_id>.")
        raise typer.Exit(1)

    run, projects = resolve_latest_run_for_task(task_name, project_filter=project)
    if run:
        return run
    if projects:
        typer.echo(
            f"Task '{task_name}' exists in multiple projects. Use --project with one of:"
        )
        for project_path in projects:
            typer.echo(project_path)
        raise typer.Exit(1)

    typer.echo(f"No runs found for task '{task_name}'.")
    raise typer.Exit(1)


def _find_named_tasks(name: str, project: str | None = None):
    from .parser import load_project_tasks
    from .scheduler import get_projects

    matches = []
    for proj_dir in get_projects():
        if project and project not in str(proj_dir):
            continue
        for task_file, local_task in load_project_tasks(proj_dir):
            if local_task.task.name == name:
                matches.append((proj_dir, task_file, local_task.task))
    return matches


def _resolve_named_task(name: str, project: str | None = None):
    matches = _find_named_tasks(name, project=project)
    if not matches:
        typer.echo(f"Task '{name}' not found.")
        raise typer.Exit(1)
    if len(matches) > 1:
        typer.echo(
            f"Task '{name}' exists in multiple projects. Use --project with one of:"
        )
        for proj_dir, _task_file, _task in matches:
            typer.echo(str(proj_dir))
        raise typer.Exit(1)
    return matches[0]


def _follow_logs(run_id: str, stream: str):
    from .runs import format_local_timestamp, get_run, log_path_for_stream

    run = get_run(run_id)
    if not run:
        raise typer.Exit(1)

    path = log_path_for_stream(run, stream)
    if not path or not path.exists():
        return

    position = path.stat().st_size
    while True:
        current = get_run(run_id)
        if path.exists():
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                handle.seek(position)
                chunk = handle.read()
                position = handle.tell()
            if chunk:
                if stream == "merged":
                    # merged follow uses fresh snapshot of appended events only
                    for line in chunk.splitlines():
                        try:
                            payload = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if not isinstance(payload, dict):
                            continue
                        ts = payload.get("ts", "")
                        stream_name = str(payload.get("stream", "")).upper().ljust(6)
                        text = str(payload.get("text", ""))
                        for logical_line in text.splitlines() or [text]:
                            if ts:
                                try:
                                    local_ts = format_local_timestamp(ts).split(" ", 1)[
                                        1
                                    ]
                                except Exception:
                                    local_ts = ts
                            else:
                                local_ts = "-"
                            typer.echo(f"{local_ts} {stream_name} {logical_line}")
                else:
                    typer.echo(chunk, nl=False)
        if not current or current.status != "RUNNING":
            break
        time.sleep(0.5)


def _follow_all_logs(stream: str, project: str | None = None):
    from .runs import list_runs, project_short_name, render_combined_events

    positions: dict[str, int] = {}

    for run in list_runs(limit=None, project_filter=project):
        if not run.events_path:
            continue
        path = Path(run.events_path)
        if path.exists():
            positions[run.id] = path.stat().st_size

    while True:
        new_events: list[dict] = []
        for run in list_runs(limit=None, project_filter=project):
            path_str = run.events_path
            if not path_str:
                continue
            path = Path(path_str)
            if not path.exists():
                continue

            start_pos = positions.get(run.id, 0)
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                handle.seek(start_pos)
                chunk = handle.read()
                positions[run.id] = handle.tell()

            if not chunk:
                continue

            temp_events: list[dict] = []
            for line in chunk.splitlines():
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(payload, dict):
                    continue
                temp_events.append(payload)

            for payload in temp_events:
                payload_stream = str(payload.get("stream", ""))
                if stream != "merged" and payload_stream != stream:
                    continue
                new_events.append(
                    {
                        "ts": str(payload.get("ts", "")),
                        "stream": payload_stream,
                        "text": str(payload.get("text", "")),
                        "run_id": run.id,
                        "task_name": run.task_name,
                        "project_path": run.project_path,
                        "project_short": project_short_name(run.project_path),
                    }
                )

        if new_events:
            typer.echo(render_combined_events(new_events, stream=stream), nl=False)
        time.sleep(0.5)


@project_app.command("list")
def project_list():
    """List all registered projects."""
    from .scheduler import get_projects
    from .parser import load_project_tasks
    from .config import KAGE_PROJECTS_LIST
    from rich.console import Console
    from rich.table import Table

    console = Console()
    projects = get_projects()

    if not projects:
        console.print("[yellow]No projects registered.[/yellow]")
        console.print(
            "Run [bold]kage init[/bold] in a project directory to register it."
        )
        console.print(f"List file: {KAGE_PROJECTS_LIST}")
        return

    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Project Path", style="bold")
    table.add_column("Tasks", justify="right")
    table.add_column("Status")

    for proj_dir in sorted(projects):
        tasks = load_project_tasks(proj_dir)
        task_count = len(tasks)
        exists = proj_dir.exists()
        status = "[green]✔ OK[/green]" if exists else "[red]✘ Directory not found[/red]"
        table.add_row(str(proj_dir), str(task_count), status)

    console.print(table)
    console.print(f"[dim]Source: {KAGE_PROJECTS_LIST}[/dim]")


@project_app.command("remove")
def project_remove(
    path: Optional[str] = typer.Argument(
        None, help="Project path to unregister (defaults to current directory)"
    ),
):
    """Unregister a project from kage."""
    from .config import KAGE_PROJECTS_LIST
    from .agent import assert_not_in_agent_run
    from rich.console import Console
    from pathlib import Path

    assert_not_in_agent_run("remove a project")
    console = Console()
    if path:
        target_path = Path(path).resolve()
    else:
        target_path = Path.cwd().resolve()
    target = str(target_path)

    if not KAGE_PROJECTS_LIST.exists():
        console.print("[yellow]No projects registered.[/yellow]")
        return

    lines = KAGE_PROJECTS_LIST.read_text().splitlines()
    new_lines = [
        line
        for line in lines
        if line.strip() and str(Path(line.strip()).resolve()) != target
    ]

    if len(new_lines) == len([line for line in lines if line.strip()]):
        console.print(f"[yellow]Project not found in registry: {target}[/yellow]")
        return

    KAGE_PROJECTS_LIST.write_text("\n".join(new_lines) + ("\n" if new_lines else ""))
    console.print(f"[green]✔ Removed:[/green] {target}")


@task_app.command("list")
def task_list(
    project: Optional[str] = typer.Option(
        None, "--project", "-p", help="Filter by project path"
    ),
):
    """List registered tasks with effective type and provider/command details."""
    from .compiler import compiled_task_indicator
    from .config import get_global_config
    from .scheduler import get_projects
    from .parser import load_project_tasks
    from rich.console import Console
    from rich.table import Table

    console = Console()
    projects = get_projects()

    if not projects:
        console.print(
            "[yellow]No projects registered. Run 'kage init' in a project directory.[/yellow]"
        )
        raise typer.Exit()

    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Project", style="dim")
    table.add_column("Task Name", style="bold")
    table.add_column("Active")
    table.add_column("Suspended")
    table.add_column("Schedule")
    table.add_column("Type")
    table.add_column("Provider/Command")

    found = False
    for proj_dir in projects:
        if project and project not in str(proj_dir):
            continue
        merged_cfg = get_global_config(workspace_dir=proj_dir)
        tasks = load_project_tasks(proj_dir)
        for toml_file, local_task in tasks:
            t = local_task.task
            compiled = compiled_task_indicator(t, toml_file)
            if t.prompt:
                task_type = _task_type_label(t, compiled["state"])
                if compiled["state"] == "fresh":
                    task_type = "Prompt ([green]Compiled[/green])"
                elif compiled["state"] == "stale":
                    task_type = "Prompt ([red]Compiled[/red])"
                effective_provider, inherited = _effective_task_provider(t, merged_cfg)
                provider_info = (
                    f"{effective_provider} (Inherited)"
                    if effective_provider and inherited
                    else effective_provider
                )
            else:
                task_type = _task_type_label(t)
                provider_info = (t.command or "")[:40]
            status = "[green]ON[/green]" if t.active else "[red]OFF[/red]"
            from .suspension import get_suspension_status

            suspension = get_suspension_status(
                t,
                tz_name=t.timezone or merged_cfg.timezone,
            )
            table.add_row(
                _project_short_name(str(proj_dir)),
                t.name,
                status,
                _suspension_table_value(suspension),
                t.cron,
                task_type,
                provider_info or "-",
            )
            found = True

    if not found:
        console.print("[yellow]No tasks found.[/yellow]")
    else:
        console.print(table)


@task_app.command("new")
def task_new(
    file_name: str = typer.Argument(
        ..., help="Name of the task file (without extension)"
    ),
):
    """Create a new kage task file in .kage/tasks/."""
    from pathlib import Path
    from rich.console import Console

    console = Console()
    tasks_dir = Path.cwd() / ".kage" / "tasks"

    if not tasks_dir.parent.exists():
        console.print("[red]Not in a kage project. Run 'kage init' first.[/red]")
        raise typer.Exit(1)

    tasks_dir.mkdir(parents=True, exist_ok=True)
    target_path = tasks_dir / f"{file_name}.md"

    if target_path.exists():
        console.print(f"[yellow]Task file already exists: {target_path}[/yellow]")
        raise typer.Exit(1)

    import locale

    lang = "en"
    try:
        loc, _ = locale.getlocale()
        if loc and loc.startswith("ja"):
            lang = "ja"
    except Exception:
        pass

    import os

    if os.environ.get("LANG", "").startswith("ja"):
        lang = "ja"

    if lang == "ja":
        template = f"""---
name: {file_name.replace("_", " ").title()}
cron: "0 3 * * *"
# provider: antigravity
active: false
mode: autostop
---

# Task: PDFのOCR精度測定ベンチマーク

PDFからテキストを抽出する最適な無料OCRモデルを選定するため、ベンチマークテストを実施してください。一晩かけて1つずつモデルを検証し、最終的な比較レポートを作成してください。

1. **データ準備**: サンプルPDFが存在しない場合は、テスト用に適当な日本語のダミーPDFを作成（またはダウンロード）してください。
2. **モデル検証**: 以下のOCRツールを1回の実行（run）につき1つずつインストール・実行し、テキスト抽出の精度と処理速度を計測してください。
   - Tesseract OCR (with jpn data)
   - EasyOCR
   - PaddleOCR
   - marker (Surya)
3. **レポート作成**: すべての検証が完了したら、`ocr_benchmark_report.md` をルートディレクトリに作成し、各モデルの精度、速度、導入のしやすさなどを比較した表を出力してください。
4. **終了**: レポートが出力されたら、すべてのサブタスクを 'done' にしてこのタスクを停止してください。
"""
    else:
        template = f"""---
name: {file_name.replace("_", " ").title()}
cron: "0 3 * * *"
# provider: antigravity
active: false
mode: autostop
---

# Task: PDF OCR Accuracy Benchmark

We need to select the best free OCR model for extracting text from PDFs. Please conduct a benchmark test overnight, evaluating one model per run, and create a final comparison report.

1. **Data Prep**: If a sample PDF doesn't exist, create (or download) a dummy PDF with varied text layouts for testing.
2. **Model Evaluation**: Install and run one of the following OCR tools per execution run. Measure text extraction accuracy and processing speed.
   - Tesseract OCR
   - EasyOCR
   - PaddleOCR
   - marker (Surya)
3. **Reporting**: Once all evaluations are complete, generate `ocr_benchmark_report.md` in the root directory. Include a comparison table showing accuracy, speed, and ease of setup for each model.
4. **Completion**: After the report is generated, mark all sub-tasks as 'done' to stop this task automatically.
"""
    target_path.write_text(template, encoding="utf-8")
    console.print(f"[green]✔ Created new task file:[/green] {target_path}")


def _set_task_active_state(name: Optional[str], active: bool, all_tasks: bool = False):
    from .scheduler import get_projects
    from .parser import load_project_tasks
    from .suspension import update_task_file_metadata
    from rich.console import Console

    console = Console()
    projects = get_projects()
    found_any = False

    for proj_dir in projects:
        tasks = load_project_tasks(proj_dir)
        for task_file, local_task in tasks:
            t = local_task.task
            if all_tasks or t.name == name:
                found_any = True
                update_task_file_metadata(
                    task_file,
                    task_name=t.name,
                    updates={"active": active},
                )
                state_str = (
                    "[green]ENABLED[/green]" if active else "[red]DISABLED[/red]"
                )
                console.print(f"{state_str}: {t.name} ({task_file})")

    if not found_any and not all_tasks:
        console.print(f"[red]Task '{name}' not found.[/red]")
        raise typer.Exit(1)


@task_app.command("on")
def task_on(
    name: Optional[str] = typer.Argument(
        None,
        help="Task name to enable",
        autocompletion=_complete_task_names,
    ),
    all_tasks: bool = typer.Option(False, "--all", help="Enable all tasks"),
):
    """Enable a specific task or all tasks."""
    if not name and not all_tasks:
        typer.echo("Error: Must specify a task name or use --all")
        raise typer.Exit(1)
    _set_task_active_state(name, True, all_tasks)


@task_app.command("off")
def task_off(
    name: Optional[str] = typer.Argument(
        None,
        help="Task name to disable",
        autocompletion=_complete_task_names,
    ),
    all_tasks: bool = typer.Option(False, "--all", help="Disable all tasks"),
):
    """Disable a specific task or all tasks."""
    if not name and not all_tasks:
        typer.echo("Error: Must specify a task name or use --all")
        raise typer.Exit(1)
    _set_task_active_state(name, False, all_tasks)


@task_app.command("suspend")
def task_suspend(
    name: str = typer.Argument(
        ...,
        help="Task name to suspend",
        autocompletion=_complete_task_names,
    ),
    for_duration: Optional[str] = typer.Option(
        None,
        "--for",
        help="Suspend for one duration token: 30m, 3h, 14d, or 2w",
    ),
    until: Optional[str] = typer.Option(
        None,
        "--until",
        help="Suspend until an ISO date or datetime",
    ),
    reason: Optional[str] = typer.Option(
        None,
        "--reason",
        help="Optional reason stored in task front matter",
    ),
    project: Optional[str] = typer.Option(
        None, "--project", "-p", help="Project path substring for task lookup"
    ),
):
    """Suspend a task until a deadline without changing its active state."""
    from .config import get_global_config
    from .suspension import (
        parse_suspension_deadline,
        suspension_deadline_from_duration,
        update_task_file_metadata,
    )
    from rich.console import Console

    if bool(for_duration) == bool(until):
        typer.echo("Specify exactly one of --for or --until.")
        raise typer.Exit(1)

    console = Console()
    proj_dir, task_file, task = _resolve_named_task(name, project=project)

    cfg = get_global_config(workspace_dir=proj_dir)
    task_tz = task.timezone or cfg.timezone
    try:
        deadline = (
            suspension_deadline_from_duration(for_duration, tz_name=task_tz)
            if for_duration
            else parse_suspension_deadline(until or "", tz_name=task_tz)
        )
    except ValueError as exc:
        typer.echo(str(exc))
        raise typer.Exit(1) from exc

    updates = {"suspended_until": deadline.isoformat(timespec="seconds")}
    remove_keys: set[str] = set()
    if reason is not None and reason.strip():
        updates["suspended_reason"] = reason
    elif reason is not None:
        remove_keys.add("suspended_reason")

    update_task_file_metadata(
        task_file,
        task_name=task.name,
        updates=updates,
        remove_keys=remove_keys,
    )
    console.print(
        f"[yellow]SUSPENDED[/yellow]: {task.name} until {updates['suspended_until']} ({task_file})"
    )


@task_app.command("resume")
def task_resume(
    name: str = typer.Argument(
        ...,
        help="Task name to resume",
        autocompletion=_complete_task_names,
    ),
    project: Optional[str] = typer.Option(
        None, "--project", "-p", help="Project path substring for task lookup"
    ),
):
    """Remove task suspension metadata without starting the task."""
    from .suspension import update_task_file_metadata
    from rich.console import Console

    console = Console()
    _proj_dir, task_file, task = _resolve_named_task(name, project=project)
    update_task_file_metadata(
        task_file,
        task_name=task.name,
        remove_keys={"suspended_until", "suspended_reason"},
    )
    console.print(f"[green]RESUMED[/green]: {task.name} ({task_file})")


@task_app.command("show")
def task_show(
    name: str = typer.Argument(
        ...,
        help="Task name to show details for",
        autocompletion=_complete_task_names,
    ),
    project: Optional[str] = typer.Option(
        None, "--project", "-p", help="Project path substring for task lookup"
    ),
):
    """Show detailed task configuration, including compiled lock freshness and prompt hash."""
    from .compiler import compiled_task_status, prompt_hash
    from .config import get_global_config
    from .suspension import get_suspension_status
    from rich.console import Console
    from rich.panel import Panel

    console = Console()
    proj_dir, task_file, task = _resolve_named_task(name, project=project)
    merged_cfg = get_global_config(workspace_dir=proj_dir)
    suspension = get_suspension_status(
        task,
        tz_name=task.timezone or merged_cfg.timezone,
    )
    details = [
        f"[bold]Name:[/bold]           {task.name}",
        f"[bold]Schedule:[/bold]       {task.cron}",
        f"[bold]Mode:[/bold]           {task.mode}",
        f"[bold]Concurrency:[/bold]    {task.concurrency_policy}",
        f"[bold]Timezone:[/bold]       {task.timezone or 'global'}",
        f"[bold]Allowed Hours:[/bold]  {task.allowed_hours or 'any'}",
        f"[bold]Denied Hours:[/bold]   {task.denied_hours or 'none'}",
        f"[bold]Suspension:[/bold]     {suspension.summary}",
        f"[bold]Suspend Reason:[/bold] {task.suspended_reason or '-'}",
        f"[bold]Project:[/bold]        {proj_dir}",
        f"[bold]File:[/bold]           {task_file}",
    ]
    compiled = compiled_task_status(task, task_file)
    if task.prompt:
        compiled_state = (
            "fresh"
            if compiled and compiled["exists"] and compiled["is_fresh"]
            else "stale"
            if compiled and compiled["exists"]
            else "none"
        )
        effective_provider, inherited = _effective_task_provider(task, merged_cfg)
        provider_label = (
            f"{effective_provider} (Inherited)"
            if effective_provider and inherited
            else effective_provider or "unresolved"
        )
        details.append(
            f"[bold]Type:[/bold]           {_task_type_label(task, compiled_state)}"
        )
        details.append(f"[bold]Prompt:[/bold]         {task.prompt[:100]}...")
        details.append(
            f"[bold]Prompt Hash:[/bold]    {(compiled or {}).get('prompt_hash', prompt_hash(task.prompt or ''))}"
        )
        details.append(f"[bold]Provider:[/bold]       {provider_label}")
        if compiled:
            if compiled["exists"]:
                freshness = (
                    "fresh" if compiled["is_fresh"] else "stale; recompile required"
                )
                details.append(
                    f"[bold]Compiled:[/bold]       {compiled['path']} ({freshness})"
                )
            else:
                details.append("[bold]Compiled:[/bold]       none")
    elif task.command:
        details.append(f"[bold]Type:[/bold]           {_task_type_label(task)}")
        details.append(f"[bold]Command:[/bold]        {task.command}")
    console.print(
        Panel("\n".join(details), title=f"[cyan]{task.name}[/cyan]", expand=False)
    )


@task_app.command("run")
def task_run(
    name: str = typer.Argument(
        ...,
        help="Task name to run immediately",
        autocompletion=_complete_task_names,
    ),
    project: Optional[str] = typer.Option(
        None, "--project", "-p", help="Project path substring for task lookup"
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Run even when the task is currently suspended",
    ),
):
    """Run a specific task immediately (ignores schedule, but not suspension unless forced)."""
    from .config import get_global_config
    from .executor import TaskExecutionResult, execute_task
    from .suspension import get_suspension_status
    from rich.console import Console

    console = Console()
    proj_dir, task_file, task = _resolve_named_task(name, project=project)
    if not force:
        cfg = get_global_config(workspace_dir=proj_dir)
        suspension = get_suspension_status(
            task,
            tz_name=task.timezone or cfg.timezone,
        )
        if suspension.is_suspended:
            console.print(
                f"[yellow]Task '{name}' is suspended:[/yellow] {suspension.summary}"
            )
            raise typer.Exit(1)

    console.print(f"[cyan]Running task:[/cyan] [bold]{name}[/bold] in {proj_dir}")
    result = execute_task(proj_dir, task, task_file=task_file, force=force)
    if result != TaskExecutionResult.STARTED:
        console.print(
            f"[yellow]Task '{name}' did not start:[/yellow] {_execution_result_message(result)}"
        )
        raise typer.Exit(1)
    console.print(f"[green]✓ Task '{name}' completed.[/green]")


@cron_app.command("install")
def cron_install():
    """Register the scheduler loop in cron/launchd."""
    daemon.install()


@cron_app.command("remove")
def cron_remove():
    """Unregister the scheduler loop from cron/launchd."""
    daemon.remove()


@cron_app.command("status")
def cron_status():
    """Check whether the scheduler loop is registered."""
    daemon.status()


@cron_app.command("start")
def cron_start():
    """Start/Enable background tasks."""
    daemon.start()


@cron_app.command("stop")
def cron_stop():
    """Stop/Disable background tasks."""
    daemon.stop()


@cron_app.command("restart")
def cron_restart():
    """Restart background tasks."""
    daemon.restart()


@cron_app.command("run")
def cron_run():
    """Run scheduled tasks once for the system scheduler."""
    from .scheduler import run_all_scheduled_tasks

    run_all_scheduled_tasks()


@quest_app.command("new")
def quest_new(
    name: str = typer.Argument(..., help="Short quest name"),
    direction: str = typer.Option(
        ..., "--direction", "-d", help="Vague direction / goal"
    ),
    project: Optional[str] = typer.Option(
        None, "--project", "-p", help="Project path (defaults to current dir)"
    ),
    roles: str = typer.Option(
        "scout,poc,strategist", "--roles", help="Comma-separated role names"
    ),
    max_agent_runs: int = typer.Option(
        50, "--max-agent-runs", help="Hard cap on total agent dispatches"
    ),
    provider: Optional[str] = typer.Option(
        None, "--provider", help="AI provider override (e.g. claude, gemini)"
    ),
    solo: bool = typer.Option(
        False,
        "--solo",
        help="Legacy mode: roles spawn children directly without an owner gate",
    ),
):
    """Create a new quest with a root scout node ready to dispatch."""
    from .quest import QuestMode, create_quest, get_quest

    project_path = Path(project).resolve() if project else Path.cwd().resolve()
    quest = create_quest(
        str(project_path),
        name,
        direction,
        roles=[r.strip() for r in roles.split(",") if r.strip()],
        max_agent_runs=max_agent_runs,
        provider=provider,
        mode=QuestMode.SOLO if solo else QuestMode.TEAM,
    )
    refreshed = get_quest(quest.id)
    assert refreshed is not None
    typer.echo(
        f"Created quest {refreshed.id}: {refreshed.name} "
        f"(status={refreshed.status}, max_agent_runs={refreshed.max_agent_runs})"
    )


@quest_app.command("list")
def quest_list(
    status_filter: Optional[str] = typer.Option(
        None, "--status", help="Filter by quest status"
    ),
    project: Optional[str] = typer.Option(
        None, "--project", "-p", help="Project path substring filter"
    ),
    json_output: bool = typer.Option(False, "--json", help="Print structured JSON"),
):
    """List quests and their progress."""
    from .quest import list_quests, node_counts
    from rich.console import Console
    from rich.table import Table

    console = Console()
    quests = list_quests(status_filter=status_filter, project_filter=project)
    if json_output:
        payload = [q.to_dict() | {"node_counts": node_counts(q.id)} for q in quests]
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    if not quests:
        console.print("[yellow]No quests found.[/yellow]")
        return
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("ID", style="bold")
    table.add_column("Name")
    table.add_column("Status")
    table.add_column("Runs", justify="right")
    table.add_column("Nodes")
    table.add_column("Direction")
    for q in quests:
        counts = node_counts(q.id)
        node_summary = (
            f"{counts.get('total', 0)} "
            f"(exp {counts.get('explored', 0)}/grow {counts.get('growing', 0)}/"
            f"abort {counts.get('aborted', 0)})"
        )
        table.add_row(
            q.id,
            q.name,
            q.status,
            f"{q.agent_runs}/{q.max_agent_runs}",
            node_summary,
            q.direction[:60],
        )
    console.print(table)


@quest_app.command("show")
def quest_show(
    quest_id: str = typer.Argument(..., help="Quest ID"),
    json_output: bool = typer.Option(False, "--json", help="Print structured JSON"),
):
    """Show a quest, its nodes, and edges."""
    from .quest import get_quest, list_edges, list_nodes

    quest = get_quest(quest_id)
    if not quest:
        typer.echo(f"Quest not found: {quest_id}")
        raise typer.Exit(1)
    nodes = list_nodes(quest_id)
    edges = list_edges(quest_id)
    if json_output:
        typer.echo(
            json.dumps(
                {
                    "quest": quest.to_dict(),
                    "nodes": [n.to_dict() for n in nodes],
                    "edges": [e.__dict__ for e in edges],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    from rich.console import Console
    from rich.table import Table

    console = Console()
    console.print(
        f"[bold cyan]{quest.id}[/bold cyan] {quest.name} (status={quest.status}, "
        f"runs={quest.agent_runs}/{quest.max_agent_runs})"
    )
    console.print(f"Direction: {quest.direction}")
    table = Table(show_header=True, header_style="bold", title="Nodes")
    table.add_column("ID")
    table.add_column("Role")
    table.add_column("Status")
    table.add_column("Verdict")
    table.add_column("Hypothesis")
    for n in nodes:
        table.add_row(n.id, n.role, n.status, n.verdict or "-", n.hypothesis[:80])
    console.print(table)
    if edges:
        edge_table = Table(show_header=True, header_style="bold", title="Edges")
        edge_table.add_column("From")
        edge_table.add_column("To")
        edge_table.add_column("Relation")
        for e in edges:
            edge_table.add_row(e.from_node or "-", e.to_node or "-", e.relation)
        console.print(edge_table)


@quest_app.command("stop")
def quest_stop(
    quest_id: str = typer.Argument(..., help="Quest ID"),
):
    """Stop an active quest (ticks will skip it until resumed)."""
    from .quest import get_quest, set_quest_status

    if not get_quest(quest_id):
        typer.echo(f"Quest not found: {quest_id}")
        raise typer.Exit(1)
    set_quest_status(quest_id, "stopped")
    typer.echo(f"Stopped quest {quest_id}")


@quest_app.command("resume")
def quest_resume(
    quest_id: str = typer.Argument(..., help="Quest ID"),
):
    """Resume a stopped quest."""
    from .quest import get_quest, set_quest_status

    if not get_quest(quest_id):
        typer.echo(f"Quest not found: {quest_id}")
        raise typer.Exit(1)
    set_quest_status(quest_id, "active")
    typer.echo(f"Resumed quest {quest_id}")


@quest_app.command("abort-node")
def quest_abort_node(
    node_id: str = typer.Argument(..., help="Quest node ID"),
):
    """Force-abort a single quest node."""
    from .quest import abort_node

    node = abort_node(node_id)
    if not node:
        typer.echo(f"Node not found: {node_id}")
        raise typer.Exit(1)
    typer.echo(f"Aborted node {node_id}")


def _is_ja() -> bool:
    import os

    for key in ("LC_ALL", "LANG", "LANGUAGE"):
        value = os.environ.get(key, "")
        if value.startswith("ja"):
            return True
    return False


@app.command()
def onboard():
    """Initial setup for kage: Create ~/.kage and default configuration."""
    if _is_ja():
        typer.echo("kage の初期セットアップを実行中...")
    else:
        typer.echo("Initializing kage onboard...")

    config_mod.setup_global()
    daemon.install()
    db.init_db()

    if _is_ja():
        typer.echo("グローバル設定とデータベースのセットアップが完了しました。")
    else:
        typer.echo("Successfully set up global configuration and database.")


@app.command()
def init():
    """Initialize a kage project in the current directory."""
    if _is_ja():
        typer.echo("プロジェクトを初期化中...")
    else:
        typer.echo("Initializing kage project...")

    config_mod.setup_local()

    if _is_ja():
        typer.echo("初期化が完了しました。")
    else:
        typer.echo("Project initialized.")


@app.command()
def run(
    name: str = typer.Argument(
        ...,
        help="Task name to run immediately",
        autocompletion=_complete_task_names,
    ),
    project: Optional[str] = typer.Option(
        None, "--project", "-p", help="Project path substring for task lookup"
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Run even when the task is currently suspended",
    ),
):
    """Run a specific task immediately."""
    task_run(name=name, project=project, force=force)


@app.command()
def compile(
    name: str = typer.Argument(
        ...,
        help="Task name to compile into a .lock.sh script",
        autocompletion=_complete_task_names,
    ),
    project: Optional[str] = typer.Option(
        None, "--project", "-p", help="Project path substring for task lookup"
    ),
):
    """Compile a prompt task into a .lock.sh override."""
    from .compiler import compile_prompt_task

    proj_dir, task_file, task = _resolve_named_task(name, project=project)
    try:
        compiled_path = compile_prompt_task(proj_dir, task, task_file)
    except ValueError as exc:
        typer.echo(str(exc))
        raise typer.Exit(1) from exc
    except RuntimeError as exc:
        typer.echo(str(exc))
        raise typer.Exit(1) from exc

    typer.echo(f"Compiled '{name}' -> {compiled_path}")


@runs_app.callback(invoke_without_command=True)
def runs(
    ctx: typer.Context,
    task: Optional[str] = typer.Option(None, "--task", help="Filter by task name"),
    project: Optional[str] = typer.Option(
        None, "--project", "-p", help="Filter by project path substring"
    ),
    status: Optional[str] = typer.Option(None, "--status", help="Filter by status"),
    source: Optional[str] = typer.Option(
        None, "--source", help="Filter by source: task or connector_poll"
    ),
    limit: int = typer.Option(20, "--limit", help="Maximum runs to show"),
    absolute_time: bool = typer.Option(
        False,
        "--absolute-time",
        help="Show absolute local timestamps instead of relative time",
    ),
    json_output: bool = typer.Option(False, "--json", help="Print structured JSON"),
):
    """List execution runs."""
    if ctx.invoked_subcommand:
        return

    from .runs import list_runs

    records = list_runs(
        limit=limit,
        task_name=task,
        project_filter=project,
        status=status,
        source=source,
    )
    _print_runs(
        records,
        json_output=json_output,
        absolute_time=absolute_time,
    )


@runs_app.command("show")
def runs_show(
    exec_id: str = typer.Argument(
        ...,
        help="Execution ID to inspect",
        autocompletion=_complete_run_ids,
    ),
    json_output: bool = typer.Option(False, "--json", help="Print structured JSON"),
):
    """Show details for a single execution run."""
    from .runs import get_run

    record = get_run(exec_id)
    if not record:
        typer.echo(f"Run not found: {exec_id}")
        raise typer.Exit(1)
    _print_run_details(record, json_output=json_output)


@runs_app.command("stop")
def runs_stop(
    exec_id: str = typer.Argument(
        ...,
        help="Execution ID to stop",
        autocompletion=_complete_run_ids,
    ),
):
    """Stop a running execution."""
    from .executor import stop_execution

    typer.echo(f"Stopping execution {exec_id}...")
    stop_execution(exec_id)
    typer.echo("Stop signal sent.")


@app.command()
def logs(
    task_name: Optional[str] = typer.Argument(
        None,
        help="Task name to inspect (latest run only). Omit to merge logs across all tasks",
        autocompletion=_complete_task_names,
    ),
    run_id: Optional[str] = typer.Option(
        None, "--run", help="Execution ID to inspect directly"
    ),
    project: Optional[str] = typer.Option(
        None, "--project", "-p", help="Project path substring for task lookup"
    ),
    stream: str = typer.Option(
        "merged", "--stream", help="Log stream: merged, stdout, stderr"
    ),
    lines: Optional[int] = typer.Option(
        None, "--lines", help="Show only the last N lines"
    ),
    since: Optional[str] = typer.Option(
        None,
        "--since",
        help="Only show entries since ISO timestamp or relative time like 10m",
    ),
    follow: bool = typer.Option(False, "--follow", "-f", help="Follow appended output"),
    path_only: bool = typer.Option(
        False, "--path", help="Print the underlying log file path"
    ),
    json_output: bool = typer.Option(False, "--json", help="Print structured JSON"),
):
    """View raw execution logs."""
    from .runs import load_all_log_text, load_log_text, log_path_for_stream

    if stream not in {"merged", "stdout", "stderr"}:
        raise typer.BadParameter("--stream must be one of: merged, stdout, stderr")
    if follow and json_output:
        raise typer.BadParameter("--follow cannot be combined with --json")
    if path_only and not (task_name or run_id):
        raise typer.BadParameter("--path requires a task name or --run <exec_id>")

    if not task_name and not run_id:
        try:
            content = load_all_log_text(
                stream=stream,
                lines=lines,
                since=since,
                project_filter=project,
            )
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc

        if json_output:
            typer.echo(
                json.dumps(
                    {
                        "scope": "all",
                        "stream": stream,
                        "project_filter": project,
                        "content": content,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        elif content:
            typer.echo(content, nl=not content.endswith("\n"))
        else:
            typer.echo(
                "No log output recorded."
                if not _is_ja()
                else "まだログ出力は記録されていません。"
            )

        if follow:
            _follow_all_logs(stream=stream, project=project)
        return

    run = _resolve_log_target(task_name=task_name, run_id=run_id, project=project)
    target_path = log_path_for_stream(run, stream)

    if path_only:
        if not target_path or not target_path.exists():
            typer.echo("No raw log file is available for this run.")
            raise typer.Exit(1)
        if json_output:
            typer.echo(
                json.dumps(
                    {
                        "run_id": run.id,
                        "task_name": run.task_name,
                        "stream": stream,
                        "path": str(target_path),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            typer.echo(str(target_path))
        return

    try:
        content = load_log_text(run, stream=stream, lines=lines, since=since)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    if json_output:
        typer.echo(
            json.dumps(
                {
                    "run": run.to_dict(),
                    "stream": stream,
                    "path": str(target_path) if target_path else None,
                    "content": content,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    elif content:
        typer.echo(content, nl=not content.endswith("\n"))
    else:
        typer.echo("No log output recorded.")

    if follow:
        _follow_logs(run.id, stream)


@app.command()
def stop(
    exec_id: str = typer.Argument(
        ...,
        help="Execution ID to stop",
        autocompletion=_complete_run_ids,
    ),
):
    """Stop a running execution."""
    runs_stop(exec_id)


@app.command()
def ui(
    host: Optional[str] = typer.Option(
        None, "--host", "-h", help="Bind host (e.g., '0.0.0.0' for external access)"
    ),
    port: Optional[int] = typer.Option(None, "--port", "-p", help="Bind port"),
):
    """Launch the web UI dashboard."""
    from .config import get_global_config
    from .web import start_ui

    cfg = get_global_config()
    target_host = host or cfg.ui_host
    target_port = port or cfg.ui_port
    typer.echo(f"Starting web UI on {target_host}:{target_port}...")
    start_ui(host=target_host, port=target_port)


@app.command()
def tui():
    """Launch the terminal UI dashboard."""
    from .tui import start_tui

    start_tui()


@app.command()
def config(
    key: str = typer.Argument(
        ...,
        help="Setting key (e.g., 'default_ai_engine' or 'providers.antigravity.model')",
    ),
    value: str = typer.Argument(..., help="New value"),
    is_global: bool = typer.Option(
        False,
        "--global",
        "-g",
        help="Update global config (~/.kage/config.toml) instead of workspace config",
    ),
    is_local: bool = typer.Option(
        False,
        "--local",
        "-l",
        help="Update local config (.kage/config.local.toml) instead of workspace config",
    ),
):
    """Update configuration via CLI."""
    from .config import set_config_value
    from .gemini_transition import (
        emit_gemini_transition_warning,
        should_warn_for_gemini_config,
    )

    if is_global and is_local:
        raise typer.BadParameter("--global and --local cannot be used together")

    scope = "global" if is_global else "local" if is_local else "project"
    set_config_value(key, value, is_global=is_global, scope=scope)
    if should_warn_for_gemini_config(key, value):
        emit_gemini_transition_warning(f"You're configuring Gemini CLI via '{key}'")


@app.command("config-show")
def config_show(
    workspace: Optional[str] = typer.Option(
        None, "--workspace", "-w", help="Workspace path for resolving .kage/config.toml"
    ),
):
    """Show resolved configuration (commands/providers/defaults)."""
    from pathlib import Path
    from rich.console import Console
    from rich.table import Table
    from .config import get_global_config, KAGE_CONFIG_PATH
    from .gemini_transition import (
        build_gemini_transition_warning,
        is_gemini_provider_name,
    )

    ws_dir = Path(workspace).resolve() if workspace else Path.cwd()
    ws_cfg_path = ws_dir / ".kage" / "config.toml"
    ws_local_cfg_path = ws_dir / ".kage" / "config.local.toml"
    cfg = get_global_config(workspace_dir=ws_dir)

    console = Console()
    console.print("\n[bold cyan]kage config-show[/bold cyan]\n")
    if is_gemini_provider_name(cfg.default_ai_engine):
        console.print(
            f"[yellow]{build_gemini_transition_warning('default_ai_engine is set to gemini')}[/yellow]\n"
        )

    summary = Table(show_header=False, box=None, padding=(0, 1))
    summary.add_column("k", style="bold")
    summary.add_column("v")
    summary.add_row("Workspace", str(ws_dir))
    summary.add_row(
        "Global Config",
        f"{KAGE_CONFIG_PATH} ({'found' if KAGE_CONFIG_PATH.exists() else 'missing'})",
    )
    summary.add_row(
        "Workspace Config",
        f"{ws_cfg_path} ({'found' if ws_cfg_path.exists() else 'missing'})",
    )
    summary.add_row(
        "Local Config",
        f"{ws_local_cfg_path} ({'found' if ws_local_cfg_path.exists() else 'missing'})",
    )
    summary.add_row("default_ai_engine", str(cfg.default_ai_engine or "None"))
    summary.add_row("ui_port", str(cfg.ui_port))
    summary.add_row("ui_host", str(cfg.ui_host))
    summary.add_row("log_level", str(cfg.log_level))
    summary.add_row("timezone", str(cfg.timezone))
    summary.add_row("cron_interval_minutes", str(cfg.cron_interval_minutes))
    summary.add_row("run_retention_count", str(cfg.run_retention_count))
    summary.add_row("env_path", str(cfg.env_path or "None"))
    console.print(summary)

    provider_table = Table(title="Providers", show_header=True, header_style="bold")
    provider_table.add_column("name", style="bold")
    provider_table.add_column("command")
    provider_table.add_column("model")
    provider_table.add_column("model_flag")
    provider_table.add_column("parser")
    provider_table.add_column("parser_args")
    for name in sorted(cfg.providers.keys()):
        p = cfg.providers[name]
        provider_table.add_row(
            name,
            p.command,
            p.model or "",
            p.model_flag or "",
            p.parser,
            p.parser_args or "",
        )
    if cfg.providers:
        console.print(provider_table)
    else:
        console.print("[yellow]No providers loaded.[/yellow]")

    command_table = Table(title="Commands", show_header=True, header_style="bold")
    command_table.add_column("name", style="bold")
    command_table.add_column("template")
    for name in sorted(cfg.commands.keys()):
        c = cfg.commands[name]
        command_table.add_row(name, " ".join(c.template))
    if cfg.commands:
        console.print(command_table)
    else:
        console.print("[yellow]No commands loaded.[/yellow]")


@app.command()
def doctor():
    """Run setup diagnostics and show potential issues."""
    import importlib.util
    import os
    from datetime import datetime
    from pathlib import Path
    import tomlkit
    from croniter import croniter
    from rich.console import Console
    from rich.table import Table
    from .suspension import parse_suspension_deadline
    from .config import (
        get_global_config,
        KAGE_GLOBAL_DIR,
        KAGE_CONFIG_PATH,
        KAGE_PROJECTS_LIST,
        KAGE_DB_PATH,
        KAGE_LOGS_DIR,
    )
    from .gemini_transition import build_gemini_transition_warning

    is_ja = os.environ.get("LANG", "").startswith("ja")

    t_title = "セットアップ診断" if is_ja else "Setup Diagnostics"
    t_chk = "チェック項目" if is_ja else "Check Item"
    t_det = "詳細" if is_ja else "Details"
    t_exists = "存在します" if is_ja else "Found"
    t_run_onboard = "kage onboard を実行してください" if is_ja else "Run 'kage onboard'"
    t_not_found = "が見つかりません" if is_ja else "not found"
    t_only_default = (
        "ライブラリデフォルトのみが使用されます" if is_ja else "Using library defaults"
    )
    t_proj_reg = "プロジェクト登録済み" if is_ja else "projects registered"
    t_run_init = (
        "kage onboard / init を実行してください"
        if is_ja
        else "Run 'kage onboard' or 'kage init'"
    )
    t_ai_not_set = (
        "default_ai_engine が未設定" if is_ja else "default_ai_engine not set"
    )
    t_ai_hint = (
        "AIタスクを使う場合: kage config default_ai_engine antigravity --global"
        if is_ja
        else "If using AI tasks: run 'kage config default_ai_engine antigravity --global'"
    )
    t_prov_undef = "が未定義" if is_ja else "is undefined"
    t_prov_cmd_hint = (
        "default_config.toml または config.toml に commands を追加してください"
        if is_ja
        else "Add commands to your config.toml"
    )
    t_prov_hint = (
        "config.toml に providers セクションを追加するか、デフォルト設定を確認してください"
        if is_ja
        else "Check providers in your config or default_config.toml"
    )
    t_res = "結果:" if is_ja else "Result:"
    t_err = "エラー" if is_ja else "errors"
    t_warn = "警告" if is_ja else "warnings"
    t_migrate_hint = (
        "kage migrate install を実行してください"
        if is_ja
        else "Run 'kage migrate install'"
    )
    t_completion_hint = (
        "kage completion install bash または zsh を実行してください"
        if is_ja
        else "Run 'kage completion install bash' or 'kage completion install zsh'"
    )
    t_tui_hint = (
        "'kage tui' を使うには textual 依存が必要です"
        if is_ja
        else "Install the 'textual' dependency to use 'kage tui'"
    )
    t_connector_artifacts = "connector artifacts" if not is_ja else "connector 添付"
    t_connector_artifacts_detail = (
        "Connector-aware runs export KAGE_ARTIFACT_DIR as a workspace-local staging directory. Incoming connector attachments are downloaded to KAGE_ARTIFACT_DIR/incoming for that run, and Discord, Slack, and Telegram upload every top-level file left in KAGE_ARTIFACT_DIR, so keep only intended final deliverables there and delete source or intermediate files before the run ends unless they were explicitly requested."
        if not is_ja
        else "connector を使う run では workspace 内 staging directory として KAGE_ARTIFACT_DIR を export します。受信した connector 添付はその run の KAGE_ARTIFACT_DIR/incoming に保存され、Discord / Slack / Telegram は KAGE_ARTIFACT_DIR 直下に最後に残っている top-level file をすべて upload するので、そこには意図した最終成果物だけを残し、source や中間 file は明示的に求められた場合以外は終了前に削除してください。"
    )
    t_connector_artifacts_detail_empty = (
        "KAGE_ARTIFACT_DIR is created only for connector-aware runs, including connector poll replies."
        if not is_ja
        else "KAGE_ARTIFACT_DIR は connector-aware な run でのみ作られ、connector poll reply でも利用されます。"
    )

    console = Console()
    console.print(f"\n[bold cyan]kage doctor[/bold cyan] — {t_title}\n")

    checks = []

    def ok(label, detail=""):
        checks.append(("[green]✔[/green]", label, detail))

    def warn(label, detail=""):
        checks.append(("[yellow]⚠[/yellow]", label, detail))

    def fail(label, detail=""):
        checks.append(("[red]✘[/red]", label, detail))

    def _validate_cron(expr: object, label: str):
        if not isinstance(expr, str):
            fail(label, "cron must be a string")
            return
        try:
            croniter(expr, datetime.now().astimezone())
        except Exception:
            warn(label, f"invalid cron expression: {expr}")

    def _load_toml(path: Path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                doc = tomlkit.load(f)
            return doc.unwrap() if hasattr(doc, "unwrap") else dict(doc), None
        except Exception as e:
            return None, str(e)

    def _validate_config_file(path: Path, scope: str):
        data, err = _load_toml(path)
        if err:
            fail(f"{scope} parse", err)
            return
        if not isinstance(data, dict):
            fail(scope, "must be a TOML table/object")
            return

        allowed_top = {
            "default_ai_engine",
            "log_level",
            "ui_port",
            "ui_host",
            "cron_interval_minutes",
            "timezone",
            "env_path",
            "commands",
            "providers",
            "connectors",
            "agents",
            "default_agent",
            "run_retention_count",
            "working_dir",
        }
        for k in data.keys():
            if k not in allowed_top:
                warn(scope, f"unknown top-level key: {k}")

        typed_keys = {
            "default_ai_engine": (str,),
            "log_level": (str,),
            "ui_port": (int,),
            "ui_host": (str,),
            "cron_interval_minutes": (int,),
            "timezone": (str,),
            "env_path": (str,),
            "system_prompt": (str,),
            "default_agent": (str,),
            "run_retention_count": (int,),
            "working_dir": (str,),
        }
        for key, expected in typed_keys.items():
            if (
                key in data
                and data[key] is not None
                and not isinstance(data[key], expected)
            ):
                fail(scope, f"{key} must be {expected[0].__name__}")

        commands = data.get("commands")
        if commands is not None:
            if not isinstance(commands, dict):
                fail(scope, "commands must be a table")
            else:
                for name, cmd in commands.items():
                    if not isinstance(cmd, dict):
                        fail(scope, f"commands.{name} must be a table")
                        continue
                    for k in cmd.keys():
                        if k != "template":
                            warn(scope, f"commands.{name}: unknown key {k}")
                    tmpl = cmd.get("template")
                    if not isinstance(tmpl, list) or not all(
                        isinstance(x, str) for x in tmpl
                    ):
                        fail(scope, f"commands.{name}.template must be string array")

        providers = data.get("providers")
        if providers is not None:
            if not isinstance(providers, dict):
                fail(scope, "providers must be a table")
            else:
                for name, prov in providers.items():
                    if not isinstance(prov, dict):
                        fail(scope, f"providers.{name} must be a table")
                        continue
                    for k in prov.keys():
                        if k not in {
                            "command",
                            "parser",
                            "parser_args",
                            "model",
                            "model_flag",
                        }:
                            warn(scope, f"providers.{name}: unknown key {k}")
                    if "command" in prov and not isinstance(prov["command"], str):
                        fail(scope, f"providers.{name}.command must be string")
                    if "parser" in prov and not isinstance(prov["parser"], str):
                        fail(scope, f"providers.{name}.parser must be string")
                    if "parser_args" in prov and not isinstance(
                        prov["parser_args"], str
                    ):
                        fail(scope, f"providers.{name}.parser_args must be string")
                    if (
                        "model" in prov
                        and prov["model"] is not None
                        and not isinstance(prov["model"], str)
                    ):
                        fail(scope, f"providers.{name}.model must be string")
                    if (
                        "model_flag" in prov
                        and prov["model_flag"] is not None
                        and not isinstance(prov["model_flag"], str)
                    ):
                        fail(scope, f"providers.{name}.model_flag must be string")
                    if isinstance(commands, dict):
                        command_name = prov.get("command")
                        if (
                            isinstance(command_name, str)
                            and command_name not in commands
                        ):
                            warn(
                                scope,
                                f"providers.{name}.command references unknown commands.{command_name}",
                            )

    def _split_markdown_front_matter(text: str):
        lines = text.splitlines()
        if not lines or lines[0].strip() != "---":
            return None, text
        end_idx = None
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                end_idx = i
                break
        if end_idx is None:
            return None, text
        data = {}
        for raw in lines[1:end_idx]:
            line = raw.strip()
            if not line or line.startswith("#") or ":" not in line:
                continue
            k, v = line.split(":", 1)
            key = k.strip()
            val = v.strip()
            if (val.startswith('"') and val.endswith('"')) or (
                val.startswith("'") and val.endswith("'")
            ):
                val = val[1:-1]
            data[key] = val
        body = "\n".join(lines[end_idx + 1 :]).strip()
        return data, body

    def _validate_task_mapping(task_data: dict, label: str, merged_cfg):
        allowed = {
            "name",
            "cron",
            "active",
            "mode",
            "concurrency_policy",
            "timezone",
            "timeout_minutes",
            "allowed_hours",
            "denied_hours",
            "suspended_until",
            "suspended_reason",
            "command",
            "shell",
            "working_dir",
            "prompt",
            "provider",
            "command_template",
            "parser",
            "parser_args",
            "ai",
            "connector",
            "connectors",
            "notify_connectors",
        }
        for k in task_data.keys():
            if k not in allowed:
                warn(label, f"unknown key: {k}")

        if (
            not isinstance(task_data.get("name"), str)
            or not task_data.get("name", "").strip()
        ):
            fail(label, "name is required and must be string")
        _validate_cron(task_data.get("cron"), label)

        if task_data.get("prompt") is None and task_data.get("command") is None:
            warn(label, "neither prompt nor command is set")
        if task_data.get("prompt") is not None and not isinstance(
            task_data.get("prompt"), str
        ):
            fail(label, "prompt must be string")
        if task_data.get("command") is not None:
            if not isinstance(task_data.get("command"), str):
                fail(label, "command must be string")
            elif not task_data.get("command", "").strip():
                fail(label, "command must be non-empty string")
        if task_data.get("shell") is not None and not isinstance(
            task_data.get("shell"), str
        ):
            fail(label, "shell must be string")
        if task_data.get("working_dir") is not None and not isinstance(
            task_data.get("working_dir"), str
        ):
            fail(label, "working_dir must be string")
        if task_data.get("suspended_until") is not None:
            if not isinstance(task_data["suspended_until"], str):
                fail(label, "suspended_until must be string")
            else:
                try:
                    parse_suspension_deadline(
                        task_data["suspended_until"],
                        tz_name=task_data.get("timezone") or merged_cfg.timezone,
                    )
                except ValueError as exc:
                    warn(label, str(exc))
        if task_data.get("suspended_reason") is not None and not isinstance(
            task_data["suspended_reason"], str
        ):
            fail(label, "suspended_reason must be string")

        command_template = task_data.get("command_template")
        if command_template is not None and (
            not isinstance(command_template, list)
            or not all(isinstance(x, str) for x in command_template)
        ):
            fail(label, "command_template must be string array")

        if task_data.get("provider") is not None:
            if not isinstance(task_data["provider"], str):
                fail(label, "provider must be string")
            elif task_data["provider"] not in merged_cfg.providers:
                warn(
                    label,
                    f"provider '{task_data['provider']}' is not defined in merged config",
                )

        if task_data.get("parser") is not None and not isinstance(
            task_data["parser"], str
        ):
            fail(label, "parser must be string")
        if task_data.get("parser_args") is not None and not isinstance(
            task_data["parser_args"], str
        ):
            fail(label, "parser_args must be string")

        ai = task_data.get("ai")
        if ai is not None:
            if not isinstance(ai, dict):
                fail(label, "ai must be table")
            else:
                for k in ai.keys():
                    if k not in {"engine", "args"}:
                        warn(label, f"ai: unknown key {k}")
                if (
                    "engine" in ai
                    and ai["engine"] is not None
                    and not isinstance(ai["engine"], str)
                ):
                    fail(label, "ai.engine must be string")
                if "args" in ai and ai["args"] is not None:
                    args = ai["args"]
                    if not isinstance(args, list) or not all(
                        isinstance(x, str) for x in args
                    ):
                        fail(label, "ai.args must be string array")

    def _validate_task_file(task_file: Path, merged_cfg):
        label = str(task_file)
        if task_file.suffix.lower() != ".md":
            warn(label, "Only .md task files are supported. TOML tasks are deprecated.")
            return

        try:
            text = task_file.read_text(encoding="utf-8")
        except Exception as e:
            fail(label, f"read error: {e}")
            return

        fm, body = _split_markdown_front_matter(text)
        if not fm:
            fail(label, "missing markdown front matter")
            return

        allowed = {
            "name",
            "cron",
            "active",
            "mode",
            "concurrency_policy",
            "timezone",
            "timeout_minutes",
            "allowed_hours",
            "denied_hours",
            "suspended_until",
            "suspended_reason",
            "provider",
            "command",
            "shell",
            "working_dir",
            "parser",
            "parser_args",
            "connector",
            "connectors",
            "notify_connectors",
        }
        for k in fm.keys():
            if k not in allowed:
                warn(label, f"front matter unknown key: {k}")

        if not isinstance(fm.get("name"), str) or not fm.get("name", "").strip():
            fail(label, "front matter name is required")
        _validate_cron(fm.get("cron"), label)

        if not body.strip() and "command" not in fm:
            fail(
                label,
                "markdown task requires either body prompt or 'command' in front matter",
            )
        if (
            body.strip()
            and isinstance(fm.get("command"), str)
            and fm.get("command", "").strip()
        ):
            fail(label, "markdown task cannot define both body prompt and command")

        task_data = {
            "name": fm.get("name"),
            "cron": fm.get("cron"),
            "active": fm.get("active", "true"),
            "mode": fm.get("mode"),
            "concurrency_policy": fm.get("concurrency_policy"),
            "timezone": fm.get("timezone"),
            "timeout_minutes": fm.get("timeout_minutes"),
            "allowed_hours": fm.get("allowed_hours"),
            "denied_hours": fm.get("denied_hours"),
            "prompt": body if body.strip() else None,
            "command": fm.get("command", "").strip()
            if isinstance(fm.get("command"), str)
            else fm.get("command"),
            "shell": fm.get("shell"),
            "working_dir": fm.get("working_dir"),
            "provider": fm.get("provider"),
            "parser": fm.get("parser"),
            "parser_args": fm.get("parser_args"),
            "suspended_until": fm.get("suspended_until"),
            "suspended_reason": fm.get("suspended_reason"),
            "connector": fm.get("connector"),
            "connectors": fm.get("connectors"),
            "notify_connectors": fm.get("notify_connectors"),
        }
        _validate_task_mapping(task_data, f"{label}#task", merged_cfg)

    # 1. Directory
    if KAGE_GLOBAL_DIR.exists():
        ok(f"~/.kage/ {'ディレクトリ' if is_ja else 'Directory'}", str(KAGE_GLOBAL_DIR))
    else:
        fail(
            f"~/.kage/ {'ディレクトリ' if is_ja else 'Directory'} {t_not_found}",
            t_run_onboard,
        )

    # 2. Config
    if KAGE_CONFIG_PATH.exists():
        ok("~/.kage/config.toml", t_exists)
    else:
        warn(f"~/.kage/config.toml {t_not_found}", t_only_default)

    # 3. DB
    if KAGE_DB_PATH.exists():
        ok("kage.db", str(KAGE_DB_PATH))
    else:
        fail(f"kage.db {t_not_found}", t_run_onboard)

    # 3.5. Logs directory
    if KAGE_LOGS_DIR.exists():
        ok("logs dir", str(KAGE_LOGS_DIR))
    else:
        warn(
            "logs dir",
            f"{KAGE_LOGS_DIR} ({'created on first run' if not is_ja else '初回実行時に作成'})",
        )

    # 3.6. Shell completion
    completion_dir = KAGE_GLOBAL_DIR / "completions"
    installed_completion_shells = []
    for shell_name in ("bash", "zsh"):
        if (completion_dir / f"kage.{shell_name}").exists():
            installed_completion_shells.append(shell_name)
    if installed_completion_shells:
        ok("shell completion", ", ".join(installed_completion_shells))
    else:
        warn("shell completion", t_completion_hint)

    # 3.7. TUI backend
    if importlib.util.find_spec("textual"):
        ok("tui backend", "textual")
    else:
        warn("tui backend", t_tui_hint)

    # 3.8. Install migrations
    try:
        from .migrations.runner import (
            InstallMigrationContext,
            discover_install_migrations,
            get_install_migration_state_path,
        )

        migration_state_path = get_install_migration_state_path()
        if migration_state_path.exists():
            try:
                migration_state = json.loads(
                    migration_state_path.read_text(encoding="utf-8")
                )
            except Exception:
                migration_state = {}
        else:
            migration_state = {}
        applied_migrations = migration_state.get("applied", {})
        if not isinstance(applied_migrations, dict):
            applied_migrations = {}

        migration_ctx = InstallMigrationContext(
            from_version=None,
            to_version=_resolve_version(),
            global_dir=KAGE_GLOBAL_DIR,
            db_path=KAGE_DB_PATH,
            logs_dir=KAGE_LOGS_DIR,
            state_path=migration_state_path,
        )
        pending_migrations = [
            migration.migration_id
            for migration in discover_install_migrations()
            if migration.migration_id not in applied_migrations
            and migration.should_run(migration_ctx)
        ]
        applied_count = len(applied_migrations)
        if pending_migrations:
            warn(
                "install migrations",
                f"{len(pending_migrations)} pending / {applied_count} applied ({', '.join(pending_migrations)}) · {t_migrate_hint}",
            )
        else:
            ok(
                "install migrations",
                f"0 pending / {applied_count} applied",
            )
    except Exception as e:
        warn("install migrations", str(e))

    # 4. Projects
    if KAGE_PROJECTS_LIST.exists():
        lines = KAGE_PROJECTS_LIST.read_text().splitlines()
        count = len([line for line in lines if line.strip()])
        ok("projects.list", f"{count} {t_proj_reg}")
    else:
        warn(f"projects.list {t_not_found}", t_run_init)

    # 5. Engine
    cfg = get_global_config()
    if cfg.default_ai_engine:
        ok("default_ai_engine", f'"{cfg.default_ai_engine}"')
    else:
        warn(t_ai_not_set, t_ai_hint)
    if cfg.default_ai_engine == "gemini":
        console.print(
            f"[yellow]{build_gemini_transition_warning('default_ai_engine is set to gemini')}[/yellow]\n"
        )
        warn(
            "gemini cli sunset",
            build_gemini_transition_warning("default_ai_engine is set to gemini"),
        )

    # 6. Provider Checks
    if cfg.default_ai_engine:
        prov = cfg.providers.get(cfg.default_ai_engine)
        if prov:
            cmd_def = cfg.commands.get(prov.command)
            if cmd_def:
                command_label = cmd_def.template[0]
                if prov.command == "antigravity" and command_label == "agy":
                    command_label = "agy (fallback: antigravity)"
                ok(
                    f"providers.{cfg.default_ai_engine}",
                    f"→ commands.{prov.command}: {command_label}",
                )
            else:
                warn(
                    f"providers.{cfg.default_ai_engine}.command = '{prov.command}' {t_prov_undef}",
                    t_prov_cmd_hint,
                )
        else:
            warn(f"providers.{cfg.default_ai_engine} {t_prov_undef}", t_prov_hint)

    if cfg.connectors:
        ok(
            t_connector_artifacts,
            t_connector_artifacts_detail,
        )
        for c_name, c_dict in cfg.connectors.items():
            c_type = c_dict.get("type", "unknown")
            if hasattr(c_type, "unwrap"):
                c_type = c_type.unwrap()
            is_poll = c_dict.get("poll", False)
            is_realtime = c_dict.get("realtime", False)
            if hasattr(is_poll, "unwrap"):
                is_poll = is_poll.unwrap()
            if hasattr(is_realtime, "unwrap"):
                is_realtime = is_realtime.unwrap()
            if is_poll and is_realtime:
                warn(
                    f"connectors.{c_name}",
                    "poll and realtime are both enabled; use only one chat mode to avoid duplicate replies",
                )
            elif is_realtime and c_type == "discord":
                from .connectors.realtime_manager import is_realtime_running

                if is_realtime_running(c_name):
                    ok(
                        f"connectors.{c_name}",
                        "Discord realtime mode configured and listener is running",
                    )
                else:
                    warn(
                        f"connectors.{c_name}",
                        "Discord realtime mode configured but listener is not running;"
                        " it will be started automatically by 'kage cron run'",
                    )
            elif is_realtime:
                warn(
                    f"connectors.{c_name}",
                    f"realtime is not yet implemented for {c_type} connectors",
                )
    else:
        ok(
            t_connector_artifacts,
            t_connector_artifacts_detail_empty,
        )

    # 7. Validate config files and task files
    if KAGE_CONFIG_PATH.exists():
        _validate_config_file(KAGE_CONFIG_PATH, str(KAGE_CONFIG_PATH))

    try:
        from .compiler import compiled_task_indicator
        from .scheduler import get_projects

        projects = get_projects()
    except Exception as e:
        projects = []
        warn("projects discovery", str(e))

    compiled_fresh = 0
    compiled_stale: list[str] = []
    compiled_none = 0
    for proj_dir in sorted(projects):
        ws_cfg = proj_dir / ".kage" / "config.toml"
        if ws_cfg.exists():
            _validate_config_file(ws_cfg, str(ws_cfg))

        tasks_dir = proj_dir / ".kage" / "tasks"
        if not tasks_dir.exists():
            continue

        merged_cfg = get_global_config(workspace_dir=proj_dir)
        for task_file in sorted(list(tasks_dir.glob("*.md"))):
            _validate_task_file(task_file, merged_cfg)
            try:
                from .parser import parse_task_file

                parsed = parse_task_file(task_file)
            except Exception:
                parsed = []
            for _section, task_def in parsed:
                compiled = compiled_task_indicator(task_def, task_file)
                if compiled["state"] == "fresh":
                    compiled_fresh += 1
                elif compiled["state"] == "stale":
                    compiled_stale.append(f"{task_def.name}@{proj_dir.name}")
                elif compiled["state"] == "none":
                    compiled_none += 1

    if compiled_stale:
        warn(
            "compiled locks",
            f"{len(compiled_stale)} stale / {compiled_fresh} fresh / {compiled_none} missing ({', '.join(compiled_stale[:5])}{' ...' if len(compiled_stale) > 5 else ''})",
        )
    else:
        ok(
            "compiled locks",
            f"0 stale / {compiled_fresh} fresh / {compiled_none} missing",
        )

    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 1))
    table.add_column("", width=2)
    table.add_column(t_chk, style="bold")
    table.add_column(t_det, style="dim")
    for icon, label, detail in checks:
        table.add_row(icon, label, detail)

    console.print(table)

    # --- agent / RLS diagnostics ---
    _agent_doctor_checks(console, ok, warn, fail, is_ja=is_ja)

    fails = [c for c in checks if "✘" in c[0]]
    warns = [c for c in checks if "⚠" in c[0]]
    console.print(
        f"\n[bold]{t_res}[/bold] {len(checks)} {('項目中' if is_ja else 'items,')} [red]{len(fails)} {t_err}[/red] / [yellow]{len(warns)} {t_warn}[/yellow]"
    )
    if fails:
        raise typer.Exit(code=1)


def _agent_doctor_checks(console, ok, warn, fail, *, is_ja=False):
    """agent / RLS 系の診断を追加で実行し、別テーブルで表示."""
    import os
    import sqlite3

    from rich.table import Table

    from .agent import BUILTIN_AGENTS, RUN_ID_ENV_VAR, AGENT_NAME_ENV_VAR
    from .config import (
        KAGE_DB_PATH,
        KAGE_PROJECTS_LIST,
        KAGE_CONFIG_PATH,
        get_global_config,
    )

    config = get_global_config()
    local_checks: list[tuple[str, str, str]] = []

    def lok(label, detail=""):
        local_checks.append(("[green]✔[/green]", label, detail))

    def lwarn(label, detail=""):
        local_checks.append(("[yellow]⚠[/yellow]", label, detail))

    def lfail(label, detail=""):
        local_checks.append(("[red]✘[/red]", label, detail))

    # 1. trigger 存在チェック
    if KAGE_DB_PATH.exists():
        try:
            conn = sqlite3.connect(KAGE_DB_PATH)
            triggers = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='trigger'"
                    " AND name IN ('trg_exec_agent_no_update','trg_exec_agent_no_delete')"
                )
            }
            cols = {row[1] for row in conn.execute("PRAGMA table_info(executions)")}
            conn.close()
            if "agent_name" not in cols:
                lfail("executions.agent_name column", "missing")
            elif len(triggers) < 2:
                lwarn(
                    "agent immutable triggers",
                    f"{len(triggers)}/2 present; run `kage migrate install`",
                )
            else:
                lok("agent_isolation_triggers", "agent_name immutable")
        except Exception as e:
            lwarn("agent_isolation_triggers", f"failed: {e}")
    else:
        lok("agent_isolation_triggers", "db not initialized (clean install)")

    # 2. default_agent 解決チェック
    if config.default_agent in BUILTIN_AGENTS:
        lok("default_agent", f"default_agent='{config.default_agent}' (builtin)")
    elif config.default_agent in config.agents:
        lok("default_agent", f"default_agent='{config.default_agent}' (user)")
    else:
        lwarn(
            "default_agent",
            f"'{config.default_agent}' is not defined; falling back to 'kage'",
        )

    # 3. 各 connector の bound agent 表示 / 共有警告
    bound_counts: dict[str, int] = {}
    for _name, c_dict in config.connectors.items():
        bound = c_dict.get("agent")
        if hasattr(bound, "unwrap"):
            bound = bound.unwrap()
        bound = bound or config.default_agent
        bound_counts[bound] = bound_counts.get(bound, 0) + 1

    default_share = bound_counts.get(config.default_agent, 0)
    if default_share > 1 and config.default_agent == "kage":
        lwarn(
            "agent sharing",
            f"{default_share} connectors share the default agent '{config.default_agent}'; "
            f"set distinct 'agent' fields to isolate contexts",
        )
    elif bound_counts:
        for name, count in sorted(bound_counts.items()):
            lok("agent binding", f"agent '{name}': {count} connector(s)")
    else:
        lok("agent binding", "no connectors configured")

    # 4. shell env の KAGE_RUN_ID / KAGE_AGENT_NAME 残留検知
    if os.environ.get(RUN_ID_ENV_VAR) or os.environ.get(AGENT_NAME_ENV_VAR):
        lwarn(
            "agent env in shell",
            "KAGE_RUN_ID or KAGE_AGENT_NAME is set in your shell; kage commands "
            "will be agent-scoped. Unset it for full administrative access.",
        )

    # 5. memory_max_entries 残留
    import tomlkit

    if KAGE_CONFIG_PATH.exists():
        try:
            with open(KAGE_CONFIG_PATH, "r", encoding="utf-8") as f:
                doc = tomlkit.load(f)
            if "memory_max_entries" in doc:
                lwarn(
                    "legacy config",
                    "memory_max_entries is still present; migration 0004 should remove it",
                )
        except Exception:
            pass

    # 6. project ごとの legacy memory dir 発見
    legacy_count = 0
    if KAGE_PROJECTS_LIST.exists():
        try:
            with open(KAGE_PROJECTS_LIST, "r", encoding="utf-8") as f:
                lines = [ln.strip() for ln in f if ln.strip()]
        except Exception:
            lines = []
        for ln in lines:
            mem = Path(ln) / ".kage" / "memory"
            if mem.exists() and mem.is_dir():
                legacy_count += 1
    if legacy_count:
        lok(
            "legacy memory dirs",
            f"{legacy_count} legacy `.kage/memory/` dirs detected (migration 0004 archives them)",
        )

    # 表示
    title = "Agent / Isolation" if not is_ja else "Agent / 分離"
    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 1))
    table.add_column("", width=2)
    table.add_column(f"{title}", style="bold")
    table.add_column("", style="dim")
    for icon, lbl, detail in local_checks:
        table.add_row(icon, lbl, detail)
    console.print(table)


@app.command("version")
def version():
    """Show kage version."""
    typer.echo(_resolve_version())


@migrate_app.command("install")
def migrate_install(
    from_version: Optional[str] = typer.Option(
        None, "--from-version", help="Previously installed version"
    ),
    to_version: Optional[str] = typer.Option(
        None, "--to-version", help="Installed version after update"
    ),
    json_output: bool = typer.Option(False, "--json", help="Print structured JSON"),
):
    """Run install-time migrations."""
    from .migrations.runner import (
        install_migration_results_to_json,
        run_install_migrations,
    )

    results = run_install_migrations(
        from_version=from_version,
        to_version=to_version or _resolve_version(),
    )

    if json_output:
        typer.echo(install_migration_results_to_json(results))
        return

    if not results:
        typer.echo("No install migrations were required.")
        return

    for result in results:
        summary = result.summary
        details = ", ".join(
            f"{key}={value}" for key, value in sorted(result.details.items())
        )
        if details:
            typer.echo(f"Applied {result.migration_id}: {summary} ({details})")
        else:
            typer.echo(f"Applied {result.migration_id}: {summary}")


@app.command("skill")
def skill():
    """Fetch and display the kage agent skill definition (SKILL.md) from GitHub."""
    import urllib.request
    from rich.console import Console
    from rich.markdown import Markdown

    console = Console()
    v = _resolve_version()
    # URL pattern: https://raw.githubusercontent.com/igtm/kage/refs/tags/v0.1.2/skills/kage/SKILL.md
    url = f"https://raw.githubusercontent.com/igtm/kage/refs/tags/v{v}/skills/kage/SKILL.md"

    console.print(f"[dim]Fetching skill definition from: {url}[/dim]")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "kage-cli"})
        with urllib.request.urlopen(req) as response:
            content = response.read().decode("utf-8")
            console.print(Markdown(content))
    except Exception as e:
        console.print(f"[red]Error fetching skill definition:[/red] {e}")
        console.print(
            "[yellow]Hint:[/yellow] Make sure you are using a tagged version and have internet access."
        )


@connector_app.command("setup")
def connector_setup(
    ctype: Optional[str] = typer.Argument(
        None, help="Connector type (discord, slack, telegram)"
    ),
):
    """Show setup instructions for a connector type."""
    from rich.console import Console
    from rich.panel import Panel
    from rich.markdown import Markdown

    console = Console()

    if not ctype:
        console.print("[bold]Available Connector Types:[/bold]")
        console.print("- [bold magenta]discord[/bold magenta]")
        console.print("- [bold blue]slack[/bold blue]")
        console.print("- [bold cyan]telegram[/bold cyan]")
        console.print(
            "\nRun [bold]kage connector setup discord[/bold] for instructions."
        )
        return

    ctype = ctype.lower()
    if ctype == "discord":
        text = """
# Discord Connector Setup Guide

1. **Create Application**: Go to [Discord Developer Portal](https://discord.com/developers/applications) and click **"New Application"**.
2. **Setup Bot**:
   - Go to the **"Bot"** tab.
   - Click **"Reset Token"** to get your **Bot Token**.
   - **CRITICAL**: Scroll down to "Privileged Gateway Intents" and enable **"Message Content Intent"**.
3. **Invite Bot**:
   - Go to **"OAuth2" -> "URL Generator"**.
   - Select scopes: `bot`.
   - Select bot permissions: `Send Messages`, `Read Messages/View Channels`, `Read Message History`.
   - Copy the generated URL and open it in your browser to invite the bot to your server.
4. **Get Channel ID**:
   - In Discord (User Settings -> Advanced), enable **"Developer Mode"**.
   - Right-click the target channel and select **"Copy Channel ID"**.
5. **Config**: Add the following to your `.kage/config.toml`:

```toml
[connectors.my_discord]
type = "discord"
# Choose ONE of the following chat modes:
poll = true      # 1-minute polling (simpler, no Gateway required)
# realtime = true  # WebSocket-based instant replies with typing indicator
bot_token = "YOUR_BOT_TOKEN"
channel_id = "YOUR_CHANNEL_ID"
system_prompt = "Optional additional instructions for this connector"
agent = "kage"            # bind to an [agents.<name>] table to isolate context
```

> **⚠️ Security**: `poll = true` or `realtime = true` allows anyone in the channel to interact with the AI, which has full access to your PC. Only enable one of them, and only in private/trusted channels. Task notifications (via `notify_connectors`) work even with both flags set to `false`.
> **Realtime**: Run `kage connector realtime start` to start the long-lived WebSocket listener. The bot will show a typing indicator and reply immediately when a message arrives. If you have `kage cron run` installed in your crontab, realtime listeners are started/stopped automatically within one minute of changing the config.
> **Artifacts**: Connector-aware runs export `KAGE_ARTIFACT_DIR` as a workspace-local staging directory (for example `.kage/tmp/connector-artifacts/<run_id>`). Incoming connector attachments are downloaded to `KAGE_ARTIFACT_DIR/incoming` for that run, and Discord, Slack, and Telegram upload every top-level file left in `KAGE_ARTIFACT_DIR` with the text reply or task notification, so leave only the intended final deliverables there and delete source Markdown/Marp/HTML, downloaded images, and other intermediate assets unless the user explicitly asked for them.
"""
        console.print(
            Panel(Markdown(text), title="Discord Setup", border_style="magenta")
        )
    elif ctype == "slack":
        text = """
# Slack Connector Setup Guide

1. **Create App**: Go to [Slack API Apps](https://api.slack.com/apps) and click **"Create New App"** (From scratch).
2. **Permissions**:
   - Go to **"OAuth & Permissions"**.
   - Scroll to **"Bot Token Scopes"** and add:
     - `channels:history`
     - `files:read`
     - `chat:write`
     - `files:write`
     - `groups:history` (if using private channels)
3. **Install**:
   - Scroll up and click **"Install to Workspace"**.
   - Copy the **"Bot User OAuth Token"** (starts with `xoxb-`).
4. **Get Channel ID**:
   - In Slack, right-click the channel name -> **"View channel details"**.
   - The Channel ID is at the very bottom (e.g., `C1234567890`).
5. **Invite Bot**: In the target channel, type `/invite @YourBotName`.
6. **Config**: Add the following to your `.kage/config.toml`:

```toml
[connectors.my_slack]
type = "slack"
poll = true   # ⚠️ Only enable in private/trusted channels (grants AI access to your PC)
bot_token = "xoxb-YOUR_TOKEN"
channel_id = "YOUR_CHANNEL_ID"
system_prompt = "Optional additional instructions for this connector"
agent = "kage"            # bind to an [agents.<name>] table to isolate context
```

> **⚠️ Security**: `poll = true` allows anyone in the channel to interact with the AI, which has full access to your PC. Task notifications (via `notify_connectors`) work even with `poll = false`.
> **Artifacts**: Connector-aware runs export `KAGE_ARTIFACT_DIR` as a workspace-local staging directory (for example `.kage/tmp/connector-artifacts/<run_id>`). Incoming connector attachments are downloaded to `KAGE_ARTIFACT_DIR/incoming` for that run, and Slack uploads every top-level file left in `KAGE_ARTIFACT_DIR` with the text reply or task notification, so leave only the intended final deliverables there and delete source Markdown/Marp/HTML, downloaded images, and other intermediate assets unless the user explicitly asked for them.
"""
        console.print(Panel(Markdown(text), title="Slack Setup", border_style="blue"))
    elif ctype == "telegram":
        text = """
# Telegram Connector Setup Guide

1. **Create Bot**: Open Telegram and message [@BotFather](https://t.me/BotFather). Send `/newbot` and follow the prompts to create your bot.
2. **Get Bot Token**: BotFather will give you a **Bot Token** (e.g., `123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11`).
3. **Get Chat ID**:
   - Add the bot to your group or start a DM with the bot.
   - Send a message to the bot/group.
   - Open `https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates` in your browser.
   - Find `"chat":{"id":...}` — this is your **Chat ID** (may be negative for groups).
4. **Config**: Add the following to your `.kage/config.toml`:

```toml
[connectors.my_telegram]
type = "telegram"
poll = true   # ⚠️ Only enable in private/trusted chats (grants AI access to your PC)
bot_token = "YOUR_BOT_TOKEN"
chat_id = "YOUR_CHAT_ID"
system_prompt = "Optional additional instructions for this connector"
agent = "kage"            # bind to an [agents.<name>] table to isolate context
```

> **⚠️ Security**: `poll = true` allows anyone in the chat to interact with the AI, which has full access to your PC. Task notifications (via `notify_connectors`) work even with `poll = false`.
> **Artifacts**: Connector-aware runs export `KAGE_ARTIFACT_DIR` as a workspace-local staging directory (for example `.kage/tmp/connector-artifacts/<run_id>`). Incoming connector attachments are downloaded to `KAGE_ARTIFACT_DIR/incoming` for that run, and Telegram uploads every top-level file left in `KAGE_ARTIFACT_DIR` with the text reply or task notification, so leave only the intended final deliverables there and delete source Markdown/Marp/HTML, downloaded images, and other intermediate assets unless the user explicitly asked for them.
"""
        console.print(
            Panel(Markdown(text), title="Telegram Setup", border_style="cyan")
        )
    else:
        console.print(f"[red]Unknown connector type: {ctype}[/red]")
        console.print("Available types: discord, slack, telegram")


if __name__ == "__main__":
    app()


@connector_app.command("list")
def connector_list():
    """List all configured connectors."""
    from .config import get_global_config
    from rich.console import Console
    from rich.table import Table

    console = Console()
    config = get_global_config()

    if not config.connectors:
        console.print("[yellow]No connectors configured.[/yellow]")
        console.print("Add [[connectors.name]] blocks to your config.toml.")
        return

    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Name", style="bold")
    table.add_column("Type")
    table.add_column("Agent")
    table.add_column("Status")
    table.add_column("Details")

    from .agent import get_current_agent_name

    current_agent = get_current_agent_name()

    for name, c_dict in config.connectors.items():
        c_type = c_dict.get("type", "unknown")
        # Handle tomlkit boolean types or standard ones
        is_polling = c_dict.get("poll", False)
        is_realtime = c_dict.get("realtime", False)
        if hasattr(is_polling, "unwrap"):
            is_polling = is_polling.unwrap()
        if hasattr(is_realtime, "unwrap"):
            is_realtime = is_realtime.unwrap()

        # agent 名の解決
        bound = c_dict.get("agent")
        if hasattr(bound, "unwrap"):
            bound = bound.unwrap()
        agent_name = bound or config.default_agent
        # AI 実行中かつ自 agent でなければ名前のみマスク
        if current_agent is not None and agent_name != current_agent:
            agent_name = "[dim]<other agent>[/dim]"

        status_parts = []
        if is_polling:
            status_parts.append("[green]Poll ON[/green]")
        if is_realtime:
            status_parts.append("[magenta]Realtime ON[/magenta]")
        status = " ".join(status_parts) if status_parts else "[dim]Inactive[/dim]"

        details = []
        if c_type == "discord":
            details.append(f"Channel: {c_dict.get('channel_id', 'N/A')}")
            if c_dict.get("user_id"):
                details.append(f"User Filter: {str(c_dict.get('user_id'))}")
        elif c_type == "slack":
            details.append(f"Channel: {c_dict.get('channel_id', 'N/A')}")
            if c_dict.get("user_id"):
                details.append(f"User Filter: {str(c_dict.get('user_id'))}")
        elif c_type == "telegram":
            details.append(f"Chat: {c_dict.get('chat_id', 'N/A')}")
            if c_dict.get("user_id"):
                details.append(f"User Filter: {str(c_dict.get('user_id'))}")

        table.add_row(name, c_type, agent_name, status, ", ".join(details))

    console.print(table)


@connector_app.command("poll")
def connector_poll():
    """Poll and reply messages for connectors with poll=true."""
    from .connectors.runner import run_connectors
    from rich.console import Console

    console = Console()
    console.print("[bold blue]Polling connectors...[/bold blue]")
    try:
        run_connectors()
        console.print("[green]✔ Polling completed.[/green]")
    except Exception as e:
        console.print(f"[red]✘ Polling failed: {e}[/red]")
    # run_connectors 内部で agent filter 済み


realtime_app = typer.Typer(
    help="Manage long-lived realtime connector listeners (Discord only for now)"
)
connector_app.add_typer(realtime_app, name="realtime")


def _resolve_realtime_names(name: Optional[str]) -> list[str]:
    """Return a list of realtime connector names to operate on.

    If ``name`` is given, validate it exists and has realtime=true.
    Otherwise return all connectors with realtime=true.
    """
    from .connectors.runner import get_connector
    from .connectors.realtime_manager import get_realtime_connector_names

    if name:
        connector = get_connector(name)
        if not connector:
            print(f"[kage] Connector '{name}' not found.")
            raise typer.Exit(1)
        if not connector.config.realtime:
            print(f"[kage] Connector '{name}' does not have realtime=true.")
            raise typer.Exit(1)
        return [name]
    names = get_realtime_connector_names()
    return names


def _guard_realtime_for_agent(names: list[str]) -> list[str]:
    """現 agent 配下の connector だけ残す。人間は全件。"""
    from .agent import get_current_agent_name
    from .config import get_global_config

    config = get_global_config()
    current = get_current_agent_name()
    if current is None:
        return names
    kept: list[str] = []
    for n in names:
        c_dict = config.connectors.get(n, {})
        bound = c_dict.get("agent")
        if hasattr(bound, "unwrap"):
            bound = bound.unwrap()
        bound = bound or config.default_agent
        if bound == current:
            kept.append(n)
        else:
            print(
                f"[kage] Skipping connector '{n}' (bound to agent '{bound}', "
                f"current agent '{current}')."
            )
    return kept


@realtime_app.command("run")
def realtime_run(
    name: Optional[str] = typer.Argument(
        None,
        help="Connector name to run in the foreground (runs all realtime connectors if omitted)",
    ),
):
    """Run realtime listener(s) in the foreground (for debugging / manual use)."""
    from .connectors.runner import get_connector, run_realtime_connectors

    if name:
        connector = get_connector(name)
        if not connector:
            print(f"[kage] Connector '{name}' not found.")
            raise typer.Exit(1)
        if not connector.config.realtime:
            print(f"[kage] Connector '{name}' does not have realtime=true.")
            raise typer.Exit(1)
        try:
            connector.realtime()
        except KeyboardInterrupt:
            print(f"[kage] Realtime listener for '{name}' stopped.")
        return

    try:
        run_realtime_connectors()
    except KeyboardInterrupt:
        print("[kage] Realtime connectors stopped.")


@realtime_app.command("start")
def realtime_start(
    name: Optional[str] = typer.Argument(
        None,
        help="Connector name to start (starts all realtime connectors if omitted)",
    ),
):
    """Start detached realtime listener(s)."""
    from .connectors.realtime_manager import start_realtime_connector

    names = _resolve_realtime_names(name)
    if not names:
        print("[kage] No connectors have realtime=true.")
        raise typer.Exit(0)

    for n in names:
        started, msg = start_realtime_connector(n)
        print(f"[kage] {msg}")


@realtime_app.command("stop")
def realtime_stop(
    name: Optional[str] = typer.Argument(
        None,
        help="Connector name to stop (stops all realtime listeners if omitted)",
    ),
):
    """Stop realtime listener(s)."""
    from .connectors.realtime_manager import (
        get_realtime_status,
        stop_realtime_connector,
    )

    if name:
        names = [name]
    else:
        names = [s["name"] for s in get_realtime_status() if s["running"]]

    if not names:
        print("[kage] No realtime listeners are running.")
        raise typer.Exit(0)

    for n in names:
        stopped, msg = stop_realtime_connector(n)
        print(f"[kage] {msg}")


@realtime_app.command("restart")
def realtime_restart(
    name: Optional[str] = typer.Argument(
        None,
        help="Connector name to restart (restarts all realtime listeners if omitted)",
    ),
):
    """Restart realtime listener(s)."""
    from .connectors.realtime_manager import restart_realtime_connector

    names = _resolve_realtime_names(name)
    if not names:
        print("[kage] No connectors have realtime=true.")
        raise typer.Exit(0)

    for n in names:
        _, msg = restart_realtime_connector(n)
        print(f"[kage] {msg}")


@realtime_app.command("status")
def realtime_status():
    """Show running realtime listeners."""
    from .connectors.realtime_manager import get_realtime_status
    from rich.console import Console
    from rich.table import Table

    console = Console()
    status = get_realtime_status()

    if not status:
        console.print("[yellow]No realtime connectors configured or running.[/yellow]")
        return

    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Name")
    table.add_column("Status")
    table.add_column("PID")
    table.add_column("Log File")

    for item in status:
        if item["running"]:
            state = "[green]running[/green]"
        elif item["configured"]:
            state = "[yellow]configured but not running[/yellow]"
        else:
            state = "[dim]not configured[/dim]"
        table.add_row(
            item["name"],
            state,
            str(item["pid"] or "-"),
            item["log_file"],
        )

    console.print(table)


# ---------------------------------------------------------------------------
# kage agent: list / show / create
# ---------------------------------------------------------------------------


def _all_agent_metas(config):
    """既知の agent 一覧を (name, source) 形式で返す。BUILTIN ('kage') を含む。"""
    from .agent import BUILTIN_AGENTS

    metas = []
    for name in BUILTIN_AGENTS:
        metas.append((name, "builtin"))
    for name, agent in config.agents.items():
        if name in {m[0] for m in metas}:
            continue
        metas.append((name, "user"))
    return metas


@agent_app.command("list")
def agent_list():
    """List configured agents. AI runs only see the current agent; humans see all."""
    from .agent import get_current_agent_name
    from .config import get_global_config
    from rich.console import Console
    from rich.table import Table

    console = Console()
    config = get_global_config()
    current = get_current_agent_name()

    # connector → agent binding count
    binding_counts: dict[str, int] = {}
    for conn_name, c_dict in config.connectors.items():
        bound = c_dict.get("agent")
        if hasattr(bound, "unwrap"):
            bound = bound.unwrap()
        bound = bound or config.default_agent
        binding_counts[bound] = binding_counts.get(bound, 0) + 1

    metas = _all_agent_metas(config)
    if current is not None:
        metas = [m for m in metas if m[0] == current]

    if not metas:
        console.print(
            f"[yellow]No agents visible (current agent: '{current}').[/yellow]"
        )
        return

    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Name", style="bold")
    table.add_column("Source")
    table.add_column("Connectors")
    table.add_column("Projects")

    for name, source in metas:
        agent = config.agents.get(name)
        projects = 0
        if agent:
            projects = len(agent.extra_project_dirs) + (
                1 if agent.default_working_dir else 0
            )
        table.add_row(
            name,
            source,
            str(binding_counts.get(name, 0)),
            str(projects),
        )

    console.print(table)


@agent_app.command("show")
def agent_show(
    name: str = typer.Argument(..., help="Agent name to inspect."),
):
    """Show an agent's persona, system_prompt, projects and connectors."""
    from .agent import assert_agent_command_allowed
    from .config import get_global_config
    from rich.console import Console

    console = Console()
    config = get_global_config()
    assert_agent_command_allowed(config, name)

    from .agent import BUILTIN_AGENTS

    builtin = BUILTIN_AGENTS.get(name)
    agent = config.agents.get(name)
    if not builtin and not agent:
        console.print(f"[red]Unknown agent: {name}[/red]")
        raise typer.Exit(1)

    console.print(f"[bold]Agent:[/bold] {name}")
    console.print(
        "[dim]Source:[/dim] "
        + ("builtin (immutable)" if builtin and not agent else "user config")
    )
    if agent:
        if agent.system_prompt:
            console.print("\n[bold]system_prompt:[/bold]")
            console.print(agent.system_prompt)
        if agent.default_working_dir:
            console.print(
                f"\n[bold]default_working_dir:[/bold] {agent.default_working_dir}"
            )
        if agent.extra_project_dirs:
            console.print("\n[bold]extra_project_dirs:[/bold]")
            for p in agent.extra_project_dirs:
                console.print(f"  - {p}")
        if agent.provider:
            console.print(f"\n[bold]provider:[/bold] {agent.provider}")
    connectors = []
    for conn_name, c_dict in config.connectors.items():
        bound = c_dict.get("agent")
        if hasattr(bound, "unwrap"):
            bound = bound.unwrap()
        if (bound or config.default_agent) == name:
            connectors.append(conn_name)
    if connectors:
        console.print("\n[bold]Bound connectors:[/bold]")
        for c in connectors:
            console.print(f"  - {c}")


@agent_app.command("create")
def agent_create(
    name: str = typer.Argument(..., help="Agent name (lowercase, hyphens)."),
    system_prompt: Optional[str] = typer.Option(
        None, "--system-prompt", help="Inline systemPrompt text."
    ),
    system_prompt_file: Optional[str] = typer.Option(
        None,
        "--system-prompt-file",
        help="Read system_prompt from this file (use '-' for stdin).",
    ),
    working_dir: Optional[str] = typer.Option(
        None, "--working-dir", help="Default working directory (project root)."
    ),
    provider: Optional[str] = typer.Option(
        None, "--provider", help="Override provider name for this agent."
    ),
    extra_project_dir: Optional[list[str]] = typer.Option(
        None,
        "--extra-project-dir",
        help="Additional project dir owned by this agent (repeatable).",
    ),
    scope_choice: Optional[str] = typer.Option(
        "project",
        "--scope",
        help="Where to write the agent config: 'global' or 'project'.",
    ),
):
    """Create a new agent entry in config.toml. Refuses 'kage' (builtin)."""
    from .agent import BUILTIN_AGENTS, assert_not_in_agent_run
    from .config import set_config_value

    assert_not_in_agent_run("create an agent")
    if name in BUILTIN_AGENTS:
        typer.echo(f"Error: '{name}' is a built-in agent and cannot be created.")
        raise typer.Exit(1)
    if not name.replace("-", "").isalnum() or not name.lower() == name:
        typer.echo("Error: agent name must be lowercase [a-z0-9-].")
        raise typer.Exit(1)

    sp = system_prompt
    if system_prompt_file:
        if system_prompt_file == "-":
            import sys

            sp = sys.stdin.read()
        else:
            sp = Path(system_prompt_file).read_text(encoding="utf-8")

    scope = "global" if scope_choice == "global" else "project"
    key_prefix = f"agents.{name}"
    if sp is not None:
        set_config_value(f"{key_prefix}.system_prompt", sp, scope=scope)
    if working_dir:
        set_config_value(f"{key_prefix}.default_working_dir", working_dir, scope=scope)
    if provider:
        set_config_value(f"{key_prefix}.provider", provider, scope=scope)
    for extra in extra_project_dir or []:
        set_config_value(f"{key_prefix}.extra_project_dirs", extra, scope=scope)
    typer.echo(
        f"Created agent '{name}' in {scope} config. "
        f'Bind a connector with `agent = "{name}"`.'
    )


# ---------------------------------------------------------------------------
# kage memory: list / show / write / delete / search
# ---------------------------------------------------------------------------


def _resolve_memory_agent() -> str:
    """memory CLI で操作対象となる agent を解決。
    AI 実行中なら現 agent、それ以外は引数 --agent 必須 or 'kage'。
    """
    from .agent import get_current_agent_name

    current = get_current_agent_name()
    if current:
        return current
    return "kage"  # 人間実行時のデフォルト


@memory_app.command("list")
def memory_list(
    agent: Optional[str] = typer.Option(
        None, "--agent", help="Agent name (human use only). Defaults to current agent."
    ),
):
    """List memory topics of an agent."""
    from .agent import get_current_agent_name
    from .memory import list_memories
    from rich.console import Console
    from rich.table import Table

    current = get_current_agent_name()
    if agent and current and agent != current:
        typer.echo(
            f"Error: cannot list memory of agent '{agent}' from within '{current}'."
        )
        raise typer.Exit(1)
    target = agent or current or "kage"

    metas = list_memories(target)
    console = Console()
    if not metas:
        console.print(f"[yellow]No memories for agent '{target}'.[/yellow]")
        return

    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Slug", style="bold")
    table.add_column("Description")
    table.add_column("Updated", style="dim")
    for m in metas:
        table.add_row(m.slug, m.description, m.updated_at)
    console.print(table)


@memory_app.command("show")
def memory_show(
    slug: str = typer.Argument(..., help="Memory slug to read."),
    agent: Optional[str] = typer.Option(
        None, "--agent", help="Agent name (human use only)."
    ),
):
    """Print the body of a memory."""
    from .agent import get_current_agent_name
    from .memory import read_memory

    current = get_current_agent_name()
    if agent and current and agent != current:
        typer.echo(
            "Error: cannot access other agents' memory from within an agent run."
        )
        raise typer.Exit(1)
    target = agent or current or "kage"

    body = read_memory(target, slug)
    if body is None:
        typer.echo(f"Memory '{slug}' not found for agent '{target}'.")
        raise typer.Exit(1)
    typer.echo(body)


@memory_app.command("write")
def memory_write(
    slug: str = typer.Argument(..., help="Memory slug (lowercase, hyphens)."),
    description: str = typer.Option(..., "--description", help="Short summary."),
    file: Optional[str] = typer.Option(
        None, "--file", help="Read body from this file ('-' for stdin)."
    ),
    agent: Optional[str] = typer.Option(
        None, "--agent", help="Agent name (human use only)."
    ),
):
    """Create or overwrite a memory. Body is read from stdin unless --file."""
    import sys

    from .agent import get_current_agent_name
    from .memory import write_memory

    current = get_current_agent_name()
    if agent and current and agent != current:
        typer.echo(
            "Error: cannot write to another agent's memory from within an agent run."
        )
        raise typer.Exit(1)
    target = agent or current or "kage"

    if file:
        if file == "-":
            content = sys.stdin.read()
        else:
            content = Path(file).read_text(encoding="utf-8")
    else:
        try:
            content = sys.stdin.read()
        except Exception:
            typer.echo("Error: body must be provided via --file or stdin.")
            raise typer.Exit(1)

    path = write_memory(target, slug, description, content)
    typer.echo(f"Wrote memory '{slug}' for agent '{target}' -> {path}")


@memory_app.command("delete")
def memory_delete(
    slug: str = typer.Argument(..., help="Memory slug to delete."),
    force: bool = typer.Option(False, "--force", help="Skip confirmation."),
    agent: Optional[str] = typer.Option(
        None, "--agent", help="Agent name (human use only)."
    ),
):
    """Delete a memory."""
    from .agent import get_current_agent_name
    from .memory import delete_memory

    current = get_current_agent_name()
    if agent and current and agent != current:
        typer.echo(
            "Error: cannot delete another agent's memory from within an agent run."
        )
        raise typer.Exit(1)
    target = agent or current or "kage"

    if not force:
        confirm = typer.confirm(f"Delete memory '{slug}' of agent '{target}'?")
        if not confirm:
            raise typer.Abort()
    if delete_memory(target, slug):
        typer.echo(f"Deleted memory '{slug}' of agent '{target}'.")
    else:
        typer.echo(f"Memory '{slug}' not found for agent '{target}'.")
        raise typer.Exit(1)


@memory_app.command("search")
def memory_search(
    query: str = typer.Argument(..., help="Substring to search (case-insensitive)."),
    agent: Optional[str] = typer.Option(
        None, "--agent", help="Agent name (human use only)."
    ),
):
    """Search memory bodies for a substring."""
    from .agent import get_current_agent_name
    from .memory import search_memories
    from rich.console import Console

    current = get_current_agent_name()
    if agent and current and agent != current:
        typer.echo(
            "Error: cannot search another agent's memory from within an agent run."
        )
        raise typer.Exit(1)
    target = agent or current or "kage"

    hits = search_memories(target, query)
    console = Console()
    if not hits:
        console.print(f"[yellow]No hits for '{query}' in agent '{target}'.[/yellow]")
        return
    for slug, lineno, line in hits:
        console.print(f"[bold]{slug}[/bold]:{lineno}: {line}")
