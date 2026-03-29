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

project_app = typer.Typer(help="Manage registered projects")
app.add_typer(project_app, name="project")

connector_app = typer.Typer(
    help="Manage chat connectors (Discord, Slack, Telegram, etc.), including Discord artifact uploads"
)
app.add_typer(connector_app, name="connector")

migrate_app = typer.Typer(help="Run install/data migrations")
app.add_typer(migrate_app, name="migrate")

runs_app = typer.Typer(
    help="View and manage execution runs",
    invoke_without_command=True,
)
app.add_typer(runs_app, name="runs")

completion_app = typer.Typer(
    help="Shell completion helpers, including task and run ID suggestions"
)
app.add_typer(completion_app, name="completion")


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
    from rich.console import Console
    from pathlib import Path

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
            table.add_row(
                _project_short_name(str(proj_dir)),
                t.name,
                status,
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
    from rich.console import Console
    import re

    console = Console()
    projects = get_projects()
    found_any = False

    for proj_dir in projects:
        tasks = load_project_tasks(proj_dir)
        for task_file, local_task in tasks:
            t = local_task.task
            if all_tasks or t.name == name:
                found_any = True
                # ファイルを直接書き換える
                content = task_file.read_text(encoding="utf-8")

                # Markdown の Front Matter を書き換える
                # シンプルに正規表現で active: ... を置換
                new_val = "true" if active else "false"
                if "active:" in content:
                    content = re.sub(
                        r"active:\s*(true|false)", f"active: {new_val}", content
                    )
                else:
                    # active が無い場合は cron: の後に追加
                    content = re.sub(
                        r"(cron:.*?\n)", rf"\1active: {new_val}\n", content
                    )

                task_file.write_text(content, encoding="utf-8")
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
    from rich.console import Console
    from rich.panel import Panel

    console = Console()
    proj_dir, task_file, task = _resolve_named_task(name, project=project)
    details = [
        f"[bold]Name:[/bold]           {task.name}",
        f"[bold]Schedule:[/bold]       {task.cron}",
        f"[bold]Mode:[/bold]           {task.mode}",
        f"[bold]Concurrency:[/bold]    {task.concurrency_policy}",
        f"[bold]Timezone:[/bold]       {task.timezone or 'global'}",
        f"[bold]Allowed Hours:[/bold]  {task.allowed_hours or 'any'}",
        f"[bold]Denied Hours:[/bold]   {task.denied_hours or 'none'}",
        f"[bold]Project:[/bold]        {proj_dir}",
        f"[bold]File:[/bold]           {task_file}",
    ]
    compiled = compiled_task_status(task, task_file)
    if task.prompt:
        merged_cfg = get_global_config(workspace_dir=proj_dir)
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
):
    """Run a specific task immediately (ignores schedule)."""
    from .executor import execute_task
    from rich.console import Console

    console = Console()
    proj_dir, task_file, task = _resolve_named_task(name, project=project)
    console.print(f"[cyan]Running task:[/cyan] [bold]{name}[/bold] in {proj_dir}")
    execute_task(proj_dir, task, task_file=task_file)
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
):
    """Run a specific task immediately."""
    task_run(name=name, project=project)


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
        ..., help="Setting key (e.g., 'default_ai_engine' or 'providers.codex.model')"
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

    if is_global and is_local:
        raise typer.BadParameter("--global and --local cannot be used together")

    scope = "global" if is_global else "local" if is_local else "project"
    set_config_value(key, value, is_global=is_global, scope=scope)


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

    ws_dir = Path(workspace).resolve() if workspace else Path.cwd()
    ws_cfg_path = ws_dir / ".kage" / "config.toml"
    ws_local_cfg_path = ws_dir / ".kage" / "config.local.toml"
    cfg = get_global_config(workspace_dir=ws_dir)

    console = Console()
    console.print("\n[bold cyan]kage config-show[/bold cyan]\n")

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
    from .config import (
        get_global_config,
        KAGE_GLOBAL_DIR,
        KAGE_CONFIG_PATH,
        KAGE_PROJECTS_LIST,
        KAGE_DB_PATH,
        KAGE_LOGS_DIR,
    )

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
        "AIタスクを使う場合: kage config default_ai_engine opencode --global"
        if is_ja
        else "If using AI tasks: run 'kage config default_ai_engine opencode --global'"
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
        "Connector-aware runs export KAGE_ARTIFACT_DIR as a workspace-local staging directory. Discord uploads files from it directly; Slack/Telegram currently send text only and record skipped attachments."
        if not is_ja
        else "connector を使う run では workspace 内 staging directory として KAGE_ARTIFACT_DIR を export します。Discord はその file を直接 upload し、Slack / Telegram は text のみ送って未送信添付を記録します。"
    )
    t_connector_artifacts_detail_empty = (
        "KAGE_ARTIFACT_DIR is created only for runs that send connector messages."
        if not is_ja
        else "KAGE_ARTIFACT_DIR は connector へ送信する run でのみ作られます。"
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
            "memory_max_entries",
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
            "memory_max_entries": (int,),
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
            "prompt": body if body.strip() else None,
            "command": fm.get("command", "").strip()
            if isinstance(fm.get("command"), str)
            else fm.get("command"),
            "shell": fm.get("shell"),
            "working_dir": fm.get("working_dir"),
            "provider": fm.get("provider"),
            "parser": fm.get("parser"),
            "parser_args": fm.get("parser_args"),
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

    # 6. Provider Checks
    if cfg.default_ai_engine:
        prov = cfg.providers.get(cfg.default_ai_engine)
        if prov:
            cmd_def = cfg.commands.get(prov.command)
            if cmd_def:
                ok(
                    f"providers.{cfg.default_ai_engine}",
                    f"→ commands.{prov.command}: {cmd_def.template[0]}",
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

    fails = [c for c in checks if "✘" in c[0]]
    warns = [c for c in checks if "⚠" in c[0]]
    console.print(
        f"\n[bold]{t_res}[/bold] {len(checks)} {('項目中' if is_ja else 'items,')} [red]{len(fails)} {t_err}[/red] / [yellow]{len(warns)} {t_warn}[/yellow]"
    )
    if fails:
        raise typer.Exit(code=1)


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
poll = true   # ⚠️ Only enable in private/trusted channels (grants AI access to your PC)
bot_token = "YOUR_BOT_TOKEN"
channel_id = "YOUR_CHANNEL_ID"
system_prompt = "Optional additional instructions for this connector"
```

> **⚠️ Security**: `poll = true` allows anyone in the channel to interact with the AI, which has full access to your PC. Task notifications (via `notify_connectors`) work even with `poll = false`.
> **Artifacts**: Connector-aware runs export `KAGE_ARTIFACT_DIR` as a workspace-local staging directory (for example `.kage/tmp/connector-artifacts/<run_id>`). Write top-level files there to have Discord upload them with the text reply or task notification.
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
     - `chat:write`
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
```

> **⚠️ Security**: `poll = true` allows anyone in the channel to interact with the AI, which has full access to your PC. Task notifications (via `notify_connectors`) work even with `poll = false`.
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
```

> **⚠️ Security**: `poll = true` allows anyone in the chat to interact with the AI, which has full access to your PC. Task notifications (via `notify_connectors`) work even with `poll = false`.
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
    table.add_column("Status")
    table.add_column("Details")

    for name, c_dict in config.connectors.items():
        c_type = c_dict.get("type", "unknown")
        # Handle tomlkit boolean types or standard ones
        is_polling = c_dict.get("poll", False)
        if hasattr(is_polling, "unwrap"):
            is_polling = is_polling.unwrap()

        status = "[green]Poll ON[/green]" if is_polling else "[dim]Poll OFF[/dim]"

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

        table.add_row(name, c_type, status, ", ".join(details))

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
