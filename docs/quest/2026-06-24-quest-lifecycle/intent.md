# Quest Lifecycle — Design & Intent

Date: 2026-06-24
Status: Proposal / Prototype skeleton

## Goals

- Introduce a second lifecycle alongside `cron`, called **quest**, that lets a team of AI agents explore a vague direction autonomously for long stretches (target: 24h continuous).
- Model work as a **mind-map / task graph** (nodes + edges) instead of a linear checklist, so agents can branch, abort dead PoCs, and grow promising ones.
- Drive everything from the existing 1-minute `kage cron run` tick (no new daemon), to keep kage's stateless, OS-native philosophy.
- Provide runaway protection with a **max agent execution count** budget (other guards are future work).

## Non-Goals (this iteration)

- Wall-clock / token-cost budgets (designed for, not implemented).
- Human approval gates via connectors.
- Real LLM-decided graph expansion beyond a fixed role pipeline + simple verdict parsing.
- Web/TUI visualization beyond tabular CLI output.

## Lifecycle model

### Coexistence with cron

- A quest is created via `kage quest new` and stored in SQLite (`quests`, `quest_nodes`, `quest_edges` tables). It is **not** a `.kage/tasks/*.md` file.
- On every `kage cron run` tick, after scheduled cron tasks and connectors, the scheduler calls `quest.tick()` once. The tick dispatches at most one pending node per active quest (synchronously), reusing the existing executor so runs/logs/metadata remain uniform.
- Quests have no `cron` expression; activation is `status = active`. `kage quest stop` sets `status = stopped`; `kage quest resume` reactivates.

### Roles & team

Three role templates, each a provider + prompt skeleton that the runner materializes at dispatch time:

- **scout** — investigates current state of the repo/world for a hypothesis and emits new candidate hypotheses.
- **poc** — runs a minimal proof-of-concept for one hypothesis and emits a verdict (`promising` | `dead`) plus new directions.
- **strategist** — evaluates accumulated evidence, decides grow/abort, and may close the quest.

A quest declares which roles to enable and initial fans-out (e.g. N parallel scouts). The skeleton ships a fixed default team: `scout → poc → poc ... → strategist`.

### Task graph

- Each node: `role`, `hypothesis`, `status` (`pending` | `running` | `explored` | `aborted` | `growing`), `verdict`, `evidence`, `run_id`.
- Edges record `spawned` / `aborted_to` / `grew_to` relations with timestamps.
- Persistent in SQLite for queryability; CLI and (future) UI render the graph.

### Run loop (per tick, per active quest)

1. If `agent_runs >= max_agent_runs`, set `status = terminated` and skip.
2. Select the oldest `pending` node whose parent (if any) is not `running`.
3. Mark it `running`, build a role-specific prompt that includes the quest direction, ancestor evidence, and instructions to end with a fenced JSON block:
   ```json
   { "verdict": "promising" | "dead", "evidence": "...", "new_directions": ["..."] }
   ```
4. Synthesize an in-memory `TaskDef` (`mode: continuous`, no `task_file`) and call `executor.execute_task`. The run flows through normal logging/run history.
5. Parse the JSON block from stdout:
   - `promising` → mark node `explored`/`growing`, spawn child `poc` nodes for each `new_direction`.
   - `dead` → mark `aborted`, spawn a `strategist` node (debounced: at most one pending strategist per quest).
   - `strategist` run → may set quest `status = done`.
6. Increment `agent_runs`. Persist node/edge/quest updates.

### Termination conditions

Implemented now:

- **max_agent_runs** per quest (default 50). Hard stop → `terminated`.

Reserved in schema for future:

- `max_wall_minutes`, `max_token_budget` (columns present, not enforced yet).

Manual:

- `kage quest stop <id>` → `status = stopped` (ticks skip it).
- `kage quest abort-node <node_id>` → force node `aborted`.

## Schema (SQLite, added in `init_db`)

```sql
CREATE TABLE IF NOT EXISTS quests (
  id TEXT PRIMARY KEY,
  project_path TEXT NOT NULL,
  name TEXT NOT NULL,
  direction TEXT NOT NULL,
  status TEXT NOT NULL,            -- active | done | terminated | stopped
  max_agent_runs INTEGER NOT NULL DEFAULT 50,
  agent_runs INTEGER NOT NULL DEFAULT 0,
  roles_json TEXT,                 -- list of role names
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS quest_nodes (
  id TEXT PRIMARY KEY,
  quest_id TEXT NOT NULL,
  parent_id TEXT,
  role TEXT NOT NULL,
  hypothesis TEXT NOT NULL,
  status TEXT NOT NULL,            -- pending | running | explored | aborted | growing
  verdict TEXT,
  evidence TEXT,
  run_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS quest_edges (
  id TEXT PRIMARY KEY,
  quest_id TEXT NOT NULL,
  from_node TEXT,
  to_node TEXT,
  relation TEXT NOT NULL,          -- spawned | aborted_to | grew_to
  created_at TEXT NOT NULL
);
```

## CLI

```
kage quest new <name> --direction "..." [--project <path>]
                     [--max-agent-runs 50] [--roles scout,poc,strategist]
                     [--provider claude]
kage quest list
kage quest show <id>
kage quest stop <id>
kage quest resume <id>
kage quest abort-node <node_id>
```

`kage quest list` prints id, name, status, agent_runs/max, node counts. `kage quest show` prints the quest plus its node table and edges.

## Future work

- Wall-clock / token budgets and cost tracking.
- Connector approval gates at depth thresholds.
- Persisted role prompt overrides per quest.

## v2 — Owner-gated team model (2026-06-24)

### Motivation

現状スケルトンでは scout/poc が verdict を返すと Python の固定ルールで勝手に子ノードを spawn していた。これは「1 エージェントが独断で進める」構造で、LLM 1 個のミスが直接グラフに漏れる。1エージェントはまだミスが多いため、チームの総合力で戦いたい。

### New rule: owner-only graph mutation

- ロール `owner` を必ず 1 つ持つ。owner だけが **グラフの編集権** (新規ノード作成・状態更新・abort) を持つ。
- それ以外のロール (scout/poc/strategist) は `execute` と `report` だけ。verdict / new_directions は **「提案 (proposed node)」** として蓄えられ、即 spawn はされない。
- proposed ノードは `_select_pending_node` の候補から外れ、owner が `promote` action を出すまで実行されない。
- owner ノードは proposed が一定数溜まる OR 直近の子が abort 済 OR 待機中のノードが枯渇したときにだけ dispatch される (`_should_dispatch_owner`)。
- dispatch された owner は全子孫の evidence + proposed 一覧を受け取り、以下の actions を発する:
  ```json
  {
    "actions": [
      {"type":"promote", "node_id":"prop-001"},
      {"type":"abort",   "node_id":"nb-123"},
      {"type":"spawn",   "role":"poc", "direction":"..."},
      {"type":"finish",  "reason":"..."}
    ],
    "evidence": "..."
  }
  ```
- owner の verdict はグラフを直接変更せず、上記 action 列を `tick()` が検証付きで適用する。owner が未知の node_id や他人のノードを勝手に触ろうとしても `PermissionError` 相当で弾く。

### Provenance

proposed ノードには spawn 元 (`proposed_by` 列) と `relation=proposed_from` の edge を刻む。owner が誰の提案を触ったか追えるようにする。

### Web UI (kage ui)

追加 route:
- `GET /quests` — クエスト一覧 + 個別グラフ描画 SPA ページ
- `GET /api/quests` — 全クエスト + runs/max/roles JSON
- `GET /api/quests/{id}` — そのクエストの nodes + edges JSON

ページではノードを SVG で layered tree 描画。色 = 状態 (proposed は点線・pending 実線・aborted 赤・growing 緑)、owner ノードは王冠アイコンで区別。エッジは relation で々 (promote/grew_to/aborted_to/proposed_from)。

sample directory:
- `/quests` を `/runs` と同居させるのではなく独立 SPA 1ページにし、既存ダッシュボードのサイドバーから遷移。

### Non-goals (v2)

- owner の LLM 出力の actions を“完全 validation” するのはスコープ外。未知 ID / 不正 role くらいは弾くが、破壊的 action は基本信頼。
- 提案の自動間引き依然未実装。proposed が無限増殖しないよう上限は `max_agent_runs` で間接制御。

### Legacy compatibility

`quest create` に `--solo` を付けると旧ルール (scout/poc が直接 spawn) に戻る。デフォルトは **team モード (owner 付き)**。これにより v1 のテストは `--solo` で通る。

## v3 — Two-phase owner with council (2026-06-24, 設計のみ)

### Motivation

v2 の owner はグラフ編集権を独占するが、**owner 自身の LLM 1出力が bad action なら spawn/promote/abort 全部が曲がる**。owner が SPOF になっている。「1エージェントのミスを防ぐための owner が、owner 自身のミスで止まる」再帰リスクを解消する。

### Two-phase: design + run

owner の1出力を **design phase (協議) + run phase (実行)** の2段に分離:

1. **design phase**: owner は単独で判断せず **council** を招集。council は新ロール `council_member` の N 体(既定3)を**並列**に spawn する。各 member は同じ evidence + proposed を食べて**独立に plan を提案**する。
2. **run phase**: owner (chair) が複数案を比較・統合し、**1つの merged plan** を出す。tick がその merged plan を機械的に適用する(更なる LLM 呼び出し無し)。

### council_member ロール

```
Role: council_member
権限: execute + 提案 のみ (グラフ編集不可)
入力: 全完了ノード evidence + proposed 一覧 (owner と同じ)
出力: { "member_id": "A", "confidence": 0.8,
        "actions": [...], "dissent": "<他案との相違点>" }
```

- 既定3体。`kage quest new --council-size 5` で変更可

### owner (chair) の2段出力

design phase 完了後、owner は council_members の全案を比較し merged plan を出す:

```json
{"phase":"run","evidence":"...",
 "adopted_from":["A","C"], "dissent_handled":"Bは X で却下",
 "actions":[ {type:promote,...}, ... ]}
```

- 過半数一致で採用。分裂時は majority + rationale を必ず記録
- run phase の出力は tick が**機械的に**適用(更なる LLM 呼び出し無し)

### node 状態機械 (v3)

```
owner (pending)
  ↓ 待機: _should_dispatch_owner()
owner (running) ─ design phase
  ↓ spawn N× council_member (proposed, parallel)
owner (running) ─ 全 member 完了待ち
  ↓ chair: merge
owner (explored) ─ run phase 出力 → tick 適用
```

新 status: `council_pending` (member 完了待ち)。relation: `council_of` (owner→member), `council_reply` (member→owner)。

### 依存と非実装理由

- **並列実行**: council_members を1 tick 内で並列 spawn するには executor の非同期化が前提。現状 tick は1分1ノード同期のため、並列 council ができない。シリアル council (1 tick 1 member) でも design→run が N+2 tick かかり遅い
- そのため今回は **intent.md + HTML レポートに設計のみ追記**。executor 並列化が整ったら v3 実装に着手

### schema 予約 (将来)

- `quest_nodes.phase` 列: `design` | `run`
- `quest_nodes.role`: `council_member` 追加
- `quests.council_size` 列 (既定3)
- `quest_edges.relation`: `council_of` / `council_reply` 追加

### Legacy compatibility (v3)

- `--council-size 0` で v2 の単独 owner モードに戻る。テストはこの値で通す

## v3.1 — Looper-informed role design (2026-06-24, 設計のみ)

参考: [ksimback/looper](https://github.com/ksimback/looper) · [looper-spec.md](https://github.com/ksimback/looper/blob/main/looper-spec.md) · [@0xCodez loop engineering](https://x.com/0xCodez/status/2064374643729773029) · [@shannholmberg looper post](https://x.com/shannholmberg/status/2069323309024776456)

### なぜ looper から学ぶか

looper は「設計してから走らせる」層に特化し、council (reviewer / judge) と programmatic 検証で self-grading を排除する。**一人 owner が自前で決めて自前で評価する構造**は、looper が最も批判する「same model grading its own homework」に合致する。kage quest v2 の owner もそれに近く、v3 は looper の区別を取り込む。

### reviewer vs judge (v3.0 の council_member を置き換え)

| ロール | 権限 | 出力 | verdict_source になれるか | 使い所 |
|--------|------|------|--------------------------|--------|
| `reviewer` | execute + notes のみ | `{ "notes":[...], "dissent":"..." }` | ❌ なれない | ブレスト、adversarial、視点追加 |
| `judge` | execute + 構造化 verdict | `{ "verdict":"pass\|revise", "blocking_issues":[...], "confidence":0.0-1.0, "notes":"..." }` | ⭕ なれる | gate 進行を block する判定 |
| `owner` (chair) | グラフ編集 + gate 運営 | `actions[]` (merge 後) | — | 議長として merge のみ |

- `--council-size N` → `--council "<role>:<count>,..."` 形式へ拡張
  - 例: `--council "reviewer:2,judge:1"` (既定)
- `verdict_policy` を導入:
  - `revise_until_clean`: `verdict_source` が judge/human 必須。reviewer-only は禁止
  - `fixed_passes`: reviewer notes を N 回適用して proceed (clean 宣言しない)
- kage v2 の `NODE_STATUS_PROPOSED` は reviewer/judge 共通の「提案」のままでよい。ただし judge は verdict も同時に出し、owner が `verdict_source` 選定に使う

### 明示 gate

looper の `plan_gate` / `delivery_gate` に相当する gate ノードを導入:
- **scout_gate**: scout のEvidence 蓄積後、poc を走らせる前に reviewer/judge が quality check
- **poc_gate**: 各 poc 完了後、成長/撤退判定前に judge が verdict
- **synthesis_gate**: 戦略総括前に reviewer/judge が ROI 視点で verdict

各 gate は `phase` 列で識別。gate ノードは owner が spawn し、`council_members` を relation `council_of` で束ねる。gate の verdict_source が clean を出さない限り、次フェーズの work ノードは pending にならない。

### 検証の型 (programmatic | judge | human)

```yaml
verification:
  - id: tests-pass
    type: programmatic
    check: ["pytest", "tests/test_quest.py"]
    expect: exit_zero
  - id: evidence-enough
    type: judge
    rubric: "少なくとも2つの独立した scout/poc evidence が同一方向を示す"
  - id: human-ok
    type: human
    prompt: "Discord で #quest チャンネルに 📌 で同意してください"
```

- `programmatic`: kage は task runner なので既存 executor で実行可。**無料で deterministic**。looper が最推奨する型
- `human`: kage の connector (discord/slack/telegram) で consent を取れる。looper の human checkpoint と同じ

### loop_control (暴走防止の拡張)

v2 の `max_agent_runs` だけを置き換えず、looper 互換のガードセットへ:

```yaml
loop_control:
  max_iterations: 50          # = max_agent_runs の後方互換
  budget:
    tokens: 2_000_000
    wall_clock_min: 1440       # 24h
  no_progress:
    max_stalled_iterations: 3
    signals:
      - "同じ blocking issue が繰り返される"
      - "ノードの evidence が3ラウンド不変"
      - "proposed が promote されないまま累積"
    action: stop
  human_checkpoints: [scout_gate]   # connector 経由で consent
```

- `no_progress` は looper 由来。kage quest は「動いている間に実質進んでいない」状態を検知する必要がある (owner が堂々巡りすると v2 でも止まらない)
- `budget.wall_clock_min` は schema 確保済み列 `max_wall_minutes` と統合

### cross-model council (privacy)

```yaml
council:
  - id: reviewer-A
    role: reviewer
    cli: gemini
    provider: gemini
    scope: [scout, poc]
    privacy:
      sends: [evidence, proposed]
      redact: [".env", "secrets/**", "**/*.key"]
      consent: required
  - id: judge-B
    role: judge
    cli: claude
    provider: claude
    scope: [scout_gate, poc_gate]
    privacy:
      sends: [evidence, proposed, verdict]
      consent: required
```

- host(owner) と別 model family を推奨 (blind-spot coverage)。looper の推奨通り
- kage 既存の `quest.provider` (host 用) とは別に、council_members は**個別に provider** を持てる
- cross-vendor への送信は egress 宣言 + consent。kage connector で human approve 可能

### 状態機械 (v3.1)

```
work ノード(scout/poc/...) 完了
   ↓
owner (pending) — _should_dispatch_owner() gate
   ↓ design phase: gate spawn (scout_gate/poc_gate/...)
gate (pending)
   ↓ spawn N× council_member (relation: council_of)
reviewer/judge (proposed→running→explored)
   ↓ 各 member verdict/notes
gate (running) — chair merge
   ↓ verdict_source が "pass" → 次フェーズ work ノードを pending 化
   ↓ verdict_source が "revise" → 前フェーズ work ノードを保持し revision spawn
gate (explored)
   ↓ run phase: owner が merged actions[] を出し tick が適用
owner (explored)
```

新 status: `gate_pending` (member 完了待ち), `gate_revise` (revise 判定で前段差し戻し中)
新 relation: `council_of`, `council_reply`, `verdict_source_ref`

### kage に残る Non-goal (looper との差)

- looper は「loop 設計をファイルで書き出して hand off」が本質。**kage は設計を SQLite + tick に刻む**ので、loop.yaml/resolved.json 互換ではなく quest rows に正規化する
- looper の ASCII flow preview 相当は `/quests` Web UI が担う
- looper は durable orchestrator を明示的に外す。**kage は cron tick を durable orchestrator 代わりに使う**のでここは逆。looper 互換の「設計 JSON を外部 runner に渡す」は将来の `kage quest export` で対応可能

### 実装依存

- council_members の**並列実行**: executor の非同期化が前提 (v3 と同じ)
- **programmatic check**: 既存 executor で ``TaskDef(command=...)`` を即 dispatch する形で実装可。非同期化不要
- **human checkpoint**: connector に `quest_consent` source type を追加する小変更で可能

### Legacy compatibility (v3.1)

- `--council ""` で council 無し (v2 の team = owner 単独)
- `--council "reviewer:0,judge:0"` でも同じ
- `--solo` で v1
- 3モード階層: solo → team(v2) → team+council(v3.1)

## v3.2 — Team と社内工程 (planner→executer→accepter) (2026-06-24, 設計のみ)

### 動機

v3.1 までの `scout` / `poc` / `strategist` は「ロール」扱いで、1ノード=1LLM呼出。1回の呼出で「計画も実行も受け入れも同じモデル」になり、looper が批判する same-model-self-grade の構造を Team 内部で再生してしまう。ユーザーの指摘は「ロール→Team に格上げし、Team 内部で工程を分けろ。受け入れテスターが ng なら工程へ差し戻し。accept されて初めて owner に返せ」という階層化。

### 階層構造 (Team = 上位概念)

```
Owner (1, quest 全体の graph 編集者)
  │ dispatch work (direction + hypothesis)
  ▼
Team: scout / poc / strategist / ...   ← Team はロールではなく編成単位
  │ Team 内に工程 (stage) を3つ持つ
  ▼
  ┌─ planner   (具体タスク分解・計画)
  │      ↓
  ├─ executer (実行・証拠生成)
  │      ↓
  └─ accepter  (受け入れテスター: pass=ownerへ / ng=planner/executerへ差し戻し)
```

- **Team** は `scout Team` / `poc Team` / `strategist Team` のように、quest 方向性に沿った「職能チーム」として編成される。owner が「この hypothesis をこの Team に依頼」する単位。
- **各 Team は工程 (stage) を持つ**: `planner` → `executer` → `accepter`。各 stage は別の member (独立的 LLM 呼出)。
- **差し戻しループ**: accepter が reject すると planner/executer に戻る。`max_revisions` で暴走防止。cap超過は Team 失敗 verdict を owner に返し、owner が再判断。
- **accept** された場合のみ、Team は owner に対して構造化 verdict + evidence を returns。

### Team ノード / stage ノード

Quest graph 上で Team を <b>1ノード</b>、各 stage を <b>子ノード</b> で表現:

```
[parent work node] (owner が spawn)
  └── Team node (role=team, stage_container)
        ├── planner node      (role=member, stage=plan)
        ├── executer node     (role=member, stage=exec)
        │     ↑↓  (reject で revision loop)
        └── accepter node     (role=member, stage=accept)
```

- Team ノード `role` = `team_<kind>` (例: `team_scout`, `team_poc`, `team_strategist`)
- stage ノード `role` = `member`, 新列 `stage` = `plan|exec|accept`
- 新 relation: `stages_into` (Team → stage ノード), `rejects_to` (accepter → planner/executer), `accepts_to` (accepter → Team → owner)
- 新 status: `revising` (差し戻し中), `team_blocked` (max_revisions 超過)

### verdict flow

```
planner  → implements_plan
executer → executes, evidence 生成
accepter → { "verdict": "accept" | "reject",
             "blocking_issues": [...], "revision_target": "planner|executer",
             "evidence": "...", "confidence": 0.0-1.0 }
  accept  → Team verdictSpiel = 完了 + evidence → owner へ
  reject  → revision_target の stage ノードを再 spawn (relation: rejects_to)
              agent_runs++ 管理は Team
```

accepter は looper 互換の `judge` そのもの。Team の `verdict_source` = accepter が担当。これで reviewer-only の clean 宣言問題は解決。

### 各 engineering の粒度 (Team ごと調整可)

Kind は Team により「何を accept とするか」が異なる:

| Team | planner の仕事 | executer の仕事 | accepter の受け入れ基準 | revision target |
|------|----------------|----------------|--------------------------|-----------------|
| scout | 検索計画 (ファイル/ログ/外部) | 検索実行 | 「検索計画カバレッジ」と「仮説未解明」をjudge | planner (計画ミス) or executer (実行ミス) |
| poc | 検証計画 (最小コスト) | スクリプト作成実行実行 | `programmatic` (exit_zero or 指標しきい値) + judge | planner (コスト設計ミス) or executer (実装ミス) |
| strategist | 評価計画 (ROI軸) | 各ノードevidence を収束出力 | judge (ROI rubric) | planner (軸ミス) or executer (集約ミス) |

- `accepter` は `programmatic`/`judge`/`human` の3種類 (looper 互換)。poc Team は `programmatic` を推奨。
- `revision_target` は accepter が明示。planner の計画が正しく executer の実行が悪い場合は executer に差し戻し、計画自体が悪い thì planner に戻る — 失敗箇所を局所化。

### council (v3.1) との統合

v3.1 で設計した `reviewer` / `judge` は Team の **accepter** として再利用:
- Team に `--accept-mode "judge:1"` (judge 1体が accepter) が既定
- `--accept-mode "reviewer:2,judge:1"` とすると、**reviewer** 2体が「notes のみの reviewer」、**judge** 1体が「verdict 出せる accepter」 (verdict_source)
- reviewer の notes は planner/executer に feedback として戻り、judge のみが `accept` を出せる (looper の gate rule と互換)

### node 状態機械 (v3.2)

```
Team node (pending) ← owner dispatch (relation: stages_into)
  ↓
planner (proposed→running→explored)
  ↓ makes_plan
executer (proposed→running→explored)
  ↓ executes
accepter (proposed→running) — judge
  ├─ accept ─▶ Team (explored) ─▶ owner へ verdictdecken
  └─ reject ─▶ revision_target (revising) ─▶ planner/executer に戻る
                            └─▶ max_revisions 超過 → Team (team_blocked) → owner へ fail verdict
```

新 status: `revising`, `team_blocked`
新 relation: `stages_into`, `makes_plan`, `executes`, `rejects_to`, `accepts_to`, `verdict_source_ref`

### schema 予約

- `quest_nodes.team_kind`: `scout|poc|strategist|custom` (Team のほうの職能)
- `quest_nodes.stage`: `plan|exec|accept|revising` (工程)
- `quest_nodes.revision_count`: 差し戻し回数
- `quest_nodes.max_revisions`: Team ごと (既定 looper like 3)
- `quest_edges.relation` に `stages_into`, `makes_plan`, `executes`, `rejects_to`, `accepts_to`

### CLI

```
kage quest new <name> --direction "..." \
   [--mode team] \                           # solo|team
   [--teams "scout,poc,strategist"] \         # Team 編成
   [--accept-mode "judge:1"] \                # v3.1 verdict_policy 互換
   [--max-revisions 3] \                      # 工程ごと
   [--council "reviewer:2,judge:1"]          # accepter 候補メンバー
```

- `--mode solo`: v1 (直接 spawn)
- `--mode team` (既定) + `--council ""`: v2 相当 (owner は Team に 工程をスキップして1ノード dispatch する簡易挙動を legacy で提供)
- `--mode team` + `--council "..."`: v3.2

### 実装依存

- Team 内 stage は**直列**のため executor 非同期化不要。機能する tick に工程を step として乗せられる (planner 1 tick → executer 1 tick → accepter 1 tick)
- ただし revision loop で「同じ工程が何度も回る」ため、quest が長期化する。これは loop_control.no_progress の出番
- `accepter` の programmatic check は既存 `TaskDef(command=...)` dispatch で即対応可

### Legacy compatibility (v3.2)

- `--mode solo` で v1 (scout/poc 直接 spawn, 工程なし)
- `--mode team --council ""` で v2 (owner 単独, Team 内 工程スキップ = 1ノード dispatch)
- `--mode team --council "..."` で v3.2 (Team + 工程 + council accepter)
- 4モード階層: solo → team(v2) → team+council(v3.1) → team+stages+council(v3.2)

### デメリット (v3.2 追加分)

- **さらに遅い**: 1 work あたり planner+executer+accepter の最低3 tick (max_revisions 含めると 3+3*revisions)。24h 設計との整合は loop_control で保つ必要
- **Team ノードと stage ノードで graph が深くなり可視化が煩雑**: `kage ui /quests` で Team 折りたたみ表示が必要
- **accepter の judge が悪いと無限差し戻し**: `max_revisions` で do not let the host keep revising forever (looper の wisdom)
- **revision_target 判定の信頼性**: accepter が「planner のせい / executer のせい」を誤判定すると、間違った工程に差し戻されて無駄 revision が増える
- **ユーザーアクション寮**: quest を新規作るだけで `--teams`, `--accept-mode`, `--council`, `--max-revisions` と項目増。intent 入力の手間が跳ね上がる。将来的には default preset 化が必要