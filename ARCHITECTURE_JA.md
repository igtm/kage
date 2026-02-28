# kage 影 - 技術構成 (Technical Architecture)

このドキュメントでは、`kage` のシステム設計、実行メカニズム、およびその安全性についての技術的な詳細を解説します。

## 全体概要 (System Overview)

`kage` は、OS 標準のスケジューラー（`cron` または `launchd`）を起点とした **「プル型（Polling）」** のアーキテクチャを採用しています。

```mermaid
graph TD
    subgraph "OS Layer"
        Cron["cron / launchd (OS スケジューラー)"]
    end

    subgraph "kage Core"
        CLI["kage cron (エントリポイント)"]
        Run["kage run (実行ロジック)"]
        DB[(kage.db)]
        Config[config.toml]
    end

    subgraph "ローカルリソース"
        Tasks[".kage/tasks/*.md"]
        LocalTools["ローカルファイル / CLI ツール"]
    end

    subgraph "外部 AI & クラウド"
        AI["AI エンジン (Gemini 等)"]
        Slack["Slack API / Discord API"]
    end

    %% トリガーの流れ
    Cron -- "一定間隔で起動" --> CLI
    CLI -- "実行" --> Run

    %% 実行フロー
    Run -- "読み込み" --> Config
    Run -- "スケジュール確認" --> DB
    Run -- "パース" --> Tasks
    Run -- "呼び出し" --> AI
    Run -- "ポーリング & 投稿" --> Slack
    Run -- "操作" --> LocalTools
```

---

## 核心メカニズム (Core Mechanisms)

### 1. スケジューラー駆動型実行
`kage` 自体は常駐プロセス（デーモン）として常にメモリを消費し続けるのではなく、OS 標準の `cron` (Linux) や `launchd` (macOS) によって、指定された間隔（1分ごと、あるいは数秒ごと）で「その都度」起動されます。

- **`kage cron install`**: OS のスケジューラーに `kage run` を登録します。
- **ステートレスな設計**: 起動のたびに現在のコンテキスト（`.kage/tasks` や `config.toml`）を評価し、実行が必要なタスクがあれば AI を呼び出します。実行が終わればプロセスは終了します。

### 2. コネクターのポーリング方式 (Polling-based Connectors)
`kage` の Discord/Slack コネクターは、**Webhook や WebSocket による待機（プッシュ型）ではなく、定期的なメッセージ取得（プル型）** で動作します。

```mermaid
sequenceDiagram
    participant PC as ローカル PC (kage)
    participant Cloud as Slack / Discord API
    participant User as ユーザー (チャットクライアント)

    Note over PC: launchd / cron により起動
    PC->>Cloud: GET /conversations.history (最新メッセージの取得)
    Cloud-->>PC: JSON レスポンス (メッセージリスト)
    
    Note over PC: 新着メッセージをフィルタリング
    Note over PC: 必要に応じて AI に回答を依頼
    
    PC->>Cloud: POST /chat.postMessage (返信の投稿)
    Cloud-->>User: チャット画面に表示
```

---

## 安全性とプライバシー (Security & Privacy)

この「ポーリング（プル型）」アーキテクチャこそが、自宅や手持ちの PC でエージェントを運用する上で最大のメリットとなります。

### 1. 公開 IP アドレスが不要
プッシュ型の Webhook 受信を行う場合、インターネットから自分の PC にアクセスできるグローバル IP アドレスや、ルーターのポート開放、あるいは `ngrok` のようなトンネリングツールが必要です。
`kage` は自分から外部へリクエストを投げに行くだけなので、**プライベートネットワーク内（NAT 内）で設定変更なしに、かつ安全に動作します。**

### 2. セキュアなローカルアクセス
AI エージェントはローカルファイルや社外秘のプロジェクトデータにアクセスする必要があります。`kage` はあなたの PC 上で、あなたの権限で動作するため、外部のクラウドサービスにローカルファイルをアップロードすることなく、必要なコンテキストだけを抽出して AI と対話できます。

### 3. デッドマンズスイッチ (Fail-safe)
PC がスリープしたり電源が切れたりしても、OS のスケジューラーが次回の復帰時に自動的に再開させます。複雑なプロセス管理や監視を必要とせず、堅牢な運用が可能です。

---

## データ構造 (Data Structure)

- **`.kage/tasks/*.md`**: Pydantic をベースとした YAML フロントマター形式で、AI への指示と実行スケジュールを管理します。
- **`~/.kage/kage.db`**: タスクの最終実行時刻や、各コネクターの既読メッセージ ID などの状態（State）を SQLite で管理します。
- **`~/.kage/config.toml`**: 使用する AI エンジン、各プラットフォームの API トークン、および実行間隔などのグローバル設定を保持します。
