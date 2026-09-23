# 実行結果のアーティファクト(画像・PDF・Markdown)の通知添付サポート

## Summary

Slack や Discord 等の Connector 完了通知時に、タスクが生成した成果物ファイル（Markdown、画像、CSV など）を自動添付してアップロードする機能。

## Problem

現在の `kage` の中核となる理念は「Go to sleep. Wake up to results.」ですが、Connector による完了通知を受け取っても、具体的な成果物（例：OCR ベンチマークの比較表、アーキテクチャ監査レポート、生成されたグラフ画像など）を確認するには、朝に PC を開いてローカルディレクトリや kage UI を確認する必要があります。
スマートフォン等で通知を受けた瞬間に「実際の結果」を閲覧できないのは、日々の運用における UX 上のボトルネックとなっています。

## Proposal

タスクが完了し Connector 経由で通知を送信する際に、指定された成果物ファイルを添付してメッセージを送れるようにします。

設定方法として以下の2パターンのいずれか（あるいは両方）をサポートします。

1. **フロントマターでの静的指定（glob 対応）**
   `.kage/tasks/*.md` に `artifacts` フィールドを追加します。
   ```yaml
   artifacts:
     - "benchmark/RANKING.md"
     - "benchmark/results/*.png"
   ```

2. **エージェントからの動的指定 (Memory 連携)**
   AI エージェントがタスクを完了した際、`.kage/memory/` 内の当日のステータスに `artifacts` のリストを書き込むことで、動的に生成されたファイル名を Connector に渡せるようにします。

Connector (Slack/Discord/Telegram 等) はこのパスを読み取り、タスク完了通知のメッセージにこれらのファイルを添付（`files.upload` 等）して送信します。

## Inspiration

- **GitHub Actions**: `actions/upload-artifact` による成果物の保存と、Slack 等へのダイレクトなレポーティング体験。
- **Airflow / Dagster**: 実行完了時の Asset の可視化と通知連携。

## Expected Daily Benefit

PC を開かずとも、スマートフォンに届いた Slack/Discord 通知を見るだけで、夜間にエージェントが作成した「具体的な分析結果（表やグラフ）」を即座に確認できます。
これにより朝の状況把握が圧倒的にシームレスになり、「Wake up to results」の体験が劇的に向上します。

## Scope and Non-Goals

- **Scope**: ローカルに存在する指定ファイル群を、Slack / Discord などの Connector を経由してタスク完了メッセージとともにアップロードする処理の実装。
- **Non-Goals**: アーティファクトのクラウドストレージ（S3等）への永続的な保存やバージョン管理は `kage` の責務外とし、あくまで通知体験の向上に特化します。

## Risks or Open Questions

- **ファイルサイズの制限**: 各チャットプラットフォームの API にはアップロード上限サイズ（例: Discordの無料枠で25MB等）があるため、超過した場合は「ファイルが大きすぎるためスキップした」旨の警告を通知文にフォールバック表示するエラーハンドリングが必要です。
- **セキュリティ・プライバシー**: 意図せず `.env` や秘密鍵をアップロードしてしまう事故を防ぐため、ワークスペースの `.gitignore` に含まれるファイルはデフォルトでアーティファクト対象外とするなどのセーフガード（Safe-guard）が求められます。

## Suggested Rollout

1. **Phase 1**: フロントマター (`.kage/tasks/*.md`) の `artifacts` リストによる静的パスのサポート。
2. **Phase 2**: 各 Connector プラットフォーム（Slack, Discord）側のファイルアップロード API 実装とエラーハンドリングの追加。
3. **Phase 3**: glob パターンの解釈、およびエージェントからの動的なアーティファクト指定（Memory 経由）のサポート。
