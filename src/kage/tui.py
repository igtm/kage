from __future__ import annotations

import locale
from datetime import datetime
import os
from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import (
    DataTable,
    Footer,
    Header,
    Log,
    Static,
    TabPane,
    TabbedContent,
)

from .config import get_global_config
from .runs import (
    format_local_timestamp,
    format_relative_timestamp,
    list_runs,
    load_all_log_text,
    load_log_text,
)
from .web import get_config_api, get_connector_history, get_connectors

ALL_TASKS_KEY = "__all_tasks__"
LOG_LINE_LIMIT = 400
RUN_LIST_LIMIT = 200


def _is_ja() -> bool:
    if os.environ.get("LANG", "").startswith("ja"):
        return True
    try:
        loc, _ = locale.getlocale()
        if loc and loc.startswith("ja"):
            return True
    except Exception:
        pass
    return False


def _task_key(task: dict[str, Any]) -> str:
    return f"{task['project_path']}::{task['name']}::{task['file']}"


def _task_label(task: dict[str, Any]) -> str:
    return f"{task['project_name']}/{task['name']}"


def _row_key_to_str(value: Any) -> str:
    return str(getattr(value, "value", value))


def _safe_str(value: Any) -> str:
    return "-" if value in (None, "") else str(value)


def _format_task_details(task: dict[str, Any], *, is_ja: bool) -> str:
    lines = [
        f"{'名前' if is_ja else 'Name'}: {task['name']}",
        f"{'Project' if not is_ja else 'プロジェクト'}: {task['project_path']}",
        f"{'ファイル' if is_ja else 'File'}: {task['file']}",
        f"{'Type' if not is_ja else '種別'}: {task.get('type_display') or '-'}",
        f"{'Provider' if not is_ja else 'Provider'}: {task.get('provider_display') or '-'}",
        f"{'スケジュール' if is_ja else 'Schedule'}: {task['cron']}",
        f"{'Active' if not is_ja else '有効'}: {'yes' if task['active'] else 'no'}",
        f"{'モード' if is_ja else 'Mode'}: {task.get('mode') or '-'}",
        f"{'並列制御' if is_ja else 'Concurrency'}: {task.get('concurrency_policy') or '-'}",
        f"{'タイムゾーン' if is_ja else 'Timezone'}: {task.get('task_timezone') or '-'}",
        f"{'許可時間' if is_ja else 'Allowed Hours'}: {_safe_str(task.get('allowed_hours'))}",
        f"{'禁止時間' if is_ja else 'Denied Hours'}: {_safe_str(task.get('denied_hours'))}",
        f"{'停止' if is_ja else 'Suspension'}: {_safe_str(task.get('suspension_summary'))}",
        f"{'停止理由' if is_ja else 'Suspend Reason'}: {_safe_str(task.get('suspended_reason'))}",
        f"{'タイムアウト' if is_ja else 'Timeout'}: {_safe_str(task.get('timeout_minutes'))}",
        f"{'Compiled' if not is_ja else 'Compiled'}: {_safe_str(task.get('compiled_state'))}",
    ]
    if task.get("compiled_path"):
        lines.append(
            f"{'Compiled Path' if not is_ja else 'Compiled Path'}: {task['compiled_path']}"
        )
    if task.get("command"):
        lines.extend(["", "Command:", task["command"]])
    if task.get("prompt"):
        lines.extend(["", "Prompt:", task["prompt"]])
    return "\n".join(lines)


def _format_connector_history(
    connector: dict[str, Any],
    history: list[dict[str, Any]],
    *,
    is_ja: bool,
) -> str:
    masked = connector.get("config", {})
    header = [
        f"{'名前' if is_ja else 'Name'}: {connector.get('name', '-')}",
        f"Type: {masked.get('type', '-')}",
        f"Poll: {masked.get('poll', False)}",
        f"{'チャネル' if is_ja else 'Channel'}: {_safe_str(masked.get('channel_id') or masked.get('chat_id'))}",
        "",
        f"{'履歴' if is_ja else 'History'}:",
    ]
    body: list[str] = []
    for entry in history:
        ts = entry.get("timestamp")
        if isinstance(ts, (int, float)):
            stamp = (
                datetime.fromtimestamp(ts).astimezone().strftime("%Y-%m-%d %H:%M:%S")
            )
        else:
            stamp = "-"
        role = str(entry.get("role", "-"))
        content = str(entry.get("content", "")).strip() or "-"
        run_id = entry.get("run_id")
        suffix = f" [run: {run_id[:8]}]" if isinstance(run_id, str) and run_id else ""
        body.append(f"{stamp} {role}{suffix}\n{content}")
    if not body:
        body.append("履歴はありません。" if is_ja else "No history recorded.")
    return "\n\n".join(header + body)


def _format_global_config(is_ja: bool) -> str:
    cfg = get_global_config()
    lines = [
        f"default_ai_engine: {_safe_str(cfg.default_ai_engine)}",
        f"ui_host: {_safe_str(cfg.ui_host)}",
        f"ui_port: {cfg.ui_port}",
        f"timezone: {cfg.timezone}",
        f"log_level: {cfg.log_level}",
        f"cron_interval_minutes: {cfg.cron_interval_minutes}",
        f"run_retention_count: {cfg.run_retention_count}",
        f"memory_max_entries: {cfg.memory_max_entries}",
        f"{'コマンド' if is_ja else 'Commands'}: {', '.join(sorted(cfg.commands.keys())) or '-'}",
        f"{'Provider' if not is_ja else 'Providers'}: {', '.join(sorted(cfg.providers.keys())) or '-'}",
        f"{'コネクタ' if is_ja else 'Connectors'}: {', '.join(sorted(cfg.connectors.keys())) or '-'}",
    ]
    if cfg.env_path:
        lines.extend(["", "env_path:", cfg.env_path])
    return "\n".join(lines)


class KageTuiApp(App[None]):
    TITLE = "kage tui"
    SUB_TITLE = "Terminal dashboard"
    CSS = """
    Screen {
        layout: vertical;
    }

    TabbedContent {
        height: 1fr;
    }

    .panel-title {
        padding: 0 1;
        background: $boost;
        color: $text;
        text-style: bold;
    }

    .left-pane {
        width: 38%;
        min-width: 32;
        border: round $surface;
    }

    .right-pane {
        width: 1fr;
        border: round $surface;
    }

    .stack {
        height: 1fr;
    }

    .section {
        height: 1fr;
    }

    DataTable {
        height: 1fr;
    }

    #logs-meta {
        padding: 0 1;
        color: $text-muted;
        height: auto;
    }

    .content {
        height: 1fr;
        padding: 0 1;
        min-height: 0;
    }
    """
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("f5", "refresh", "Refresh"),
        Binding("1", "show_tab('logs')", "Logs"),
        Binding("2", "show_tab('tasks')", "Tasks"),
        Binding("3", "show_tab('connectors')", "Connector"),
        Binding("4", "show_tab('settings')", "Settings"),
        Binding("t", "toggle_task", "Toggle"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.is_ja = _is_ja()
        self.tasks: list[dict[str, Any]] = []
        self.task_by_key: dict[str, dict[str, Any]] = {}
        self.runs = []
        self.runs_by_id: dict[str, Any] = {}
        self.connectors: list[dict[str, Any]] = []
        self.selected_logs_task_key: str = ALL_TASKS_KEY
        self.selected_run_id: str | None = None
        self.selected_task_detail_key: str | None = None
        self.selected_connector_name: str | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with TabbedContent(initial="logs"):
            with TabPane("ログ" if self.is_ja else "Logs", id="logs"):
                with Horizontal(classes="stack"):
                    with Vertical(classes="left-pane section"):
                        yield Static("Tasks", classes="panel-title")
                        yield DataTable(id="logs-task-table")
                        yield Static("Runs", classes="panel-title")
                        yield DataTable(id="logs-run-table")
                    with Vertical(classes="right-pane section"):
                        yield Static("Logs", classes="panel-title")
                        yield Static("", id="logs-meta")
                        yield Log(
                            auto_scroll=False, id="logs-content", classes="content"
                        )
            with TabPane("タスク" if self.is_ja else "Tasks", id="tasks"):
                with Horizontal(classes="stack"):
                    with Vertical(classes="left-pane section"):
                        yield Static("Tasks", classes="panel-title")
                        yield DataTable(id="tasks-table")
                    with Vertical(classes="right-pane section"):
                        yield Static("Details", classes="panel-title")
                        yield Log(
                            auto_scroll=False, id="task-detail", classes="content"
                        )
            with TabPane("Connector", id="connectors"):
                with Horizontal(classes="stack"):
                    with Vertical(classes="left-pane section"):
                        yield Static("Connectors", classes="panel-title")
                        yield DataTable(id="connectors-table")
                    with Vertical(classes="right-pane section"):
                        yield Static("History", classes="panel-title")
                        yield Log(
                            auto_scroll=False,
                            id="connector-history",
                            classes="content",
                        )
            with TabPane("設定" if self.is_ja else "Settings", id="settings"):
                with Vertical(classes="right-pane section"):
                    yield Static("Global Config", classes="panel-title")
                    yield Log(
                        auto_scroll=False,
                        id="settings-content",
                        classes="content",
                    )
        yield Footer()

    def on_mount(self) -> None:
        self._setup_tables()
        self._reload()

    def _setup_tables(self) -> None:
        logs_task_table = self.query_one("#logs-task-table", DataTable)
        logs_task_table.cursor_type = "row"
        logs_task_table.add_columns("Task")
        logs_run_table = self.query_one("#logs-run-table", DataTable)
        logs_run_table.cursor_type = "row"
        logs_run_table.add_columns(
            "When" if not self.is_ja else "日時",
            "Status" if not self.is_ja else "状態",
            "Task",
        )
        tasks_table = self.query_one("#tasks-table", DataTable)
        tasks_table.cursor_type = "row"
        tasks_table.add_columns("⏻", "Task")
        connectors_table = self.query_one("#connectors-table", DataTable)
        connectors_table.cursor_type = "row"
        connectors_table.add_columns("Name", "Type")

    def action_refresh(self) -> None:
        self._reload()

    def action_show_tab(self, tab_id: str) -> None:
        self.query_one(TabbedContent).active = tab_id

    def action_toggle_task(self) -> None:
        """Toggle the active state of the currently selected task."""
        tabbed = self.query_one(TabbedContent)
        active_tab = tabbed.active
        if active_tab == "tasks":
            key = self.selected_task_detail_key
        elif active_tab == "logs":
            key = self.selected_logs_task_key
            if key == ALL_TASKS_KEY:
                return
        else:
            return
        if not key:
            return
        task = self.task_by_key.get(key)
        if not task:
            return
        from pathlib import Path

        task_file = Path(task["file"])
        if not task_file.exists():
            return
        current_active = task["active"]
        if task_file.suffix.lower() == ".md":
            from .suspension import update_markdown_front_matter

            update_markdown_front_matter(
                task_file,
                updates={"active": not current_active},
            )
        else:
            import tomlkit

            content = task_file.read_text(encoding="utf-8")
            doc = tomlkit.loads(content)
            if "task" in doc:
                doc["task"]["active"] = not current_active
            else:
                for key, value in doc.items():
                    if key.startswith("task") and hasattr(value, "get"):
                        if value.get("name") == task["name"]:
                            value["active"] = not current_active
            task_file.write_text(tomlkit.dumps(doc), encoding="utf-8")
        self._reload()

    def _reload(self) -> None:
        config_payload = get_config_api()
        self.tasks = sorted(
            config_payload["tasks"],
            key=lambda task: (task["project_name"].lower(), task["name"].lower()),
        )
        self.task_by_key = {_task_key(task): task for task in self.tasks}
        self.runs = list_runs(limit=RUN_LIST_LIMIT)
        self.runs_by_id = {run.id: run for run in self.runs}
        self.connectors = sorted(get_connectors(), key=lambda item: item["name"])

        if (
            self.selected_logs_task_key != ALL_TASKS_KEY
            and self.selected_logs_task_key not in self.task_by_key
        ):
            self.selected_logs_task_key = ALL_TASKS_KEY
        if self.selected_task_detail_key not in self.task_by_key:
            self.selected_task_detail_key = next(iter(self.task_by_key), None)
        if self.selected_connector_name not in {
            item["name"] for item in self.connectors
        }:
            self.selected_connector_name = (
                self.connectors[0]["name"] if self.connectors else None
            )
        if self.selected_run_id not in self.runs_by_id:
            self.selected_run_id = None

        self._refresh_logs_task_table()
        self._refresh_runs_table()
        self._refresh_log_view()
        self._refresh_tasks_table()
        self._refresh_task_detail()
        self._refresh_connectors_table()
        self._refresh_connector_history()
        self._update_text_panel(
            "#settings-content",
            _format_global_config(self.is_ja),
        )

    def _refresh_logs_task_table(self) -> None:
        table = self.query_one("#logs-task-table", DataTable)
        table.clear(columns=False)
        label = "All Tasks" if not self.is_ja else "すべてのタスク"
        table.add_row(label, key=ALL_TASKS_KEY)
        for task in self.tasks:
            table.add_row(_task_label(task), key=_task_key(task))
        self._move_cursor(
            table,
            0
            if self.selected_logs_task_key == ALL_TASKS_KEY
            else self._task_row_index(self.selected_logs_task_key),
        )

    def _task_row_index(self, task_key: str) -> int:
        if task_key == ALL_TASKS_KEY:
            return 0
        ordered_keys = [ALL_TASKS_KEY, *[_task_key(task) for task in self.tasks]]
        try:
            return ordered_keys.index(task_key)
        except ValueError:
            return 0

    def _filtered_runs(self):
        if self.selected_logs_task_key == ALL_TASKS_KEY:
            return self.runs
        task = self.task_by_key.get(self.selected_logs_task_key)
        if not task:
            return []
        return [
            run
            for run in self.runs
            if run.task_name == task["name"]
            and run.project_path == task["project_path"]
        ]

    def _refresh_runs_table(self) -> None:
        table = self.query_one("#logs-run-table", DataTable)
        table.clear(columns=False)
        filtered_runs = self._filtered_runs()
        if filtered_runs and self.selected_run_id not in {
            run.id for run in filtered_runs
        }:
            self.selected_run_id = filtered_runs[0].id
        if not filtered_runs:
            self.selected_run_id = None
        for run in filtered_runs:
            when = format_relative_timestamp(run.run_at, is_ja=self.is_ja)
            table.add_row(when, run.status, run.task_name, key=run.id)
        self._move_cursor(table, 0)

    def _refresh_log_view(self) -> None:
        meta = self.query_one("#logs-meta", Static)
        content = ""
        label = ""
        if self.selected_run_id:
            run = self.runs_by_id.get(self.selected_run_id)
            if run:
                content = load_log_text(run, stream="merged", lines=LOG_LINE_LIMIT)
                label = f"{run.task_name} · {run.status} · {format_local_timestamp(run.run_at)}"
        elif self.selected_logs_task_key != ALL_TASKS_KEY:
            task = self.task_by_key.get(self.selected_logs_task_key)
            if task:
                content = load_all_log_text(
                    stream="merged",
                    lines=LOG_LINE_LIMIT,
                    project_filter=task["project_path"],
                    task_name=task["name"],
                )
                label = _task_label(task)
        else:
            content = load_all_log_text(stream="merged", lines=LOG_LINE_LIMIT)
            label = "All Tasks" if not self.is_ja else "すべてのタスク"

        meta.update(label)
        self._update_text_panel(
            "#logs-content",
            content
            or (
                "No log output recorded."
                if not self.is_ja
                else "まだログ出力は記録されていません。"
            ),
        )

    def _refresh_tasks_table(self) -> None:
        table = self.query_one("#tasks-table", DataTable)
        table.clear(columns=False)
        for task in self.tasks:
            if task.get("is_suspended"):
                indicator = "⏸"
            else:
                indicator = "●" if task["active"] else "─"
            table.add_row(indicator, _task_label(task), key=_task_key(task))
        self._move_cursor(
            table,
            0
            if self.selected_task_detail_key is None
            else max(0, self._task_row_index(self.selected_task_detail_key) - 1),
        )

    def _refresh_task_detail(self) -> None:
        task = self.task_by_key.get(self.selected_task_detail_key or "")
        if not task:
            self._update_text_panel(
                "#task-detail",
                "No tasks registered."
                if not self.is_ja
                else "タスクは登録されていません。",
            )
            return
        self._update_text_panel(
            "#task-detail",
            _format_task_details(task, is_ja=self.is_ja),
        )

    def _refresh_connectors_table(self) -> None:
        table = self.query_one("#connectors-table", DataTable)
        table.clear(columns=False)
        for connector in self.connectors:
            table.add_row(
                connector["name"],
                str(connector.get("config", {}).get("type", "-")),
                key=connector["name"],
            )
        self._move_cursor(table, 0)

    def _refresh_connector_history(self) -> None:
        if not self.selected_connector_name:
            self._update_text_panel(
                "#connector-history",
                "No connectors configured."
                if not self.is_ja
                else "コネクタは設定されていません。",
            )
            return
        connector = next(
            (
                item
                for item in self.connectors
                if item["name"] == self.selected_connector_name
            ),
            None,
        )
        if connector is None:
            self._update_text_panel(
                "#connector-history",
                "No connectors configured."
                if not self.is_ja
                else "コネクタは設定されていません。",
            )
            return
        history = get_connector_history(self.selected_connector_name)
        self._update_text_panel(
            "#connector-history",
            _format_connector_history(connector, history, is_ja=self.is_ja),
        )

    def _move_cursor(self, table: DataTable, row: int) -> None:
        try:
            table.move_cursor(row=row, column=0, animate=False)
        except Exception:
            pass

    def _update_text_panel(self, panel_id: str, content: str) -> None:
        widget = self.query_one(panel_id, Log)
        widget.clear()
        widget.write(content)
        widget.scroll_home(animate=False)

    def _handle_table_selection(self, table_id: str, row_key: str) -> None:
        if table_id == "logs-task-table":
            self.selected_logs_task_key = row_key
            self.selected_run_id = None
            self._refresh_runs_table()
            self._refresh_log_view()
        elif table_id == "logs-run-table":
            self.selected_run_id = row_key
            self._refresh_log_view()
        elif table_id == "tasks-table":
            self.selected_task_detail_key = row_key
            self._refresh_task_detail()
        elif table_id == "connectors-table":
            self.selected_connector_name = row_key
            self._refresh_connector_history()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        self._handle_table_selection(
            event.data_table.id or "", _row_key_to_str(event.row_key)
        )

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self._handle_table_selection(
            event.data_table.id or "", _row_key_to_str(event.row_key)
        )


def start_tui() -> None:
    KageTuiApp().run()
