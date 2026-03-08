# kage 開発オーバービュー

## 開発フロー
1.  **実装**: 各機能の要件に従ってコードを記述します。
2.  **品質管理**: 実装完了後、必ず以下のコマンドを実行してコードの整形とリンターチェック（自動修正）を行ってください。
    ```bash
    uvx ruff format . && uvx ruff check . --fix
    ```
3.  **検証**: テストを実行し、期待通りに動作することを確認します。

## リリース前チェック
- version を上げる前に、機能本体だけでなく関連するユーザー向け導線も必ず更新します。
- 少なくとも以下を確認・更新します。
  - `README.md`
  - `README_JA.md`
  - `skills/kage/SKILL.md`
  - `kage doctor` の診断・説明
  - `kage --help` / `kage task --help` などの help 導線
  - `kage task new` の生成テンプレート
  - `kage task show` などの表示項目
- `.rulesync/rules/` を更新したあとは、必ず `npx rulesync generate` を実行して生成物を同期してから commit します。

## PR と release label
- PR を作るときは、完了報告の前に必ず release label の要否を判定し、その結果を PR に反映します。判定を省略してはいけません。
- プロダクトの挙動や配布パッケージに影響する変更で PR を作るときは、PR 作成時点で必ず release label を 1 つだけ付けます。label を付ける前に PR 作成タスクを完了扱いにしてはいけません。
- 付ける label は次の 3 つのどれか 1 つです。
  - `release:major`: 破壊的変更、既存ユーザーの移行が必要な変更、互換性を壊す CLI/設定変更
  - `release:minor`: 新機能、ユーザー向けコマンド追加、既存互換を保った機能拡張
  - `release:patch`: バグ修正、小さな UX 改善、互換性を壊さない既存機能の修正
- `release:major` / `release:minor` / `release:patch` を複数同時に付けてはいけません。
- 今回のような GitHub Actions 整備、CI/開発環境の調整、rulesync 整備、内部リファクタ、プロダクト挙動に影響しない docs 更新は release label なしで PR を作成します。
- release label が必要なのにリポジトリに存在しない場合は、PR を閉じる前にその label を作成してから付けます。
- `gh pr create` や同等のコマンドで PR を作成するときは、release label が必要な変更なら作成時に付けるか、作成直後に必ず追加します。
- PR 作成後は `gh pr view` などで最終状態を確認し、release label が必要な変更では該当 label がちょうど 1 つ付いていることを確認するまで完了扱いにしてはいけません。
- release label を付けないケースでも、「意図的に label なし」と判断したことを PR 本文または最終報告で明記します。label の付け忘れを release label なしと扱ってはいけません。

## 設計指針
- **自律性**: AIエージェントが自らタスクを管理し、継続的にプロジェクトを改善できる設計を維持します。
- **透明性**: すべての実行ログとメモリの変更を追跡可能にします。
- **シンプルさ**: 不要な複雑さを避け、Markdownベースのタスク定義など、直感的なインターフェースを優先します。
