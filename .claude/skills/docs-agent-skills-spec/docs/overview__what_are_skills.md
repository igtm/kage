URL: https://agentskills.io/what-are-skills

# What are skills?

Agent Skills は、AI エージェントの能力を拡張するための軽量でオープンなフォーマットです。
その核心は `SKILL.md` ファイルを含むフォルダであり、エージェントが特定のタスクを実行する方法を指示します。

## スキルの基本構造
```
my-skill/
├── SKILL.md          # 必須: 命令 + メタデータ
├── scripts/          # 任意: 実行可能なコード
├── references/       # 任意: ドキュメント
└── assets/           # 任意: テンプレート、リソース
```

## スキルの仕組み (Progressive Disclosure)
コンテキストを効率的に管理するために、以下の 3 段階で動作します。
1. **Discovery (検出)**: 起動時に `name` と `description` のみを読み込み、関連性を判断。
2. **Activation (有効化)**: タスクがスキルの説明に一致した場合、`SKILL.md` の全文を読み込む。
3. **Execution (実行)**: 指示に従い、必要に応じてスクリプトの実行やリソースの読み込みを行う。

## SKILL.md ファイル
YAML フロントメタデータと Markdown 命令で構成されます。
```markdown
---
name: pdf-processing
description: Extract text and tables from PDF files, fill forms, merge documents.
---

# PDF Processing

## When to use this skill
...
```

### フロントメタデータの必須フィールド
- `name`: 短い識別子
- `description`: スキルをいつ使用すべきかの説明

### 特徴
- **自己文書化**: 読みやすく、監査や改善が容易。
- **拡張性**: 単なるテキスト指示から複雑な実行コードまで対応可能。
- **ポータブル**: 単なるファイル群であるため、編集・バージョン管理・共有が容易。
