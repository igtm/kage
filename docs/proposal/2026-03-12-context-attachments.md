# 静的コンテキストの事前注入 (Context Attachments / Pinned Context) の導入

## Summary

タスクのフロントマターで `attachments` フィールドをサポートし、指定されたファイル群やURLの内容を、AIエージェントの実行開始前に自動で読み込んでコンテキストとして事前注入（Pre-inject）する仕組みの提案。

## Problem

`kage` のタスクが夜間に起動し、自律的にコードの修正や分析を行う際、エージェントが「どのドキュメントを読み、どの型定義を参照すべきか」を自ら探索（`ls` や `cat` などのツール呼び出し）するプロセスが発生します。
しかし、この自律探索には以下の課題があります。
1. **探索コストとレイテンシ**: 必要な情報を探すための無駄なツール呼び出し（APIターン）が発生し、コスト増と実行時間の大幅な遅延を招く。
2. **再現性と安定性の低下**: エージェントが重要なドキュメントを見逃したり、誤ったファイルを参照したりすることで、タスクが失敗する確率が上がる。
3. **継続的実行の無駄**: `continuous` や `autostop` モードで繰り返し実行されるタスクにおいて、毎回の run で同じ探索手順を繰り返すのは非常に非効率。

## Proposal

タスク定義の YAML フロントマターに `attachments` (または `context_files`) フィールドを追加し、静的なコンテキストを明示的に「ピン留め」できるようにします。

```yaml
---
name: API Client Generator
cron: "0 2 * * *"
provider: claude
attachments:
  - "docs/ARCHITECTURE.md"
  - "src/types/*.ts"
  - "https://raw.githubusercontent.com/example/repo/main/openapi.json"
---
# Task Instructions...
```

**動作の仕組み**:
1. `kage run` がタスクをフックした際、対象となるローカルファイル（globパターン対応）や外部URLを自動でフェッチする。
2. 取得したテキスト内容を、適切な XML タグ（例: `<file path="...">...</file>`）でラップする。
3. エージェントの System Prompt または User Prompt の先頭にこれらを付与した上で、初回の推論API呼び出しを行う。

## Inspiration

- **Cursor / Copilot Chat**: ユーザーが `@Files` や `#docs` で明示的にコンテキストを指定し、AIに即座に読ませる体験（Context Pinning）。
- **Claude Artifacts / Projects**: プロジェクト全体に共通するナレッジベースを事前にアップロードしておく機能。
- **aider**: 起動時に引数でファイルを指定して、初手からコンテキストに乗せる挙動。

## Expected Daily Benefit

- **ゼロショットの成功率向上**: エージェントが初手から正確で完全な前提知識を持った状態でタスクに取り組めるため、ハルシネーションや「情報不足による失敗」が激減します。
- **実行時間とトークンコストの節約**: 探索のための余分なAPI呼び出し（ツールチェーン）をスキップできるため、毎回の cron tick がより速く、安価に完了します。
- **Task Authoring のDX向上**: 「このドキュメントを読んでから実装して」と自然言語で指示する代わりに、`attachments` に書くだけで確実に読み込まれるという予測可能性（Predictability）が得られます。

## Scope and Non-Goals

- **Scope**:
  - ローカルのテキストファイル読み込み（glob展開を含む）
  - 基本的な HTTP GET による raw テキストや JSON などの外部 URL の読み込み
  - ファイル内容のメタデータ付きインジェクション
- **Non-Goals**:
  - ベクトル検索（RAG）の導入（これは静的な全文インジェクションに特化します）
  - 複雑なウェブスクレイピングや、認証が必要なURLのフェッチ
  - 動的にコンテキストを生成・変更する仕組み（別提案の Dynamic Context Variables でカバー）

## Risks or Open Questions

- **コンテキストウィンドウの枯渇**: Glob パターンで `src/**/*.ts` のように大量のファイルを指定した場合、プロンプトのトークン制限を簡単に超過するリスクがあります。`kage` 側でトークン数の概算を行い、超過しそうな場合は Warning を出す、あるいは安全装置として自動で Truncate する機能が必要になるかもしれません。
- **バイナリファイルのハンドリング**: 画像や PDF などを `attachments` に指定した場合の挙動。Vision モデル対応や OCR プラグイン等とどう連動させるかが設計上の論点です。

## Suggested Rollout

1. **フェーズ 1**: ローカルファイルの絶対パス・相対パスによる読み込みとインジェクションを実装。
2. **フェーズ 2**: Glob パターンの展開をサポート。
3. **フェーズ 3**: HTTP URLからのフェッチサポートおよび、トークン制限保護（Token Limit Guardrail）の導入。
