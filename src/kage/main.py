import typer
from . import config as config_mod, daemon, db
from typing import Optional
from importlib import metadata

app = typer.Typer(
    help="kage - AI Native Cron Task Runner",
    add_completion=False,
)

cron_app = typer.Typer(help="OS-level scheduler (cron/launchd) management")
app.add_typer(cron_app, name="cron")

task_app = typer.Typer(help="Manage kage tasks")
app.add_typer(task_app, name="task")

project_app = typer.Typer(help="Manage registered projects")
app.add_typer(project_app, name="project")

connector_app = typer.Typer(help="Manage chat connectors (Discord, Slack, Telegram, etc.)")
app.add_typer(connector_app, name="connector")


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
    """List all registered tasks and their status (ON/OFF)."""
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
        tasks = load_project_tasks(proj_dir)
        for toml_file, local_task in tasks:
            t = local_task.task
            task_type = "AI Prompt" if t.prompt else "Shell"
            provider_info = (
                t.provider or (t.ai.engine if t.ai and t.ai.engine else "")
                if t.prompt
                else (t.command or "")[:40]
            )
            status = "[green]ON[/green]" if t.active else "[red]OFF[/red]"
            table.add_row(
                str(proj_dir),
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
    name: Optional[str] = typer.Argument(None, help="Task name to enable"),
    all_tasks: bool = typer.Option(False, "--all", help="Enable all tasks"),
):
    """Enable a specific task or all tasks."""
    if not name and not all_tasks:
        typer.echo("Error: Must specify a task name or use --all")
        raise typer.Exit(1)
    _set_task_active_state(name, True, all_tasks)


@task_app.command("off")
def task_off(
    name: Optional[str] = typer.Argument(None, help="Task name to disable"),
    all_tasks: bool = typer.Option(False, "--all", help="Disable all tasks"),
):
    """Disable a specific task or all tasks."""
    if not name and not all_tasks:
        typer.echo("Error: Must specify a task name or use --all")
        raise typer.Exit(1)
    _set_task_active_state(name, False, all_tasks)


@task_app.command("show")
def task_show(name: str = typer.Argument(..., help="Task name to show details for")):
    """Show details of a specific task."""
    from .scheduler import get_projects
    from .parser import load_project_tasks
    from rich.console import Console
    from rich.panel import Panel

    console = Console()
    projects = get_projects()

    for proj_dir in projects:
        for toml_file, local_task in load_project_tasks(proj_dir):
            t = local_task.task
            if t.name == name:
                details = [
                    f"[bold]Name:[/bold]           {t.name}",
                    f"[bold]Schedule:[/bold]       {t.cron}",
                    f"[bold]Mode:[/bold]           {t.mode}",
                    f"[bold]Concurrency:[/bold]    {t.concurrency_policy}",
                    f"[bold]Timezone:[/bold]       {t.timezone or 'global'}",
                    f"[bold]Allowed Hours:[/bold]  {t.allowed_hours or 'any'}",
                    f"[bold]Denied Hours:[/bold]   {t.denied_hours or 'none'}",
                    f"[bold]Project:[/bold]        {proj_dir}",
                    f"[bold]File:[/bold]           {toml_file}",
                ]
                if t.prompt:
                    details.append("[bold]Type:[/bold]           AI Prompt")
                    details.append(f"[bold]Prompt:[/bold]         {t.prompt[:100]}...")
                    details.append(
                        f"[bold]Provider:[/bold]       {t.provider or 'global default'}"
                    )
                elif t.command:
                    details.append("[bold]Type:[/bold]           Shell Command")
                    details.append(f"[bold]Command:[/bold]        {t.command}")
                console.print(
                    Panel(
                        "\n".join(details), title=f"[cyan]{t.name}[/cyan]", expand=False
                    )
                )
                return

    console.print(f"[red]Task '{name}' not found.[/red]")
    raise typer.Exit(1)


@task_app.command("run")
def task_run(name: str = typer.Argument(..., help="Task name to run immediately")):
    """Run a specific task immediately (ignores schedule)."""
    from .scheduler import get_projects
    from .parser import load_project_tasks
    from .executor import execute_task
    from rich.console import Console

    console = Console()
    projects = get_projects()

    for proj_dir in projects:
        for toml_file, local_task in load_project_tasks(proj_dir):
            if local_task.task.name == name:
                console.print(
                    f"[cyan]Running task:[/cyan] [bold]{name}[/bold] in {proj_dir}"
                )
                execute_task(proj_dir, local_task.task, task_file=toml_file)
                console.print(f"[green]✓ Task '{name}' completed.[/green]")
                return

    console.print(f"[red]Task '{name}' not found.[/red]")
    raise typer.Exit(1)


@cron_app.command("install")
def cron_install():
    """Register kage run to system scheduler (cron/launchd)."""
    daemon.install()


@cron_app.command("remove")
def cron_remove():
    """Unregister kage run from system scheduler."""
    daemon.remove()


@cron_app.command("status")
def cron_status():
    """Check if kage is registered in system scheduler."""
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


def _is_ja() -> bool:
    import locale
    import os
    if os.environ.get("LANG", "").startswith("ja"):
        return True
    try:
        loc, _ = locale.getlocale()
        if loc and loc.startswith("ja"):
            return True
    except Exception:
        pass
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
def run():
    """Run scheduled tasks."""
    from .scheduler import run_all_scheduled_tasks

    run_all_scheduled_tasks()


@app.command()
def logs(limit: int = 10):
    """View kage execution logs."""
    from .config import KAGE_DB_PATH
    import sqlite3
    from rich.table import Table
    from rich.console import Console

    if not KAGE_DB_PATH.exists():
        typer.echo("No logs found.")
        return

    conn = sqlite3.connect(KAGE_DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT run_at, project_path, task_name, status, stdout, stderr, finished_at
        FROM executions 
        ORDER BY run_at DESC LIMIT ?
    """,
        (limit,),
    )
    rows = cursor.fetchall()

    console = Console()
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Run At")
    table.add_column("Project")
    table.add_column("Task")
    table.add_column("Status")
    table.add_column("Duration", justify="right")
    table.add_column("Output (stdout / stderr)", style="dim")

    for row in rows:
        run_at, proj, name, status, stdout_val, stderr_val, finished_at = row

        # 整形: "2026-02-23T18:28:01.032891" -> "02/23 18:28:01"
        try:
            from datetime import datetime

            dt_start = datetime.fromisoformat(run_at)
            run_at_str = dt_start.strftime("%m/%d %H:%M:%S")
            
            if finished_at:
                dt_end = datetime.fromisoformat(finished_at)
                duration_sec = (dt_end - dt_start).total_seconds()
                duration_str = f"{int(duration_sec)}s"
            else:
                if status == "RUNNING":
                    duration_sec = (datetime.now() - dt_start).total_seconds()
                    duration_str = f"{int(duration_sec)}s+"
                else:
                    duration_str = "-"
        except ValueError:
            run_at_str = run_at[:19].replace("T", " ")
            duration_str = "-"

        # Output 整形
        out_str = []
        if stdout_val and str(stdout_val).strip():
            clean_out = str(stdout_val).strip().replace("\n", " ").replace("\r", "")
            out_str.append(f"[STDOUT] {clean_out[:40]}")
        if stderr_val and str(stderr_val).strip():
            clean_err = str(stderr_val).strip().replace("\n", " ").replace("\r", "")
            out_str.append(f"[STDERR] {clean_err[:40]}")

        final_out = " | ".join(out_str)
        if len(final_out) > 65:
            final_out = final_out[:62] + "..."

        # ステータスの色付け
        if status == "SUCCESS":
            status_colored = f"[green]{status}[/green]"
        elif status == "RUNNING":
            status_colored = f"[yellow]{status}[/yellow]"
        else:
            status_colored = f"[red]{status}[/red]"

        # プロジェクトパスの短縮 (最後の2ディレクトリなどを表示)
        from pathlib import Path

        p = Path(proj)
        proj_str = f".../{p.parent.name}/{p.name}" if len(p.parts) > 2 else proj

        table.add_row(run_at_str, proj_str, str(name), status_colored, duration_str, final_out)

    console.print(table)
    conn.close()


@app.command()
def stop(exec_id: str = typer.Argument(..., help="Execution ID to stop")):
    """Stop a running execution."""
    from .executor import stop_execution
    from rich.console import Console

    console = Console()
    console.print(f"[yellow]Stopping execution {exec_id}...[/yellow]")
    stop_execution(exec_id)
    console.print("[green]Stop signal sent.[/green]")


@app.command()
def ui(
    host: Optional[str] = typer.Option(None, "--host", "-h", help="Bind host (e.g., '0.0.0.0' for external access)"),
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
def config(
    key: str = typer.Argument(..., help="Setting key (e.g., 'default_ai_engine')"),
    value: str = typer.Argument(..., help="New value"),
    is_global: bool = typer.Option(
        False,
        "--global",
        "-g",
        help="Update global config (~/.kage/config.toml) instead of workspace config",
    ),
):
    """Update configuration via CLI."""
    from .config import set_config_value

    set_config_value(key, value, is_global=is_global)


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
    summary.add_row("default_ai_engine", str(cfg.default_ai_engine or "None"))
    summary.add_row("ui_port", str(cfg.ui_port))
    summary.add_row("ui_host", str(cfg.ui_host))
    summary.add_row("log_level", str(cfg.log_level))
    summary.add_row("timezone", str(cfg.timezone))
    summary.add_row("cron_interval_minutes", str(cfg.cron_interval_minutes))
    summary.add_row("env_path", str(cfg.env_path or "None"))
    console.print(summary)

    provider_table = Table(title="Providers", show_header=True, header_style="bold")
    provider_table.add_column("name", style="bold")
    provider_table.add_column("command")
    provider_table.add_column("parser")
    provider_table.add_column("parser_args")
    for name in sorted(cfg.providers.keys()):
        p = cfg.providers[name]
        provider_table.add_row(name, p.command, p.parser, p.parser_args or "")
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
        "AIタスクを使う場合: kage config default_ai_engine codex --global"
        if is_ja
        else "If using AI tasks: run 'kage config default_ai_engine codex --global'"
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
            croniter(expr, datetime.utcnow())
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
                        if k not in {"command", "parser", "parser_args"}:
                            warn(scope, f"providers.{name}: unknown key {k}")
                    if "command" in prov and not isinstance(prov["command"], str):
                        fail(scope, f"providers.{name}.command must be string")
                    if "parser" in prov and not isinstance(prov["parser"], str):
                        fail(scope, f"providers.{name}.parser must be string")
                    if "parser_args" in prov and not isinstance(
                        prov["parser_args"], str
                    ):
                        fail(scope, f"providers.{name}.parser_args must be string")
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
        if task_data.get("command") is not None and not isinstance(
            task_data.get("command"), str
        ):
            fail(label, "command must be string")
        if task_data.get("shell") is not None and not isinstance(
            task_data.get("shell"), str
        ):
            fail(label, "shell must be string")

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

        task_data = {
            "name": fm.get("name"),
            "cron": fm.get("cron"),
            "active": fm.get("active", "true"),
            "prompt": body if body.strip() else None,
            "command": fm.get("command"),
            "shell": fm.get("shell"),
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

    # 7. Validate config files and task files
    if KAGE_CONFIG_PATH.exists():
        _validate_config_file(KAGE_CONFIG_PATH, str(KAGE_CONFIG_PATH))

    try:
        from .scheduler import get_projects

        projects = get_projects()
    except Exception as e:
        projects = []
        warn("projects discovery", str(e))

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
    ctype: Optional[str] = typer.Argument(None, help="Connector type (discord, slack, telegram)")
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
        console.print("\nRun [bold]kage connector setup discord[/bold] for instructions.")
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
"""
        console.print(Panel(Markdown(text), title="Discord Setup", border_style="magenta"))
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
        console.print(Panel(Markdown(text), title="Telegram Setup", border_style="cyan"))
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
