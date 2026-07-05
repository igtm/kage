import pytest

from kage import memory as mem_mod
from kage import agent as agent_mod


@pytest.fixture
def isolated_memory(tmp_path, monkeypatch):
    fake_dir = tmp_path / ".kage" / "agents"
    monkeypatch.setattr(agent_mod, "KAGE_AGENTS_DIR", fake_dir)
    monkeypatch.setattr(
        mem_mod,
        "agent_memory_dir",
        lambda n: fake_dir / n / "memory",
    )
    return fake_dir


def test_write_and_read_memory(isolated_memory):
    mem_mod.write_memory("public", "prefs", "user prefs", "日本語で返答")
    body = mem_mod.read_memory("public", "prefs")
    assert body == "日本語で返答\n"


def test_write_overwrites_and_updates_description(isolated_memory):
    mem_mod.write_memory("public", "prefs", "old desc", "old content")
    mem_mod.write_memory("public", "prefs", "new desc", "new content")
    body = mem_mod.read_memory("public", "prefs")
    assert body == "new content\n"
    metas = mem_mod.list_memories("public")
    assert len(metas) == 1
    assert metas[0].description == "new desc"


def test_list_memories(isolated_memory):
    mem_mod.write_memory("public", "a", "alpha", "alpha body")
    mem_mod.write_memory("public", "b", "beta", "beta body")
    metas = mem_mod.list_memories("public")
    slugs = {m.slug for m in metas}
    assert slugs == {"a", "b"}


def test_delete_memory(isolated_memory):
    mem_mod.write_memory("public", "x", "x desc", "y")
    assert mem_mod.delete_memory("public", "x") is True
    assert mem_mod.read_memory("public", "x") is None
    assert mem_mod.delete_memory("public", "x") is False


def test_search_memories(isolated_memory):
    mem_mod.write_memory("public", "p", "desc", "line A\nimportant line\nline C")
    hits = mem_mod.search_memories("public", "important")
    assert hits
    slug, lineno, line = hits[0]
    assert slug == "p"
    assert "important line" in line


def test_build_memory_headings_xml_format(isolated_memory):
    mem_mod.write_memory("public", "prefs", "language and timezone", "ja")
    xml = mem_mod.build_memory_headings_xml("public")
    assert "<available_memories>" in xml
    assert "<name>prefs</name>" in xml
    assert "<description>language and timezone</description>" in xml
    assert "<updated_at>" in xml
    assert "<location>" not in xml  # 隠蔽


def test_build_memory_headings_xml_empty_when_no_memory(isolated_memory):
    assert mem_mod.build_memory_headings_xml("public") == ""


def test_normalize_slug():
    from kage.memory import normalize_slug

    assert normalize_slug("User Preferences") == "user-preferences"
    assert normalize_slug("foo_bar") == "foo-bar"  # _ は invalid slug char
    with pytest.raises(ValueError):
        normalize_slug("")
