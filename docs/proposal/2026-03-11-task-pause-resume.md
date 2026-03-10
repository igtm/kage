# タスクのネイティブな一時停止・再開コマンド (Task Pause/Resume) の導入

## Summary
現在、`continuous` なタスクを一時的に停止したい場合、ユーザーは `.kage/tasks/*.md` ファイルをディレクトリ外に移動するか、拡張子を変更するなどのワークアラウンドを強いられています。タスクファイル（Markdown）の Frontmatter に `status: active | paused` の概念を導入し、CLI から `kage pause <task_name>` / `kage resume <task_name>` コマンドで直感的に切り替えられるようにする提案です。

## Problem
1. プロジェクトの状況変化（例: 対象の外部APIがメンテナンス中、一時的にエージェントの動作を止めて手動作業に集中したい、等）により、定期実行タスクを一時的に止めたいケースが頻繁に発生します。
2. 現状ではファイルを `.kage/tasks/` ディレクトリから退避させるか削除する必要がありますが、これを行うと Git の管理状態が変わり、元に戻す際の手間や不要な差分を生みます。
3. ディレクトリから退避させたタスクは一覧から消えてしまうため、過去に設定した「現在は休眠中のタスク」の存在を忘れてしまい、自動化資産の再利用性が低下します。

## Proposal
1. `Task` の YAML Frontmatter に `status` (または `enabled`) フィールドを追加します。デフォルトは `active` とします。
   ```yaml
   ---
   name: daily-lunchtime-insight
   mode: continuous
   status: paused  # active | paused | completed
   ---
   ```
2. `kage` のランナーは、`status: paused` に設定されているタスクを対象から除外（スキップ）し、無駄な API コールや実行エラーを防ぎます。
3. ユーザーの DX 向上のため、以下の CLI コマンドを追加します。
   - `kage pause <task-name>`: 対象タスクの Frontmatter を `status: paused` に書き換える。
   - `kage resume <task-name>`: 対象タスクの Frontmatter を `status: active` に書き換える。
   - `kage list`: 実行結果の一覧において、稼働中（▶️）や一時停止中（⏸️）のステータスアイコンを表示する。

## Inspiration
- **systemctl**: `systemctl disable` / `enable`
- **GitHub Actions**: Workflow の Disable / Enable UI
- **Taskwarrior**: 依存関係や優先度調整による実質的なタスクの `wait` 状態管理

## Expected Daily Benefit
- 開発中、不要になったりエラーを吐き続けているエージェントを、ファイルシステムを直接触ることなく `kage pause` コマンド一発で即座に止めることができます。
- Git 管理下のファイルを移動・削除せずに済むため、設定ファイルとしての「一時停止状態」をコミットしてチームや別環境と共有できます。
- `kage list` で休眠中のタスクが可視化されるため、「以前使っていたあの通知タスクを再開しよう」といった運用がしやすくなります。

## Scope and Non-Goals
- 指定期間後（例: `kage pause --for 24h`）に自動で Resume される機能は今回のスコープ外とし、まずは手動トグルのみとします。
- `autostop` モードにおける、タスク全完了時の自動的な `completed` への移行とは明確に区別し、本提案ではあくまで「ユーザー操作による一時停止」にフォーカスします。

## Risks or Open Questions
- **YAML の非破壊編集:** CLI から Frontmatter を書き換える際、ユーザーが書いたコメントやフォーマットを壊さずにパース・シリアライズできるライブラリ、または安全な正規表現ベースの置換処理を検討する必要があります。
- **Git の差分発生:** `kage pause` を実行すると Markdown ファイルが変更されるため `git status` に現れます。これは「設定の変更」としてコミット可能であるため仕様として許容しますが、気にするユーザー向けにローカルの一時設定を優先する機構が将来的に必要になるかもしれません。

## Suggested Rollout
1. スキーマ定義の拡張: `Task` モデルへの `status` フィールド追加と、ランナー側でのスキップロジックを実装。
2. CLI コマンドの追加: `kage pause` / `resume` の追加と、安全な YAML 置換処理の実装。
3. UI の更新: `kage list` の出力フォーマットを改修し、ステータスを可視化。
