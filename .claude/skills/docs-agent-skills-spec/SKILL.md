---
name: docs-agent-skills-spec
description: Agent Skills フォーマットの仕様および技術ドキュメント。SKILL.md の作成方法やディレクトリ構造、統合方法などの情報を提供します。
---

# Agent Skills Spec Skill

このスキルは、Agent Skills フォーマットの公式仕様（https://agentskills.io/）に関する包括的なドキュメントを提供します。

## 概要

Agent Skills は、AI エージェントが特定のツールや知識を利用するための標準化されたパッケージフォーマットです。

### 主な特徴

- **標準化**: `SKILL.md` による統一された記述形式
- **自己完結**: 必要なドキュメントと知識を一つのディレクトリに集約
- **ポータビリティ**: 様々な AI エージェント（Claude, Copilot, etc.）で再利用可能

## このスキルの使い方

Agent Skills の作成、仕様の確認、または統合方法について質問された場合、`docs/` ディレクトリ内の適切なファイルを参照してください。

### ドキュメント構成

- `docs/specification__spec.md` - `SKILL.md` の記述ルールやフロントマターの仕様
- `docs/overview__intro.md` - 基本的な概念と設計思想

## クイックリファレンス

### よくある質問への対応

**「SKILL.md の書き方は？」**
→ `docs/specification__spec.md` を参照

**「Agent Skills とは何？」**
→ `docs/overview__what_are_skills.md` を参照
