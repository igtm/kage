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


class DiscordConnectorConfig(BaseModel):
    type: str = "discord"
    active: bool = False
    bot_token: str = ""
    channel_id: str = ""
    user_id: Optional[str] = None
    history_limit: int = 10
    max_age_seconds: int = 600
    persona: Optional[str] = None

class SlackConnectorConfig(BaseModel):
    type: str = "slack"
    active: bool = False
    bot_token: str = ""
    channel_id: str = ""
    user_id: Optional[str] = None
    history_limit: int = 10
    max_age_seconds: int = 600
    persona: Optional[str] = None

class GlobalConfig(BaseModel):
    model_config = {"extra": "ignore"}
    default_ai_engine: Optional[str] = None
    log_level: str = "INFO"
    ui_port: int = 8484
    ui_host: str = "127.0.0.1"
    cron_interval_minutes: int = 1  # cron/launchd の起動間隔（分単位）
    darwin_launchd_interval_seconds: Optional[int] = None  # macOS launchd 専用: 秒単位の間隔
    darwin_launchd_keep_alive: bool = False  # macOS launchd 専用: KeepAlive を有効にするか
    timezone: str = "UTC"  # cron式のタイムゾーン評価基準
    env_path: Optional[str] = None  # cron実行時に復元するPATH環境変数
    system_prompt: str = ""  # デフォルトのシステムプロンプト
    think_tag_open: str = "<think>"  # 思考プロセスの開始タグ
    think_tag_close: str = "</think>"  # 思考プロセスの終了タグ
    memory_max_entries: int = 5  # プロンプトに注入する直近メモリの最大件数
    commands: dict[str, CommandDef] = {}
    providers: dict[str, ProviderConfig] = {}
    connectors: dict[str, dict] = {}


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
    設定をマージして GlobalConfig を返す。
    優先度（高い順）:
    1. .kage/config.local.toml
    2. .kage/config.toml
    3. ~/.kage/config.toml
    4. library defaults
    """
    # 1. ライブラリデフォルト
    merged = _load_default_config()

    # 2. ユーザーグローバル設定 (~/.kage/config.toml)
    user_config = _load_toml_file(KAGE_CONFIG_PATH)
    merged = _deep_merge(merged, user_config)

    # 3. ワークスペース設定 (.kage/config.toml)
    ws_dir = workspace_dir or Path.cwd()
    ws_config_path = ws_dir / ".kage" / "config.toml"
    ws_config = _load_toml_file(ws_config_path)
    merged = _deep_merge(merged, ws_config)

    # 4. ワークスペースローカル設定 (.kage/config.local.toml)
    ws_local_config_path = ws_dir / ".kage" / "config.local.toml"
    ws_local_config = _load_toml_file(ws_local_config_path)
    merged = _deep_merge(merged, ws_local_config)

    try:
        return GlobalConfig(**merged)
    except Exception:
        return GlobalConfig()


def get_system_prompt(workspace_dir: Optional[Path] = None) -> str:
    """
    システムプロンプトを取得する。
    優先度: .kage/system_prompt.md > ~/.kage/system_prompt.md > config内のsystem_prompt
    """
    ws_dir = workspace_dir or Path.cwd()

    # 1. Workspace MD
    ws_md = ws_dir / ".kage" / "system_prompt.md"
    if ws_md.exists():
        return ws_md.read_text(encoding="utf-8").strip()

    # 2. Global MD
    global_md = KAGE_GLOBAL_DIR / "system_prompt.md"
    if global_md.exists():
        return global_md.read_text(encoding="utf-8").strip()

    # 3. Config
    config = get_global_config(workspace_dir=ws_dir)
    return config.system_prompt


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


def set_config_value(
    key: str, value: str, is_global: bool = True, workspace_dir: Optional[Path] = None
):
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

    import locale

    sample_md_path = tasks_dir / "ocr_benchmark.md"
    if not sample_md_path.exists():
        # Locale detection for default language
        lang = "en"
        try:
            loc, _ = locale.getlocale()
            if loc and loc.startswith("ja"):
                lang = "ja"
        except Exception:
            pass
        
        # Check env var for overriding locale (useful for tests or specific environments)
        import os
        if os.environ.get("LANG", "").startswith("ja"):
            lang = "ja"

        if lang == "ja":
            template = """---
name: OCR Benchmark (Sample)
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
            template = """---
name: OCR Benchmark (Sample)
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
        sample_md_path.write_text(template, encoding="utf-8")

    # Add to global projects list
    if KAGE_PROJECTS_LIST.exists():
        with open(KAGE_PROJECTS_LIST, "r", encoding="utf-8") as f:
            projects = [line.strip() for line in f if line.strip()]

        current_str = str(target_dir.absolute())
        if current_str not in projects:
            with open(KAGE_PROJECTS_LIST, "a", encoding="utf-8") as f:
                f.write(f"{current_str}\n")
