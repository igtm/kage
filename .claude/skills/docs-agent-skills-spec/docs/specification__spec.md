URL: https://agentskills.io/specification

# Specification

Agent Skills フォーマットの完全な仕様。

## ディレクトリ構造
最小構成は `SKILL.md` を含むディレクトリです。
```
skill-name/
└── SKILL.md          # 必須
```
オプションで `scripts/`, `references/`, `assets/` などのディレクトリを含めることができます。

## SKILL.md フォーマット
YAML フロントメタデータとそれに続く Markdown コンテンツで構成されます。

### フロントメタデータ (必須)
```yaml
---
name: skill-name
description: A description of what this skill does and when to use it.
---
```

| フィールド | 必須 | 仕様 |
| :--- | :--- | :--- |
| `name` | Yes | 1-64 文字。小文字英数字とハイフンのみ。ハイフンで開始・終了不可。連続ハイフン不可。ディレクトリ名と一致する必要がある。 |
| `description` | Yes | 1-1024 文字。スキルの機能と使用タイミングを記述する。 |
| `license` | No | ライセンス名またはライセンスファイルへの参照。 |
| `compatibility` | No | 最大 500 文字。特定の環境要件（製品、システムパッケージ、ネットワークアクセス等）。 |
| `metadata` | No | 任意のキー・バリュー マップ。 |
| `allowed-tools` | No | 事前承認されたツールのスペース区切りリスト（実験的）。 |

### ボディコンテンツ
フロントメタデータ以降の Markdown 部分。構造に特定の制限はありませんが、以下のセクションが推奨されます：
- ステップバイステップの指示
- 入出力の例
- 一般的なエッジケース

## オプションディレクトリ
- **`scripts/`**: エージェントが実行可能なコード。Python, Bash, JavaScript などが一般的。
- **`references/`**: 必要に応じて読み込まれる追加ドキュメント（`REFERENCE.md`, `FORMS.md` 等）。
- **`assets/`**: 静的リソース（テンプレート、画像、データファイル）。

## Progressive Disclosure (段階的開示)
1. **Metadata (~100 tokens)**: `name` と `description` は起動時に読み込まれる。
2. **Instructions (< 5000 tokens 推奨)**: `SKILL.md` 全体はスキル有効化時に読み込まれる。
3. **Resources (随時)**: スクリプトや参照ファイルは必要になった時のみ読み込まれる。

## ファイル参照
スキル内のファイルを指す際は、スキルルートからの相対パスを使用します。
```markdown
See [the reference guide](references/REFERENCE.md) for details.
scripts/extract.py
```

## バリデーション
`skills-ref` ライブラリを使用してチェック可能です。
```bash
skills-ref validate ./my-skill
```
