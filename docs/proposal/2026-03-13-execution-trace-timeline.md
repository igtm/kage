# 実行プロファイルとタイムラインの可視化 (Execution Trace & Timeline Visualization)

## Summary

長時間の自律タスクが「どこに時間とコストを費やしたか」を事後分析するため、ツール実行（Shell, File I/O）や LLM 推論の待ち時間を Chrome Trace Event 形式 (JSON) などで記録し、タイムラインやフレームグラフとして可視化可能にする提案。

## Problem

`kage` による夜間バッチなどの長時間タスク（数十分〜数時間）が完了、あるいは失敗した際、テキストベースのログや `kage tail` の出力だけではパフォーマンスのボトルネックを特定するのが困難です。
「なぜ3時間もかかったのか？」「`npm install` やテスト実行のシェルコマンドが遅かったのか？」「LLM API の応答（Thinking / Streaming）に時間を取られていたのか？」「無駄なリトライループに陥っていたのか？」を直感的に把握する手段がなく、タスクのプロンプト改善やコスト最適化（Task Authoring）に繋げにくいという課題があります。

## Proposal

`kage` の内部エグゼキューターおよびツール呼び出しの各ステップに、軽量なトレーシング（計装）を追加します。

1. **イベントの記録**:
   - LLM API リクエストの開始と完了（待ち時間）
   - `run_shell_command` ツールの実行（コマンドごとの所要時間）
   - `read_file` 等の I/O 操作
2. **トレースファイルの出力**:
   - 実行終了時（または定期的に）、`.kage/memory/{task_name}/YYYY-MM-DD-trace.json` として Chrome Trace Event 形式互換の JSON を出力します。
3. **可視化のサポート**:
   - ユーザーは出力された JSON を `chrome://tracing` や [Perfetto](https://ui.perfetto.dev/) にドロップするだけで、エージェントの行動のタイムライン（Flamegraph）をグラフィカルに確認できます。
   - ゆくゆくは `kage ui` (Global Dashboard) にも簡易的なタイムラインビューを統合します。

## Inspiration

- **Playwright Trace Viewer**: E2E テストの実行ログをタイムラインやスクリーショットとともに事後解析できる優れた DX。
- **Chrome DevTools / Perfetto**: パフォーマンスプロファイリングの標準 UI。
- **OpenTelemetry / LangSmith**: LLM アプリケーションのチェーン実行時間の可視化とトレーシング。

## Expected Daily Benefit

「自律エージェントの行動最適化」という高度なデバッグが視覚的かつ容易になります。ボトルネックがシェルスクリプト側にあるのか、LLM の推論遅延（あるいは無駄なツール呼び出しの反復）にあるのかが一目でわかるようになり、プロンプトの改善（不要なファイルの読み込みを減らす、シェルの実行方法を変える等）のフィードバックループが高速に回せるようになります。

## Scope and Non-Goals

- **Scope**: コア実行エンジンへの軽量なタイムスタンプ計測（Trace Event生成）の実装と、標準的なフォーマット（Chrome Trace JSON等）でのファイル出力。
- **Non-Goals**: 高度な分散トレーシング（JaegerやDatadogへのリアルタイム送信）はやりすぎであり初期スコープ外です。ローカルの JSON ファイルによる事後分析に特化します。

## Risks or Open Questions

- トレースファイルの肥大化: 何時間もループし続けるタスクの場合、JSON ファイルが MB 単位に膨らむ可能性があるため、ログローテーションや圧縮（gzip）を検討する必要があります。
- LLM の Thinking Time（推論時間）と Token Streaming の時間の切り分けをどこまで厳密に記録するか。

## Suggested Rollout

1. **Phase 1**: `run_shell_command` と LLM 呼び出しの 2 つの主要なブロックのみ時間を計測し、タスク終了後に簡易的な集計を stdout に表示する。
2. **Phase 2**: Chrome Trace Event 互換の JSON 出力（`.kage/memory/` 配下）の実装。
3. **Phase 3**: Dashboard UI への統合、または CLI 上での `kage trace view` コマンドによる簡易ビューアの提供。