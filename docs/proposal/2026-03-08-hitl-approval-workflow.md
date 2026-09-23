# Human-in-the-Loop (HITL) 承認ワークフローの導入

## Summary

自律エージェントの処理の途中で、人間の確認・承認（Approval）を要求し、承認されるまで後続タスクの実行を一時停止（Pause）する機能の提案。

## Problem

`kage` は「夜間に自律稼働し、朝に結果を得る」ことを主眼としていますが、実際の業務や開発フローでは「最終的なデプロイ」「PRの main へのマージ」「外部API経由での決済や送信」など、完全に自律化するにはリスクが高く、必ず一度人間の目視確認（セーフガード）を挟みたいステップが存在します。
現在の `kage` は `continuous` や `autostop` で最後まで走り切るか、エラーで落ちるかの二択であり、安全のためにタスク自体を細かく分割して手動で順次起動しなければならないという運用コストが生じています。

## Proposal

AI エージェントが特定の条件を満たした際、またはフロントマターで指定された重要なサブタスクに到達した際に、実行を一時停止してユーザーの承認を待つ機能を追加します。

1. **承認要求のトリガー**:
   AI が出力に特定のタグ（例: `<kage_request_approval>マージして良いですか？</kage_request_approval>`）を含めた場合、または `task.json` のサブタスクに `requires_approval: true` が設定されている場合、タスク状態が `pending_approval` に移行します。
2. **Connector 経由での通知と応答**:
   Slack や Discord の Connector を通じて、「承認待ち」の通知が送信されます。ユーザーがチャット上で特定のコマンド（例: `@kage approve` や `👍` リアクション）を返すか、`kage ui` 上で「Approve」ボタンを押すまで、以降の cron 実行では該当タスクはスキップ（Pause）されます。
3. **実行の再開**:
   承認（または拒否/フィードバック）を受け取ると、次回の cron 実行時にその結果（例: `User approved the action.`）がメモリ（プロンプト）に注入され、タスクが再開されます。

## Inspiration

- **GitHub Actions**: Environments における `Required reviewers` 機能（本番デプロイ前の承認ステップ）。
- **Slack / Discord Bots**: インタラクティブな Message Buttons や Reaction を用いた承認フロー。
- **Claude Code / OpenHands**: 破壊的なコマンド（rm や git push など）を実行する前に、CLI 上でユーザーに `y/n` のプロンプトを出す仕組みの非同期版。

## Expected Daily Benefit

「下書き作成やテスト実行までは夜間に全自動でやらせておき、朝起きたらスマホの通知で内容を確認し、問題なければボタン1つで本番反映（残りのタスク）を完了させる」という、安全性と完全自動化の良いとこ取りが可能になります。これにより、リスクの高いタスクも `kage` に安心して任せられるようになります。

## Scope and Non-Goals

- **Scope**: タスク状態としての `pending_approval` の定義、通知の送信、および承認アクション（CLI、UI、チャット経由）の受け付けによるタスク再開機能。
- **Non-Goals**: 複雑な多段階承認（N人の承認が必要など）や、ユーザーごとの詳細な権限管理（RBAC）はスコープ外とします。個人のローカルマシンや小規模チームでの運用を想定したシンプルなトグルとしての承認を目標とします。

## Risks or Open Questions

- **Timeout の扱い**: ユーザーが数日間承認を放置した場合にどうするか。デフォルトで N 時間経過したら `auto-reject` または `auto-approve` にするオプションが必要かもしれません。
- **ポーリングのタイミング**: Connector（Slack/Discord）からの応答を拾うには `poll = true` が必要ですが、cron 実行の合間にユーザーが承認した場合、即時再開するのか、それとも次の cron ティックまで待つのかの設計。（OS-native なスケジューラに依存しているため、基本は次の cron ティックでの再開となるのが自然な制約です）。

## Suggested Rollout

1. **Phase 1**: CLI および `kage ui` 上での手動承認（`kage task approve <task_name>`）と、AI 出力タグによる `pending_approval` 状態への遷移を実装。
2. **Phase 2**: Connector (Slack / Discord) への承認待ち通知の送信と、ポーリングによるチャットからの承認アクション（リアクションやリプライ）の拾い上げ。
3. **Phase 3**: フロントマター (`.kage/tasks/*.md`) での `timeout_hours` や `default_action: reject` などの高度な承認設定の追加。
