"""Quest lifecycle: an event-driven, team-based alternative to the cron lifecycle.

A quest is a long-running, mind-map style exploration owned by a team of role
agents (scout, poc, strategist). The existing 1-minute `kage cron run` tick
calls :func:`tick` once per tick; tick dispatches at most one pending node per
active quest by materializing a role-specific prompt and reusing the normal
executor (so runs/logs/history stay uniform).

Runaway protection is provided by a per-quest ``max_agent_runs`` budget.

v2 — Owner-gated team model
---------------------------
By default (:data:`QuestMode.TEAM`) the quest owns a mandatory ``owner`` role.
Only the owner is allowed to mutate the task graph; scout/poc/strategist merely
execute and emit **proposed** nodes. The tick defers owner dispatch until
enough evidence has accumulated, forcing team-wide consensus.

Pass ``--solo`` to :func:`create_quest` to fall back to the legacy "any role may
spawn" behaviour used by v1.
"""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

from .config import KAGE_DB_PATH
from .db import init_db
from .parser import ExecutionMode, TaskDef

QUEST_STATUS_ACTIVE = "active"
QUEST_STATUS_DONE = "done"
QUEST_STATUS_TERMINATED = "terminated"
QUEST_STATUS_STOPPED = "stopped"

NODE_STATUS_PENDING = "pending"
NODE_STATUS_RUNNING = "running"
NODE_STATUS_EXPLORED = "explored"
NODE_STATUS_ABORTED = "aborted"
NODE_STATUS_GROWING = "growing"
NODE_STATUS_PROPOSED = "proposed"

ROLE_SCOUT = "scout"
ROLE_POC = "poc"
ROLE_STRATEGIST = "strategist"
ROLE_OWNER = "owner"

_VERDICT_PROMISING = "promising"
_VERDICT_DEAD = "dead"

_DEFAULT_ROLES = [ROLE_SCOUT, ROLE_POC, ROLE_STRATEGIST, ROLE_OWNER]
_TEAM_ROLES = [ROLE_SCOUT, ROLE_POC, ROLE_STRATEGIST]
_DEFAULT_MAX_AGENT_RUNS = 50

# Owner dispatch thresholds (team mode).
_OWNER_MIN_PROPOSED = 1
_OWNER_MIN_CHILDREN_COMPLETED = 1


class QuestMode(str, Enum):
    SOLO = "solo"
    TEAM = "team"


@dataclass
class Quest:
    id: str
    project_path: str
    name: str
    direction: str
    status: str
    max_agent_runs: int
    agent_runs: int
    roles: list[str] = field(default_factory=lambda: list(_DEFAULT_ROLES))
    provider: Optional[str] = None
    mode: QuestMode = QuestMode.TEAM
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_path": self.project_path,
            "name": self.name,
            "direction": self.direction,
            "status": self.status,
            "max_agent_runs": self.max_agent_runs,
            "agent_runs": self.agent_runs,
            "roles": list(self.roles),
            "provider": self.provider,
            "mode": self.mode.value
            if isinstance(self.mode, QuestMode)
            else str(self.mode),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class QuestNode:
    id: str
    quest_id: str
    parent_id: Optional[str]
    role: str
    hypothesis: str
    status: str
    verdict: Optional[str] = None
    evidence: Optional[str] = None
    proposed_by: Optional[str] = None
    run_id: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "quest_id": self.quest_id,
            "parent_id": self.parent_id,
            "role": self.role,
            "hypothesis": self.hypothesis,
            "status": self.status,
            "verdict": self.verdict,
            "evidence": self.evidence,
            "proposed_by": self.proposed_by,
            "run_id": self.run_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class QuestEdge:
    id: str
    quest_id: str
    from_node: Optional[str]
    to_node: Optional[str]
    relation: str
    created_at: str = ""


def _now() -> str:
    return datetime.now().astimezone().isoformat()


def _connect() -> sqlite3.Connection:
    init_db()
    conn = sqlite3.connect(KAGE_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _row_to_quest(row: sqlite3.Row) -> Quest:
    roles: list[str] = _DEFAULT_ROLES
    raw_roles = row["roles_json"]
    if raw_roles:
        try:
            parsed = json.loads(raw_roles)
            if isinstance(parsed, list):
                roles = [str(r) for r in parsed] or list(_DEFAULT_ROLES)
        except json.JSONDecodeError:
            pass
    return Quest(
        id=row["id"],
        project_path=row["project_path"],
        name=row["name"],
        direction=row["direction"],
        status=row["status"],
        max_agent_runs=row["max_agent_runs"],
        agent_runs=row["agent_runs"],
        roles=roles,
        provider=row["provider"],
        mode=QuestMode(row["mode"])
        if "mode" in row.keys() and row["mode"]
        else QuestMode.TEAM,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_node(row: sqlite3.Row) -> QuestNode:
    return QuestNode(
        id=row["id"],
        quest_id=row["quest_id"],
        parent_id=row["parent_id"],
        role=row["role"],
        hypothesis=row["hypothesis"],
        status=row["status"],
        verdict=row["verdict"],
        evidence=row["evidence"],
        proposed_by=row["proposed_by"] if "proposed_by" in row.keys() else None,
        run_id=row["run_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_edge(row: sqlite3.Row) -> QuestEdge:
    return QuestEdge(
        id=row["id"],
        quest_id=row["quest_id"],
        from_node=row["from_node"],
        to_node=row["to_node"],
        relation=row["relation"],
        created_at=row["created_at"],
    )


def create_quest(
    project_path: str,
    name: str,
    direction: str,
    *,
    roles: Optional[list[str]] = None,
    max_agent_runs: int = _DEFAULT_MAX_AGENT_RUNS,
    provider: Optional[str] = None,
    initial_role: Optional[str] = None,
    mode: QuestMode = QuestMode.TEAM,
) -> Quest:
    """Create a new quest with a single root node ready to dispatch.

    In team mode (default) the initial role is ``owner``; the owner will decide
    the first scout/poc to actually run. In ``--solo`` mode the root node is a
    scout that dispatches immediately (legacy v1 behaviour).
    """
    if mode == QuestMode.TEAM:
        roles = list(roles or _DEFAULT_ROLES)
        if ROLE_OWNER not in roles:
            roles.append(ROLE_OWNER)
        if initial_role is None:
            initial_role = ROLE_OWNER
    else:
        roles = list(roles or _TEAM_ROLES)
        if initial_role is None:
            initial_role = ROLE_SCOUT
    quest_id = uuid.uuid4().hex[:12]
    now = _now()
    conn = _connect()
    try:
        conn.execute(
            """
            INSERT INTO quests
                (id, project_path, name, direction, status, max_agent_runs,
                 agent_runs, roles_json, provider, mode, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                quest_id,
                str(project_path),
                name,
                direction,
                QUEST_STATUS_ACTIVE,
                max_agent_runs,
                0,
                json.dumps(roles, ensure_ascii=False),
                provider,
                mode.value,
                now,
                now,
            ),
        )
        root = QuestNode(
            id=uuid.uuid4().hex[:12],
            quest_id=quest_id,
            parent_id=None,
            role=initial_role,
            hypothesis=direction,
            status=NODE_STATUS_PENDING,
            created_at=now,
            updated_at=now,
        )
        conn.execute(
            """
            INSERT INTO quest_nodes
                (id, quest_id, parent_id, role, hypothesis, status,
                 verdict, evidence, proposed_by, run_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, ?, ?)
            """,
            (
                root.id,
                root.quest_id,
                root.parent_id,
                root.role,
                root.hypothesis,
                root.status,
                root.created_at,
                root.updated_at,
            ),
        )
        conn.commit()
        quest = get_quest(quest_id)
        assert quest is not None
        return quest
    finally:
        conn.close()


def get_quest(quest_id: str) -> Optional[Quest]:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM quests WHERE id = ?",
            (quest_id,),
        ).fetchone()
        return _row_to_quest(row) if row else None
    finally:
        conn.close()


def list_quests(
    *,
    status_filter: Optional[str] = None,
    project_filter: Optional[str] = None,
) -> list[Quest]:
    conn = _connect()
    try:
        query = "SELECT * FROM quests"
        clauses: list[str] = []
        params: list[object] = []
        if status_filter:
            clauses.append("status = ?")
            params.append(status_filter)
        if project_filter:
            clauses.append("project_path LIKE ?")
            params.append(f"%{project_filter}%")
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at DESC"
        rows = conn.execute(query, params).fetchall()
        return [_row_to_quest(row) for row in rows]
    finally:
        conn.close()


def set_quest_status(quest_id: str, status: str) -> None:
    conn = _connect()
    try:
        conn.execute(
            "UPDATE quests SET status = ?, updated_at = ? WHERE id = ?",
            (status, _now(), quest_id),
        )
        conn.commit()
    finally:
        conn.close()


def list_nodes(quest_id: str) -> list[QuestNode]:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM quest_nodes WHERE quest_id = ? ORDER BY created_at ASC",
            (quest_id,),
        ).fetchall()
        return [_row_to_node(row) for row in rows]
    finally:
        conn.close()


def get_node(node_id: str) -> Optional[QuestNode]:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM quest_nodes WHERE id = ?",
            (node_id,),
        ).fetchone()
        return _row_to_node(row) if row else None
    finally:
        conn.close()


def list_edges(quest_id: str) -> list[QuestEdge]:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM quest_edges WHERE quest_id = ? ORDER BY created_at ASC",
            (quest_id,),
        ).fetchall()
        return [_row_to_edge(row) for row in rows]
    finally:
        conn.close()


def abort_node(node_id: str) -> Optional[QuestNode]:
    conn = _connect()
    try:
        now = _now()
        conn.execute(
            "UPDATE quest_nodes SET status = ?, updated_at = ? WHERE id = ?",
            (NODE_STATUS_ABORTED, now, node_id),
        )
        conn.commit()
    finally:
        conn.close()
    return get_node(node_id)


def node_counts(quest_id: str) -> dict[str, int]:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS c FROM quest_nodes WHERE quest_id = ? "
            "GROUP BY status",
            (quest_id,),
        ).fetchall()
        counts = {row["status"]: row["c"] for row in rows}
        counts["total"] = sum(counts.values())
        return counts
    finally:
        conn.close()


def _role_prompt(
    role: str,
    quest: Quest,
    node: QuestNode,
    ancestor_evidence: str,
    proposed_summary: str = "",
    completed_summary: str = "",
) -> str:
    direction = quest.direction
    hypothesis = node.hypothesis
    ancestry = ancestor_evidence or "(no prior evidence yet)"

    if role == ROLE_OWNER:
        proposed_text = proposed_summary or "(none)"
        completed_text = completed_summary or "(none)"
        body = (
            "# Role: Owner (Quest Director)\n"
            f"## Quest direction\n{direction}\n\n"
            "## Recent completed work\n"
            f"{completed_text}\n\n"
            "## Pending proposed nodes awaiting your decision\n"
            f"{proposed_text}\n\n"
            "You are the ONLY agent that may create, update, or abort task "
            "nodes. Do NOT run experiments yourself. Review the evidence from "
            "scout/poc/strategist and only then decide which proposals to "
            "promote into pending work, which to abort, which new roles to "
            "spawn, or whether to finish. Consensus matters: do not act on a "
            "single source — wait until at least two pieces of evidence "
            "corroborate before promoting."
        )
        owner_suffix = (
            "\n\n## Output contract\n"
            "End your response with a fenced JSON block of exactly this "
            "shape and nothing after it:\n"
            "```json\n"
            '{"evidence": "<short synthesis>", "finish": false, '
            '"actions": [\n'
            '  {"type": "promote", "node_id": "<id>"},\n'
            '  {"type": "abort",   "node_id": "<id>"},\n'
            '  {"type": "spawn",   "role": "scout|poc|strategist|owner", '
            '"direction": "<hypothesis>"},\n'
            '  {"type": "finish",  "reason": "..."}\n'
            "]}\n"
            "```\n"
            "`actions` may be empty. Set `finish: true` once the quest is "
            "closed. `spawn` with `role: owner` schedules another owner "
            "round later."
        )
        return body + owner_suffix

    common_suffix = (
        "\n\n## Output contract\n"
        "End your response with a fenced JSON block of exactly this shape and "
        "nothing after it:\n"
        "```json\n"
        '{"verdict": "promising" | "dead", "evidence": "<short summary>", '
        '"new_directions": ["<hypothesis>", ...]}\n'
        "```\n"
        "`verdict` must be one of the two literals. `new_directions` may be empty."
    )

    if role == ROLE_SCOUT:
        body = (
            "# Role: Scout\n"
            f"## Quest direction\n{direction}\n\n"
            f"## Hypothesis to investigate\n{hypothesis}\n\n"
            f"## Prior evidence\n{ancestry}\n\n"
            "Investigate the current state of the repository / environment. "
            "Look for what already exists, what is missing, and what is worth "
            "trying. Propose concrete, falsifiable candidate hypotheses to test "
            "next as PoCs."
        )
    elif role == ROLE_POC:
        body = (
            "# Role: PoC\n"
            f"## Quest direction\n{direction}\n\n"
            f"## Hypothesis to test\n{hypothesis}\n\n"
            f"## Prior evidence\n{ancestry}\n\n"
            "Run the smallest possible proof of concept for this hypothesis "
            "inside the working directory. Prefer throwaway scripts and quick "
            "measurements over polish. If it works, say what to grow next; if "
            "it fails, say exactly why and whether anything salvageable remains."
        )
    else:  # strategist
        body = (
            "# Role: Strategist\n"
            f"## Quest direction\n{direction}\n\n"
            f"## Prior evidence\n{ancestry}\n\n"
            "Evaluate the accumulated evidence like a ROI assessment. Decide "
            "whether the quest should keep going, which direction to double down "
            "on, and whether to close the quest. If the direction is exhausted, "
            "set verdict to 'dead' and leave new_directions empty."
        )
    return body + common_suffix


def _ancestor_evidence(quest_id: str, node: QuestNode) -> str:
    """Collect evidence walking up the parent chain of a node."""
    conn = _connect()
    try:
        parts: list[str] = []
        current_id = node.parent_id
        seen: set[str] = set()
        while current_id and current_id not in seen:
            seen.add(current_id)
            row = conn.execute(
                "SELECT role, hypothesis, verdict, evidence, parent_id "
                "FROM quest_nodes WHERE id = ?",
                (current_id,),
            ).fetchone()
            if not row:
                break
            verdict = row["verdict"] or "-"
            evidence = row["evidence"] or "-"
            parts.append(
                f"- [{row['role']}] {row['hypothesis']} (verdict={verdict}): {evidence}"
            )
            current_id = row["parent_id"]
        return "\n".join(parts) if parts else ""
    finally:
        conn.close()


def _proposed_summary(quest_id: str) -> str:
    """List current proposed nodes for the owner's triage queue."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT id, role, hypothesis, proposed_by "
            "FROM quest_nodes WHERE quest_id = ? AND status = ? "
            "ORDER BY created_at ASC",
            (quest_id, NODE_STATUS_PROPOSED),
        ).fetchall()
        if not rows:
            return "(no pending proposed nodes)"
        lines = [
            f"- [{r['role']}] {r['id']} (by {r['proposed_by'] or '-'}) "
            f"{r['hypothesis']}"
            for r in rows
        ]
        return "\n".join(lines)
    finally:
        conn.close()


def _completed_summary(quest_id: str, limit: int = 10) -> str:
    """Latest completed (explored/growing/aborted) nodes for the owner."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT id, role, hypothesis, verdict, evidence "
            "FROM quest_nodes WHERE quest_id = ? "
            "AND status IN (?, ?, ?) "
            "ORDER BY updated_at DESC LIMIT ?",
            (
                quest_id,
                NODE_STATUS_EXPLORED,
                NODE_STATUS_GROWING,
                NODE_STATUS_ABORTED,
                limit,
            ),
        ).fetchall()
        if not rows:
            return "(no completed work yet)"
        lines = [
            f"- [{r['role']}] {r['id']} verdict={r['verdict'] or '-'} · "
            f"{r['hypothesis']} :: {r['evidence'] or '-'}"
            for r in rows
        ]
        return "\n".join(lines)
    finally:
        conn.close()


def _synthesize_task(quest: Quest, node: QuestNode, prompt: str) -> TaskDef:
    return TaskDef(
        name=f"quest:{quest.id}:{node.id}",
        cron="* * * * *",
        active=True,
        mode=ExecutionMode.CONTINUOUS,
        prompt=prompt,
        provider=quest.provider,
        working_dir=str(quest.project_path),
    )


_VERDICT_BLOCK_RE = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)


def _parse_verdict(stdout: str) -> Optional[dict]:
    if not stdout:
        return None
    matches = list(_VERDICT_BLOCK_RE.finditer(stdout))
    for match in reversed(matches):
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and "verdict" in payload:
            return payload
    return None


def _record_node_outcome(
    conn: sqlite3.Connection,
    node: QuestNode,
    *,
    status: str,
    verdict: Optional[str],
    evidence: Optional[str],
    run_id: Optional[str],
) -> None:
    now = _now()
    conn.execute(
        """
        UPDATE quest_nodes
        SET status = ?, verdict = ?, evidence = ?, run_id = ?, updated_at = ?
        WHERE id = ?
        """,
        (status, verdict, evidence, run_id, now, node.id),
    )


def _spawn_children(
    conn: sqlite3.Connection,
    quest: Quest,
    parent_node: QuestNode,
    new_directions: list[str],
    *,
    role: str,
    relation: str,
    as_proposed: bool = False,
) -> list[QuestNode]:
    """Create child nodes (or proposed candidates in team mode) of ``parent_node``.

    ``as_proposed=True`` inserts the rows in :data:`NODE_STATUS_PROPOSED` with a
    ``proposed_from`` edge so the owner can later promote/abort them. In team
    mode non-owner roles must always pass ``as_proposed=True``.
    """
    now = _now()
    created: list[QuestNode] = []
    initial_status = NODE_STATUS_PROPOSED if as_proposed else NODE_STATUS_PENDING
    for direction in new_directions:
        direction = (direction or "").strip()
        if not direction:
            continue
        child = QuestNode(
            id=uuid.uuid4().hex[:12],
            quest_id=quest.id,
            parent_id=parent_node.id,
            role=role,
            hypothesis=direction,
            status=initial_status,
            proposed_by=parent_node.role if as_proposed else None,
            created_at=now,
            updated_at=now,
        )
        conn.execute(
            """
            INSERT INTO quest_nodes
                (id, quest_id, parent_id, role, hypothesis, status,
                 verdict, evidence, proposed_by, run_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, ?, NULL, ?, ?)
            """,
            (
                child.id,
                child.quest_id,
                child.parent_id,
                child.role,
                child.hypothesis,
                child.status,
                child.proposed_by,
                child.created_at,
                child.updated_at,
            ),
        )
        edge = QuestEdge(
            id=uuid.uuid4().hex[:12],
            quest_id=quest.id,
            from_node=parent_node.id,
            to_node=child.id,
            relation=relation,
            created_at=now,
        )
        conn.execute(
            """
            INSERT INTO quest_edges
                (id, quest_id, from_node, to_node, relation, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                edge.id,
                edge.quest_id,
                edge.from_node,
                edge.to_node,
                edge.relation,
                edge.created_at,
            ),
        )
        created.append(child)
    return created


def _has_pending_strategist(conn: sqlite3.Connection, quest_id: str) -> bool:
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM quest_nodes WHERE quest_id = ? "
        "AND role = ? AND status = ?",
        (quest_id, ROLE_STRATEGIST, NODE_STATUS_PENDING),
    ).fetchone()
    return bool(row and row["c"] > 0)


def _select_pending_node(
    conn: sqlite3.Connection, quest_id: str, quest: Quest
) -> Optional[QuestNode]:
    """Pick the next dispatchable node.

    In team mode the only ``pending`` node we *should* see is the owner when
    enough evidence has accumulated; non-owner runs go via proposed nodes that
    require owner ``promote`` action first. ``_should_dispatch_owner`` is the
    gate. In solo mode every pending node is fair game.
    """
    row = conn.execute(
        "SELECT * FROM quest_nodes WHERE quest_id = ? AND status = ? "
        "ORDER BY created_at ASC LIMIT 1",
        (quest_id, NODE_STATUS_PENDING),
    ).fetchone()
    if row is None:
        return None
    node = _row_to_node(row)
    if quest.mode == QuestMode.TEAM and node.role == ROLE_OWNER:
        if not _should_dispatch_owner(conn, quest_id):
            return None
    return node


def _should_dispatch_owner(conn: sqlite3.Connection, quest_id: str) -> bool:
    """Gate the owner's evaluation until enough evidence has accumulated."""
    proposed = conn.execute(
        "SELECT COUNT(*) AS c FROM quest_nodes WHERE quest_id = ? AND status = ?",
        (quest_id, NODE_STATUS_PROPOSED),
    ).fetchone()
    completed = conn.execute(
        "SELECT COUNT(*) AS c FROM quest_nodes WHERE quest_id = ? "
        "AND status IN (?, ?, ?)",
        (
            quest_id,
            NODE_STATUS_EXPLORED,
            NODE_STATUS_GROWING,
            NODE_STATUS_ABORTED,
        ),
    ).fetchone()
    pending = conn.execute(
        "SELECT COUNT(*) AS c FROM quest_nodes WHERE quest_id = ? AND status = ?",
        (quest_id, NODE_STATUS_PENDING),
    ).fetchone()
    proposed_n = proposed["c"] if proposed else 0
    completed_n = completed["c"] if completed else 0
    pending_n = pending["c"] if pending else 0
    if proposed_n >= _OWNER_MIN_PROPOSED:
        return True
    if completed_n >= _OWNER_MIN_CHILDREN_COMPLETED:
        return True
    if proposed_n == 0 and completed_n == 0 and pending_n <= 1:
        return True
    return False


def _mark_running(conn: sqlite3.Connection, node: QuestNode) -> None:
    now = _now()
    conn.execute(
        "UPDATE quest_nodes SET status = ?, updated_at = ? WHERE id = ?",
        (NODE_STATUS_RUNNING, now, node.id),
    )


def _increment_agent_runs(
    conn: sqlite3.Connection, quest_id: str, quest: Quest
) -> None:
    now = _now()
    new_count = quest.agent_runs + 1
    conn.execute(
        "UPDATE quests SET agent_runs = ?, updated_at = ? WHERE id = ?",
        (new_count, now, quest_id),
    )


def _apply_outcome(
    conn: sqlite3.Connection,
    quest: Quest,
    node: QuestNode,
    stdout: str,
    run_id: Optional[str],
) -> None:
    if quest.mode == QuestMode.TEAM and node.role == ROLE_OWNER:
        _apply_owner_outcome(conn, quest, node, stdout, run_id)
        return

    verdict_payload = _parse_verdict(stdout)
    verdict_str: Optional[str] = None
    evidence: Optional[str] = None
    new_directions: list[str] = []

    if verdict_payload:
        verdict_str = str(verdict_payload.get("verdict", "")).strip().lower()
        evidence = str(verdict_payload.get("evidence", "")).strip() or None
        raw_dirs = verdict_payload.get("new_directions")
        if isinstance(raw_dirs, list):
            new_directions = [str(d).strip() for d in raw_dirs if str(d).strip()]

    team_mode = quest.mode == QuestMode.TEAM

    if node.role == ROLE_STRATEGIST:
        status = NODE_STATUS_EXPLORED
        _record_node_outcome(
            conn,
            node,
            status=status,
            verdict=verdict_str,
            evidence=evidence,
            run_id=run_id,
        )
        if verdict_str == _VERDICT_DEAD:
            conn.execute(
                "UPDATE quests SET status = ?, updated_at = ? WHERE id = ?",
                (QUEST_STATUS_DONE, _now(), quest.id),
            )
        return

    if verdict_str == _VERDICT_PROMISING:
        _record_node_outcome(
            conn,
            node,
            status=NODE_STATUS_GROWING,
            verdict=_VERDICT_PROMISING,
            evidence=evidence,
            run_id=run_id,
        )
        if new_directions:
            _spawn_children(
                conn,
                quest,
                node,
                new_directions,
                role=ROLE_POC,
                relation="grew_to",
                as_proposed=team_mode,
            )
    elif verdict_str == _VERDICT_DEAD:
        _record_node_outcome(
            conn,
            node,
            status=NODE_STATUS_ABORTED,
            verdict=_VERDICT_DEAD,
            evidence=evidence,
            run_id=run_id,
        )
        if team_mode:
            # Adding a strategy proposal for the owner to triage rather than
            # dispatching autonomously in team mode; scout still spawns an
            # immediate strategist in solo mode.
            _spawn_children(
                conn,
                quest,
                node,
                [f"Assess progress on quest: {quest.direction}"],
                role=ROLE_STRATEGIST,
                relation="aborted_to",
                as_proposed=True,
            )
        elif not _has_pending_strategist(conn, quest.id):
            _spawn_children(
                conn,
                quest,
                node,
                [f"Assess progress on quest: {quest.direction}"],
                role=ROLE_STRATEGIST,
                relation="aborted_to",
            )
    else:
        # No parseable verdict: keep node explored but do not branch.
        _record_node_outcome(
            conn,
            node,
            status=NODE_STATUS_EXPLORED,
            verdict=verdict_str,
            evidence=evidence or stdout.strip()[:500] or None,
            run_id=run_id,
        )


# --------------------------------------------------------------------------- #
# Owner outcome handling (team mode only)
# --------------------------------------------------------------------------- #
_ACTION_BLOCK_RE = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)


def _parse_owner_actions(stdout: str) -> Optional[dict]:
    if not stdout:
        return None
    matches = list(_ACTION_BLOCK_RE.finditer(stdout))
    for match in reversed(matches):
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and "actions" in payload:
            return payload
    return None


def _apply_owner_outcome(
    conn: sqlite3.Connection,
    quest: Quest,
    node: QuestNode,
    stdout: str,
    run_id: Optional[str],
) -> None:
    payload = _parse_owner_actions(stdout)
    evidence = None
    actions: list[dict] = []
    finish = False
    if payload:
        evidence = str(payload.get("evidence", "")).strip() or None
        raw_actions = payload.get("actions")
        if isinstance(raw_actions, list):
            actions = [a for a in raw_actions if isinstance(a, dict)]
        finish = bool(payload.get("finish", False))

    _record_node_outcome(
        conn,
        node,
        status=NODE_STATUS_EXPLORED,
        verdict="owned",
        evidence=evidence or stdout.strip()[:500] or None,
        run_id=run_id,
    )

    if finish:
        conn.execute(
            "UPDATE quests SET status = ?, updated_at = ? WHERE id = ?",
            (QUEST_STATUS_DONE, _now(), quest.id),
        )
        return

    for action in actions:
        _apply_owner_action(conn, quest, node, action)

    # Schedule the next owner round so the quest keeps progressing until
    # the owner eventually returns ``finish: true``.
    _spawn_children(
        conn,
        quest,
        node,
        [f"Continue triage on quest: {quest.direction}"],
        role=ROLE_OWNER,
        relation="spawned",
    )


def _apply_owner_action(
    conn: sqlite3.Connection, quest: Quest, owner_node: QuestNode, action: dict
) -> None:
    action_type = str(action.get("type", "")).strip().lower()
    target_id = str(action.get("node_id", "") or "").strip()
    now = _now()

    if action_type == "promote":
        if not target_id:
            return
        row = conn.execute(
            "SELECT * FROM quest_nodes WHERE id = ? AND quest_id = ?",
            (target_id, quest.id),
        ).fetchone()
        if not row:
            return
        if row["status"] != NODE_STATUS_PROPOSED:
            # Owner can only promote proposals — silently ignore others.
            return
        conn.execute(
            "UPDATE quest_nodes SET status = ?, updated_at = ? WHERE id = ?",
            (NODE_STATUS_PENDING, now, target_id),
        )
        edge = QuestEdge(
            id=uuid.uuid4().hex[:12],
            quest_id=quest.id,
            from_node=owner_node.id,
            to_node=target_id,
            relation="promoted",
            created_at=now,
        )
        conn.execute(
            """
            INSERT INTO quest_edges
                (id, quest_id, from_node, to_node, relation, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                edge.id,
                edge.quest_id,
                edge.from_node,
                edge.to_node,
                edge.relation,
                edge.created_at,
            ),
        )
    elif action_type == "abort":
        if not target_id:
            return
        row = conn.execute(
            "SELECT id, status FROM quest_nodes WHERE id = ? AND quest_id = ?",
            (target_id, quest.id),
        ).fetchone()
        if not row:
            return
        conn.execute(
            "UPDATE quest_nodes SET status = ?, updated_at = ? WHERE id = ?",
            (NODE_STATUS_ABORTED, now, target_id),
        )
        edge = QuestEdge(
            id=uuid.uuid4().hex[:12],
            quest_id=quest.id,
            from_node=owner_node.id,
            to_node=target_id,
            relation="aborted_to",
            created_at=now,
        )
        conn.execute(
            """
            INSERT INTO quest_edges
                (id, quest_id, from_node, to_node, relation, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                edge.id,
                edge.quest_id,
                edge.from_node,
                edge.to_node,
                edge.relation,
                edge.created_at,
            ),
        )
    elif action_type == "spawn":
        role = str(action.get("role", "") or "").strip()
        if role not in _DEFAULT_ROLES:
            return
        direction = str(action.get("direction", "") or "").strip()
        if not direction:
            return
        initial_status = (
            NODE_STATUS_PROPOSED if role != ROLE_OWNER else NODE_STATUS_PENDING
        )
        child = QuestNode(
            id=uuid.uuid4().hex[:12],
            quest_id=quest.id,
            parent_id=owner_node.id,
            role=role,
            hypothesis=direction,
            status=initial_status,
            proposed_by=owner_node.role if role != ROLE_OWNER else None,
            created_at=now,
            updated_at=now,
        )
        conn.execute(
            """
            INSERT INTO quest_nodes
                (id, quest_id, parent_id, role, hypothesis, status,
                 verdict, evidence, proposed_by, run_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, ?, NULL, ?, ?)
            """,
            (
                child.id,
                child.quest_id,
                child.parent_id,
                child.role,
                child.hypothesis,
                child.status,
                child.proposed_by,
                child.created_at,
                child.updated_at,
            ),
        )
        edge = QuestEdge(
            id=uuid.uuid4().hex[:12],
            quest_id=quest.id,
            from_node=owner_node.id,
            to_node=child.id,
            relation="spawned",
            created_at=now,
        )
        conn.execute(
            """
            INSERT INTO quest_edges
                (id, quest_id, from_node, to_node, relation, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                edge.id,
                edge.quest_id,
                edge.from_node,
                edge.to_node,
                edge.relation,
                edge.created_at,
            ),
        )
    elif action_type == "finish":
        conn.execute(
            "UPDATE quests SET status = ?, updated_at = ? WHERE id = ?",
            (QUEST_STATUS_DONE, now, quest.id),
        )


def tick(dry_run: bool = False) -> list[dict]:
    """Advance every active quest by at most one node each.

    Called once per ``kage cron run`` tick. Returns a list of dispatch summaries.
    """
    summaries: list[dict] = []
    quests = list_quests(status_filter=QUEST_STATUS_ACTIVE)
    for quest in quests:
        if quest.agent_runs >= quest.max_agent_runs:
            set_quest_status(quest.id, QUEST_STATUS_TERMINATED)
            summaries.append(
                {"quest_id": quest.id, "action": "terminated", "reason": "budget"}
            )
            continue

        conn = _connect()
        try:
            node = _select_pending_node(conn, quest.id, quest)
            if node is None:
                summaries.append({"quest_id": quest.id, "action": "idle"})
                continue

            if dry_run:
                summaries.append(
                    {
                        "quest_id": quest.id,
                        "action": "would_dispatch",
                        "node_id": node.id,
                        "role": node.role,
                    }
                )
                continue

            _mark_running(conn, node)
            conn.commit()
        finally:
            conn.close()

        run_id: Optional[str] = None
        stdout = ""
        try:
            from .executor import execute_task

            ancestor = _ancestor_evidence(quest.id, node)
            proposed = _proposed_summary(quest.id)
            completed = _completed_summary(quest.id)
            prompt = _role_prompt(
                node.role,
                quest,
                node,
                ancestor,
                proposed_summary=proposed,
                completed_summary=completed,
            )
            task = _synthesize_task(quest, node, prompt)
            result = execute_task(Path(quest.project_path), task)

            if result and result.value == "started":
                # Execute_task ran synchronously and finished; capture latest run.
                from .runs import list_runs

                recent = list_runs(limit=1, task_name=task.name)
                if recent:
                    run_id = recent[0].id
                    stdout = recent[0].stdout or ""
        except Exception as exc:  # pragma: no cover - defensive
            stdout = f"[quest dispatch error] {exc}"

        conn = _connect()
        try:
            # Re-load quest to refresh agent_runs.
            refreshed = get_quest(quest.id)
            if refreshed is None:
                continue
            _increment_agent_runs(conn, quest.id, refreshed)
            fresh_node = get_node(node.id) or node
            _apply_outcome(conn, refreshed, fresh_node, stdout, run_id)
            conn.commit()
            summaries.append(
                {
                    "quest_id": quest.id,
                    "action": "dispatched",
                    "node_id": node.id,
                    "role": node.role,
                    "run_id": run_id,
                }
            )
        finally:
            conn.close()
    return summaries
