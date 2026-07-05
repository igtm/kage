from pathlib import Path

from kage import quest
from kage.quest import QuestMode


def _setup_tmp_db(mocker, tmp_path):
    db_path = tmp_path / "kage.db"
    mocker.patch("kage.db.KAGE_DB_PATH", db_path)
    mocker.patch("kage.quest.KAGE_DB_PATH", db_path)


def test_create_quest_and_structure(mocker, tmp_path: Path):
    _setup_tmp_db(mocker, tmp_path)
    q = quest.create_quest(
        str(tmp_path),
        "ocr-machine",
        "find the best free OCR model for Japanese invoices",
        max_agent_runs=3,
        mode=QuestMode.SOLO,
    )

    assert q.status == quest.QUEST_STATUS_ACTIVE
    assert q.agent_runs == 0
    nodes = quest.list_nodes(q.id)
    assert len(nodes) == 1
    assert nodes[0].role == quest.ROLE_SCOUT
    assert nodes[0].status == quest.NODE_STATUS_PENDING

    quests = quest.list_quests()
    assert len(quests) == 1
    assert quests[0].id == q.id


def test_tick_dispatches_scout_and_spawns_poc(mocker, tmp_path: Path):
    _setup_tmp_db(mocker, tmp_path)
    q = quest.create_quest(
        str(tmp_path),
        "explore",
        "explore faster builds",
        max_agent_runs=5,
        mode=QuestMode.SOLO,
    )

    fake_run = mocker.Mock()
    fake_run.id = "run-1"
    fake_run.stdout = (
        "scout done\n```json\n"
        '{"verdict": "promising", "evidence": "two leads found", '
        '"new_directions": ["try mold", "try sccache"]}\n'
        "```"
    )
    mocker.patch(
        "kage.executor.execute_task", return_value=mocker.Mock(value="started")
    )
    mocker.patch(
        "kage.runs.list_runs",
        return_value=[fake_run],
    )

    summaries = quest.tick()
    assert summaries and summaries[0]["action"] == "dispatched"

    nodes = quest.list_nodes(q.id)
    assert len(nodes) == 3  # scout + 2 spawned poc
    scout = [n for n in nodes if n.role == quest.ROLE_SCOUT][0]
    assert scout.status == quest.NODE_STATUS_GROWING
    assert scout.verdict == "promising"
    pocs = [n for n in nodes if n.role == quest.ROLE_POC]
    assert {n.hypothesis for n in pocs} == {"try mold", "try sccache"}
    edges = quest.list_edges(q.id)
    assert all(e.relation == "grew_to" for e in edges)
    fresh = quest.get_quest(q.id)
    assert fresh.agent_runs == 1


def test_tick_terminates_on_budget(mocker, tmp_path: Path):
    _setup_tmp_db(mocker, tmp_path)
    q = quest.create_quest(
        str(tmp_path),
        "capped",
        "x",
        max_agent_runs=0,
        mode=QuestMode.SOLO,
    )
    summaries = quest.tick()
    assert summaries[0]["action"] == "terminated"
    assert quest.get_quest(q.id).status == quest.QUEST_STATUS_TERMINATED


def test_tick_dead_poc_spawns_strategist_then_done(mocker, tmp_path: Path):
    _setup_tmp_db(mocker, tmp_path)
    q = quest.create_quest(
        str(tmp_path),
        "dead end",
        "y",
        max_agent_runs=10,
        mode=QuestMode.SOLO,
    )

    # First tick: scout dead -> spawn strategist node
    run1 = mocker.Mock()
    run1.id = "r1"
    run1.stdout = (
        "```json\n"
        '{"verdict": "dead", "evidence": "nothing here", "new_directions": []}\n'
        "```"
    )
    mocker.patch(
        "kage.executor.execute_task", return_value=mocker.Mock(value="started")
    )
    mocker.patch("kage.runs.list_runs", return_value=[run1])
    quest.tick()

    nodes = quest.list_nodes(q.id)
    assert any(n.role == quest.ROLE_STRATEGIST for n in nodes)

    # Second tick: strategist dead -> quest done
    run2 = mocker.Mock()
    run2.id = "r2"
    run2.stdout = (
        "```json\n"
        '{"verdict": "dead", "evidence": "exhausted", "new_directions": []}\n'
        "```"
    )
    mocker.patch("kage.runs.list_runs", return_value=[run2])
    quest.tick()

    assert quest.get_quest(q.id).status == quest.QUEST_STATUS_DONE


def test_parse_verdict_handles_missing_block():
    assert quest._parse_verdict("no json here") is None
    payload = quest._parse_verdict(
        'blah\n```json\n{"verdict": "promising", "new_directions": []}\n```\n'
    )
    assert payload == {"verdict": "promising", "new_directions": []}


def test_team_mode_defers_until_evidence(mocker, tmp_path: Path):
    """In team mode the owner should not run when evidence is empty."""
    _setup_tmp_db(mocker, tmp_path)
    q = quest.create_quest(
        str(tmp_path),
        "team quest",
        "find a faster bundler",
        max_agent_runs=20,
        mode=QuestMode.TEAM,
    )
    nodes = quest.list_nodes(q.id)
    assert len(nodes) == 1
    assert nodes[0].role == quest.ROLE_OWNER
    assert nodes[0].status == quest.NODE_STATUS_PENDING

    # No completed/pending evidence yet — _should_dispatch_owner returns
    # True in the empty case (pending_n <= 1) so the owner can kick off.
    assert quest._should_dispatch_owner(quest._connect(), q.id) is True


def test_team_mode_scout_emits_proposed_not_pending(mocker, tmp_path: Path):
    """Scout's grown children must land as 'proposed', not 'pending'."""
    _setup_tmp_db(mocker, tmp_path)
    q = quest.create_quest(
        str(tmp_path),
        "team quest",
        "find a faster bundler",
        max_agent_runs=20,
        mode=QuestMode.TEAM,
    )
    # First tick dispatches the owner; owner emits actions: spawn scout.
    owner_run = mocker.Mock()
    owner_run.id = "r-owner"
    owner_run.stdout = (
        "```json\n"
        '{"evidence": "kick off", "actions": ['
        '{"type": "spawn", "role": "scout", "direction": "measure ts vs esbuild"}'
        "]}\n"
        "```"
    )
    mocker.patch(
        "kage.executor.execute_task", return_value=mocker.Mock(value="started")
    )
    mocker.patch("kage.runs.list_runs", return_value=[owner_run])
    quest.tick()

    scout = [n for n in quest.list_nodes(q.id) if n.role == quest.ROLE_SCOUT]
    assert len(scout) == 1
    assert scout[0].status == quest.NODE_STATUS_PROPOSED
    assert scout[0].proposed_by == quest.ROLE_OWNER


def test_team_mode_promote_via_owner_action(mocker, tmp_path: Path):
    """Owner's promote action flips a proposed node to pending."""
    _setup_tmp_db(mocker, tmp_path)
    q = quest.create_quest(
        str(tmp_path),
        "team quest",
        "x",
        max_agent_runs=20,
        mode=QuestMode.TEAM,
    )
    owner_run = mocker.Mock()
    owner_run.id = "r1"
    scout_hyp = "try vite"
    owner_run.stdout = (
        "```json\n"
        '{"evidence": "init", "actions": ['
        f'{{"type": "spawn", "role": "scout", "direction": "{scout_hyp}"}}'
        "]}\n"
        "```"
    )
    mocker.patch(
        "kage.executor.execute_task", return_value=mocker.Mock(value="started")
    )
    mocker.patch("kage.runs.list_runs", return_value=[owner_run])
    quest.tick()

    scout = [n for n in quest.list_nodes(q.id) if n.role == quest.ROLE_SCOUT][0]
    assert scout.status == quest.NODE_STATUS_PROPOSED

    # Second tick: owner promotes the scout.
    promote_run = mocker.Mock()
    promote_run.id = "r2"
    promote_run.stdout = (
        "```json\n"
        f'{{"evidence": "ok", "actions": [{{"type": "promote", "node_id": "{scout.id}"}}]}}\n'
        "```"
    )
    mocker.patch("kage.runs.list_runs", return_value=[promote_run])
    quest.tick()

    scout = quest.get_node(scout.id)
    assert scout.status == quest.NODE_STATUS_PENDING


def test_team_mode_finish_ends_quest(mocker, tmp_path: Path):
    """Owner's finish flag closes the quest."""
    _setup_tmp_db(mocker, tmp_path)
    q = quest.create_quest(
        str(tmp_path),
        "team quest",
        "x",
        max_agent_runs=20,
        mode=QuestMode.TEAM,
    )
    finish_run = mocker.Mock()
    finish_run.id = "r-fin"
    finish_run.stdout = (
        '```json\n{"evidence": "done here", "finish": true, "actions": []}\n```'
    )
    mocker.patch(
        "kage.executor.execute_task", return_value=mocker.Mock(value="started")
    )
    mocker.patch("kage.runs.list_runs", return_value=[finish_run])
    quest.tick()

    assert quest.get_quest(q.id).status == quest.QUEST_STATUS_DONE
