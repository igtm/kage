# タスクの実行前検証 (Task Prerequisites Check)

## Summary
`kage` のタスク実行前に、必要な環境変数やコマンド、ネットワーク接続などが満たされているかを事前検証し、条件が揃っていない場合はAIエージェントを起動せずに（APIコストを消費せずに）早期終了させる機能の提案。

## Problem
現在、`kage` は設定されたスケジュールに従って無条件にAIエージェント（`claude`, `gemini` など）を起動します。
しかし、例えば以下のようなケースにおいて、AIが起動してからエラーに気づくのは非常に非効率です。
1. **環境変数の欠落**: デプロイや外部APIを利用するタスクで、必須のAPIキー（`AWS_ACCESS_KEY_ID` など）が設定されていない。
2. **ツールの不在**: タスク内で `docker` や `terraform` を使う想定だが、実行環境（ホストOS）にインストールされていない、あるいはデーモンが起動していない。
3. **無駄なコストとトークン消費**: AIは「コマンドが見つかりません」や「認証エラー」という結果を受け取ってから自己修復を試みたり、エラー終了したりするため、本来不要なプロンプト入力のAPIコスト（Token）と実行時間が浪費される。

## Proposal
タスクのフロントマターに `prerequisites` フィールドを追加し、実行前の静的な検証ルールを定義できるようにします。

```yaml
---
name: Infrastructure Deployment
cron: "0 3 * * *"
mode: autostop
prerequisites:
  env:
    - AWS_ACCESS_KEY_ID
    - AWS_SECRET_ACCESS_KEY
  commands:
    - terraform
    - aws
  network:
    - https://api.aws.amazon.com
---
```

この設定がある場合、`kage` は `cron` などのスケジューラから呼び出された直後（AIのLLMを呼び出す前）に、軽量な事前チェック（Pre-flight check）を行います。
チェックに失敗した場合は、AIプロセスを一切起動せず、タスクのステータスを `skipped` または `failed (prerequisites missing)` として記録し、Dashboard や通知連携を通じてユーザーに欠落している要件をアラートします。

## Inspiration
- **GitHub Actions (`needs` / `if` conditions)**: ジョブの実行前に環境や条件を評価し、無駄なRunnerの起動を防ぐ仕組み。
- **Homebrew (`brew doctor`) / Checkov**: ツール実行前にシステム環境が健全かを診断するアプローチ。

## Expected Daily Benefit
- **コスト保護 (Cost Savings)**: どうせ失敗するタスクのために、高額なLLMのコンテキスト読み込みコスト（API費用）を支払う事故を完全に防ぎます。
- **トラブルシューティングの迅速化**: 「AIが何かに失敗した（ログを追う必要がある）」ではなく、「`AWS_ACCESS_KEY_ID` が無いから開始できなかった」と根本原因が即座に通知されるため、人間がすぐに設定を修正できます。

## Scope and Non-Goals
- **Scope**: 環境変数（`env`）、実行可能コマンドパス（`commands`）、および単純なHTTPエンドポイント到達性（`network`）の事前検証機能の追加。
- **Non-Goals**: 複雑なシェルスクリプトによる事前チェック（脆弱性やサンドボックス破壊のリスクを避けるため、あくまで静的で安全な宣言的チェックに留める）。

## Risks or Open Questions
- **OS間での動作差異**: `commands` の有無判定について、Linux (`which`) と macOS (`command -v`) や Windows (`where`) での差異を隠蔽する実装が必要です。
- **動的な環境変数**: `.env` ファイルや `config.local.toml` からタスク実行直前に動的ロードされる環境変数を、どのタイミングで評価するか（Pre-flightの前にロードを完了させる必要がある）。

## Suggested Rollout
1. まずは最も重要で実装が容易な `prerequisites.env`（環境変数の必須チェック）からサポートし、フロントマターのパーサとバリデータに組み込む。
2. その後、`commands` によるコマンド存在チェックを追加する。
3. 検証失敗時のDashboard表示と通知（「要件不足でスキップ」）のUXを整備する。
