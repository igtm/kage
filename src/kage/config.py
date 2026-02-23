import os
from pathlib import Path
from importlib import resources
import tomlkit
from pydantic import BaseModel
from typing import Optional

KAGE_GLOBAL_DIR = Path.home() / ".kage"
KAGE_CONFIG_PATH = KAGE_GLOBAL_DIR / "config.toml"
KAGE_PROJECTS_LIST = KAGE_GLOBAL_DIR / "projects.list"
KAGE_DB_PATH = KAGE_GLOBAL_DIR / "kage.db"

class CommandDef(BaseModel):
    """CLIの呼び出しテンプレートを定義する（パーサー設定は含まない）"""
    template: list[str]

class ProviderConfig(BaseModel):
    """commandを参照し、パーサー設定を付与したプロバイダー定義"""
    command: str
    parser: str = "raw"
    parser_args: str = ""

class GlobalConfig(BaseModel):
    default_ai_engine: Optional[str] = None
    log_level: str = "INFO"
    ui_port: int = 8484
    daemon_interval_minutes: int = 1  # cron/launchd の起動間隔（分単位）
    commands: dict[str, CommandDef] = {}
    providers: dict[str, ProviderConfig] = {}


def _load_toml_file(path: Path) -> dict:
    """TOMLファイルを読み込んで辞書として返す。存在しない場合は空の辞書。"""
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = tomlkit.load(f)
            return data.unwrap() if hasattr(data, "unwrap") else dict(data)
    except Exception:
        return {}


def _deep_merge(base: dict, override: dict) -> dict:
    """辞書を再帰的にマージする。overrideが優先される。
    commands / providers のような辞書キーはマージされる（上書きではなく追加）。
    """
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _load_default_config() -> dict:
    """ライブラリ同梱の default_config.toml を読み込む"""
    try:
        pkg_files = resources.files("kage")
        toml_path = pkg_files.joinpath("default_config.toml")
        with toml_path.open("r", encoding="utf-8") as f:
            return dict(tomlkit.load(f))
    except Exception:
        return {}


def get_global_config(workspace_dir: Optional[Path] = None) -> GlobalConfig:
    """
    3層の設定をマージして GlobalConfig を返す。
    優先度（高い順）: workspace (.kage/config.toml) > user (~/.kage/config.toml) > library defaults
    """
    # 1. ライブラリデフォルト
    merged = _load_default_config()
    
    # 2. ユーザー設定で上書き
    user_config = _load_toml_file(KAGE_CONFIG_PATH)
    merged = _deep_merge(merged, user_config)
    
    # 3. ワークスペース設定で上書き（最高優先）
    ws_dir = workspace_dir or Path.cwd()
    ws_config_path = ws_dir / ".kage" / "config.toml"
    ws_config = _load_toml_file(ws_config_path)
    merged = _deep_merge(merged, ws_config)
    
    try:
        return GlobalConfig(**merged)
    except Exception:
        return GlobalConfig()


def get_user_overrides(workspace_dir: Optional[Path] = None) -> dict:
    """
    ユーザー設定とワークスペース設定のみをマージして返す（ライブラリデフォルトは含めない）。
    UI表示用。
    """
    user_config = _load_toml_file(KAGE_CONFIG_PATH)
    ws_dir = workspace_dir or Path.cwd()
    ws_config_path = ws_dir / ".kage" / "config.toml"
    ws_config = _load_toml_file(ws_config_path)
    
    return _deep_merge(user_config, ws_config)


def set_config_value(key: str, value: str, is_global: bool = True, workspace_dir: Optional[Path] = None):
    """
    設定値を TOML ファイルに保存する。階層化されたキー (e.g. 'ui_port') に対応。
    """
    if is_global:
        path = KAGE_CONFIG_PATH
    else:
        ws_dir = workspace_dir or Path.cwd()
        path = ws_dir / ".kage" / "config.toml"
    
    # 既存のファイルを読み込む（コメント等を保持するため tomlkit をそのまま使う）
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            doc = tomlkit.load(f)
    else:
        doc = tomlkit.document()
        if not path.parent.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            
    # 型推論: 数字やブール値への変換
    if value.lower() == "true":
        v = True
    elif value.lower() == "false":
        v = False
    elif value.isdigit():
        v = int(value)
    else:
        v = value
        
    doc[key] = v
    
    with open(path, "w", encoding="utf-8") as f:
        tomlkit.dump(doc, f)
    # typer.echo は main.py 側で出すか、ここで行うならインポートが必要
    print(f"Updated {key} = {v} in {path}")


def setup_global():
    """グローバルディレクトリの初期化のみ行う。
    デフォルト設定はライブラリに同梱されているため、config.toml は生成しない。
    ユーザーが上書きしたい場合のみ ~/.kage/config.toml を作成する。
    """
    KAGE_GLOBAL_DIR.mkdir(parents=True, exist_ok=True)
    if not KAGE_PROJECTS_LIST.exists():
        KAGE_PROJECTS_LIST.touch()


def setup_local(target_dir: Path = None):
    if target_dir is None:
        target_dir = Path.cwd()
        
    kage_local_dir = target_dir / ".kage"
    tasks_dir = kage_local_dir / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    
    sample_task_path = tasks_dir / "sample.toml"
    if not sample_task_path.exists():
        doc = tomlkit.document()
        
        doc.add(tomlkit.comment("================================================================"))
        doc.add(tomlkit.comment(" kage タスク定義サンプル (Fully Loaded)"))
        doc.add(tomlkit.comment("================================================================"))
        doc.add(tomlkit.comment(""))
        doc.add(tomlkit.comment("--- [Pattern 1] AIプロンプト（基本） ---"))
        doc.add(tomlkit.comment("最もシンプルなAIへの依頼です。"))
        
        task1 = tomlkit.table()
        task1.add("name", "Daily Code Review")
        task1.add("cron", "0 3 * * *")
        task1.add("prompt", "今日の変更点を要約して、改善案を箇条書きで出してください。")
        task1.add("provider", "claude")
        doc.add("task_basic", task1)
        doc.add(tomlkit.comment(""))

        doc.add(tomlkit.comment("--- [Pattern 2] 分類タスク + JQパース (codex_json) ---"))
        doc.add(tomlkit.comment("AIにJSON形式で出力させ、ラベル部分だけを抽出する例です。"))
        
        task2 = tomlkit.table()
        task2.add("name", "Ticket Labeling")
        task2.add("cron", "*/30 * * * *")
        task2.add("prompt", "このIssueの内容を [bug, feature, docs] のいずれかに分類して、{\"label\": \"...\"} の形式で出力して: 'ログインできない'")
        task2.add("provider", "codex_json")  # 内部で jq パーサーが設定されているプロバイダー
        task2.add("parser_args", ".label")  # プロバイダー設定を上書きしてラベル名のみ抽出
        doc.add("task_json_jq", task2)
        doc.add(tomlkit.comment(""))

        doc.add(tomlkit.comment("--- [Pattern 3] インラインフル指定 (グローバル設定を無視) ---"))
        doc.add(tomlkit.comment("特定のタスクだけ独自のCLIや引数を使いたい場合、全てここで定義できます。"))
        
        task3 = tomlkit.table()
        task3.add("name", "Custom Tool Task")
        task3.add("cron", "0 0 * * *")
        task3.add("prompt", "解析対象のテキスト")
        task3.add("command_template", ["my-custom-cli", "--output", "json", "--input", "{prompt}"])
        task3.add("parser", "jq")
        task3.add("parser_args", ".results[0].text")
        
        ai_cfg = tomlkit.table()
        ai_cfg.add("engine", "unused_but_schema_requires")
        ai_cfg.add("args", ["--temperature", "0.2", "--max-tokens", "1000"])
        task3.add("ai", ai_cfg)
        doc.add("task_full_inline", task3)
        doc.add(tomlkit.comment(""))

        doc.add(tomlkit.comment("--- [Pattern 4] 通常のShellコマンド実行 ---"))
        doc.add(tomlkit.comment("AIを使わず、単純な cron ジョブとして実行します。"))
        
        task4 = tomlkit.table()
        task4.add("name", "Cleanup Logs")
        task4.add("cron", "0 4 * * 0")
        task4.add("command", "rm -rf ./logs/*.log && touch ./logs/.gitkeep")
        task4.add("shell", "bash")
        doc.add("task_shell", task4)

        doc.add(tomlkit.comment(""))
        doc.add(tomlkit.comment("================================================================"))
        doc.add(tomlkit.comment(" 利用可能なフィールド一覧"))
        doc.add(tomlkit.comment("================================================================"))
        doc.add(tomlkit.comment(" name             : タスク名 (必須)"))
        doc.add(tomlkit.comment(" cron             : 実行タイミング (crontab形式, 必須)"))
        doc.add(tomlkit.comment(" prompt           : AIへの依頼内容 (AI実行時に必須)"))
        doc.add(tomlkit.comment(" provider         : 使用するAIプロバイダー (config.tomlの[providers]参照)"))
        doc.add(tomlkit.comment(" command          : 直接実行するShellコマンド (AIを使わない場合使用)"))
        doc.add(tomlkit.comment(" shell            : command実行時のシェル (デフォルト: sh)"))
        doc.add(tomlkit.comment(" command_template : インラインでのCLIビルド。{prompt} が置換される"))
        doc.add(tomlkit.comment(" parser           : 出力パーサーの種類 ('raw' or 'jq')"))
        doc.add(tomlkit.comment(" parser_args       : パーサーへの引数 (jqのクエリなど)"))
        doc.add(tomlkit.comment(" [task.ai]        : 詳細なAIエンジン設定"))
        doc.add(tomlkit.comment("   engine         : プロバイダー名の上書き"))
        doc.add(tomlkit.comment("   args           : CLIに渡す追加の引数リスト"))
        doc.add(tomlkit.comment("================================================================"))

        with open(sample_task_path, "w", encoding="utf-8") as f:
            tomlkit.dump(doc, f)
            
    # Add to global projects list
    if KAGE_PROJECTS_LIST.exists():
        with open(KAGE_PROJECTS_LIST, "r", encoding="utf-8") as f:
            projects = [line.strip() for line in f if line.strip()]
        
        current_str = str(target_dir.absolute())
        if current_str not in projects:
            with open(KAGE_PROJECTS_LIST, "a", encoding="utf-8") as f:
                f.write(f"{current_str}\n")
