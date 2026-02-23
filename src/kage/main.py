import typer
from . import config as config_mod, daemon, db
from typing import Optional

app = typer.Typer(
    help="kage - AI Native Cron Task Runner",
    add_completion=False,
)

daemon_app = typer.Typer(help="OS-level daemon (cron/launchd) management")
app.add_typer(daemon_app, name="daemon")

task_app = typer.Typer(help="Manage kage tasks")
app.add_typer(task_app, name="task")

project_app = typer.Typer(help="Manage registered projects")
app.add_typer(project_app, name="project")

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
        console.print(f"[yellow]No projects registered.[/yellow]")
        console.print(f"Run [bold]kage init[/bold] in a project directory to register it.")
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
    path: Optional[str] = typer.Argument(None, help="Project path to unregister (defaults to current directory)")
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
    new_lines = [l for l in lines if l.strip() and str(Path(l.strip()).resolve()) != target]

    if len(new_lines) == len([l for l in lines if l.strip()]):
        console.print(f"[yellow]Project not found in registry: {target}[/yellow]")
        return

    KAGE_PROJECTS_LIST.write_text("\n".join(new_lines) + ("\n" if new_lines else ""))
    console.print(f"[green]✔ Removed:[/green] {target}")


@task_app.command("list")
def task_list(
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Filter by project path")
):
    """List all registered tasks across projects."""
    from .scheduler import get_projects
    from .parser import load_project_tasks
    from rich.console import Console
    from rich.table import Table

    console = Console()
    projects = get_projects()
    
    if not projects:
        console.print("[yellow]No projects registered. Run 'kage init' in a project directory.[/yellow]")
        raise typer.Exit()

    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Project", style="dim")
    table.add_column("Task Name", style="bold")
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
            provider_info = t.provider or (t.ai.engine if t.ai and t.ai.engine else "") if t.prompt else (t.command or "")[:40]
            table.add_row(
                str(proj_dir),
                t.name,
                t.cron,
                task_type,
                provider_info or "-",
            )
            found = True

    if not found:
        console.print("[yellow]No tasks found.[/yellow]")
    else:
        console.print(table)

@task_app.command("show")
def task_show(
    name: str = typer.Argument(..., help="Task name to show details for")
):
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
                    f"[bold]Name:[/bold]      {t.name}",
                    f"[bold]Schedule:[/bold]  {t.cron}",
                    f"[bold]Project:[/bold]   {proj_dir}",
                    f"[bold]File:[/bold]      {toml_file}",
                ]
                if t.prompt:
                    details.append(f"[bold]Type:[/bold]      AI Prompt")
                    details.append(f"[bold]Prompt:[/bold]    {t.prompt}")
                    details.append(f"[bold]Provider:[/bold]  {t.provider or (t.ai.engine if t.ai and t.ai.engine else 'global default')}")
                elif t.command:
                    details.append(f"[bold]Type:[/bold]      Shell Command")
                    details.append(f"[bold]Command:[/bold]   {t.command}")
                    details.append(f"[bold]Shell:[/bold]     {t.shell or 'sh'}")
                console.print(Panel("\n".join(details), title=f"[cyan]{t.name}[/cyan]", expand=False))
                return

    console.print(f"[red]Task '{name}' not found.[/red]")
    raise typer.Exit(1)

@task_app.command("run")
def task_run(
    name: str = typer.Argument(..., help="Task name to run immediately")
):
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
                console.print(f"[cyan]Running task:[/cyan] [bold]{name}[/bold] in {proj_dir}")
                execute_task(proj_dir, local_task.task)
                console.print(f"[green]✓ Task '{name}' completed.[/green]")
                return

    console.print(f"[red]Task '{name}' not found.[/red]")
    raise typer.Exit(1)

@daemon_app.command("install")
def daemon_install():
    """Register kage run to system scheduler (cron/launchd)."""
    daemon.install()

@daemon_app.command("remove")
def daemon_remove():
    """Unregister kage run from system scheduler."""
    daemon.remove()

@daemon_app.command("status")
def daemon_status():
    """Check if kage is registered in system scheduler."""
    daemon.status()

@daemon_app.command("start")
def daemon_start():
    """Start/Enable background tasks."""
    daemon.start()

@daemon_app.command("stop")
def daemon_stop():
    """Stop/Disable background tasks."""
    daemon.stop()

@daemon_app.command("restart")
def daemon_restart():
    """Restart background tasks."""
    daemon.restart()

@app.command()
def onboard():
    """Initial setup for kage: Create ~/.kage and default configuration."""
    typer.echo("Initializing kage onboard...")
    config_mod.setup_global()
    daemon.install()
    db.init_db()
    typer.echo("Successfully set up global configuration and database.")

@app.command()
def init():
    """Initialize a kage project in the current directory."""
    typer.echo("Initializing kage project...")
    config_mod.setup_local()
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
    cursor.execute('''
        SELECT run_at, project_path, task_name, status, stdout, stderr
        FROM executions 
        ORDER BY run_at DESC LIMIT ?
    ''', (limit,))
    rows = cursor.fetchall()
    
    console = Console()
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Run At")
    table.add_column("Project")
    table.add_column("Task")
    table.add_column("Status")
    table.add_column("Output (stdout / stderr)", style="dim")
    
    for row in rows:
        run_at, proj, name, status, stdout_val, stderr_val = row
        
        # 整形: "2026-02-23T18:28:01.032891" -> "02/23 18:28:01"
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(run_at)
            run_at_str = dt.strftime("%m/%d %H:%M:%S")
        except ValueError:
            run_at_str = run_at[:19].replace("T", " ")

        # Output 整形
        out_str = []
        if stdout_val and str(stdout_val).strip():
            clean_out = str(stdout_val).strip().replace('\n', ' ').replace('\r', '')
            out_str.append(f"[STDOUT] {clean_out[:40]}")
        if stderr_val and str(stderr_val).strip():
            clean_err = str(stderr_val).strip().replace('\n', ' ').replace('\r', '')
            out_str.append(f"[STDERR] {clean_err[:40]}")
            
        final_out = " | ".join(out_str)
        if len(final_out) > 65:
            final_out = final_out[:62] + "..."
            
        # ステータスの色付け
        status_colored = f"[green]{status}[/green]" if status == "SUCCESS" else f"[red]{status}[/red]"
        
        # プロジェクトパスの短縮 (最後の2ディレクトリなどを表示)
        from pathlib import Path
        p = Path(proj)
        proj_str = f".../{p.parent.name}/{p.name}" if len(p.parts) > 2 else proj

        table.add_row(run_at_str, proj_str, str(name), status_colored, final_out)
        
    console.print(table)
    conn.close()

@app.command()
def ui():
    """Launch the web UI dashboard."""
    from .config import get_global_config
    from .web import start_ui
    cfg = get_global_config()
    typer.echo(f"Starting web UI on port {cfg.ui_port}...")
    start_ui(port=cfg.ui_port)

@app.command()
def config(
    key: str = typer.Argument(..., help="Setting key (e.g., 'default_ai_engine')"),
    value: str = typer.Argument(..., help="New value"),
    is_global: bool = typer.Option(False, "--global", "-g", help="Update global config (~/.kage/config.toml) instead of workspace config")
):
    """Update configuration via CLI."""
    from .config import set_config_value
    set_config_value(key, value, is_global=is_global)

@app.command()
def doctor():
    """Run setup diagnostics and show potential issues."""
    import shutil
    import os
    from rich.console import Console
    from rich.table import Table
    from .config import (
        get_global_config, KAGE_GLOBAL_DIR, KAGE_CONFIG_PATH,
        KAGE_PROJECTS_LIST, KAGE_DB_PATH
    )

    is_ja = os.environ.get("LANG", "").startswith("ja")
    
    t_title = "セットアップ診断" if is_ja else "Setup Diagnostics"
    t_chk = "チェック項目" if is_ja else "Check Item"
    t_det = "詳細" if is_ja else "Details"
    t_exists = "存在します" if is_ja else "Found"
    t_run_onboard = "kage onboard を実行してください" if is_ja else "Run 'kage onboard'"
    t_not_found = "が見つかりません" if is_ja else "not found"
    t_only_default = "ライブラリデフォルトのみが使用されます" if is_ja else "Using library defaults"
    t_proj_reg = "プロジェクト登録済み" if is_ja else "projects registered"
    t_run_init = "kage onboard / init を実行してください" if is_ja else "Run 'kage onboard' or 'kage init'"
    t_ai_not_set = "default_ai_engine が未設定" if is_ja else "default_ai_engine not set"
    t_ai_hint = "AIタスクを使う場合: kage config default_ai_engine codex --global" if is_ja else "If using AI tasks: run 'kage config default_ai_engine codex --global'"
    t_prov_undef = "が未定義" if is_ja else "is undefined"
    t_prov_cmd_hint = "default_config.toml または config.toml に commands を追加してください" if is_ja else "Add commands to your config.toml"
    t_prov_hint = "config.toml に providers セクションを追加するか、デフォルト設定を確認してください" if is_ja else "Check providers in your config or default_config.toml"
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

    # 1. Directory
    if KAGE_GLOBAL_DIR.exists():
        ok(f"~/.kage/ {'ディレクトリ' if is_ja else 'Directory'}", str(KAGE_GLOBAL_DIR))
    else:
        fail(f"~/.kage/ {'ディレクトリ' if is_ja else 'Directory'} {t_not_found}", t_run_onboard)

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
        count = len([l for l in lines if l.strip()])
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
                ok(f"providers.{cfg.default_ai_engine}", f"→ commands.{prov.command}: {cmd_def.template[0]}")
            else:
                warn(f"providers.{cfg.default_ai_engine}.command = '{prov.command}' {t_prov_undef}", t_prov_cmd_hint)
        else:
            warn(f"providers.{cfg.default_ai_engine} {t_prov_undef}", t_prov_hint)

    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 1))
    table.add_column("", width=2)
    table.add_column(t_chk, style="bold")
    table.add_column(t_det, style="dim")
    for icon, label, detail in checks:
        table.add_row(icon, label, detail)

    console.print(table)
    
    fails = [c for c in checks if "✘" in c[0]]
    warns = [c for c in checks if "⚠" in c[0]]
    console.print(f"\n[bold]{t_res}[/bold] {len(checks)} {('項目中' if is_ja else 'items,')} [red]{len(fails)} {t_err}[/red] / [yellow]{len(warns)} {t_warn}[/yellow]")
    if fails:
        raise typer.Exit(code=1)

if __name__ == "__main__":
    app()
