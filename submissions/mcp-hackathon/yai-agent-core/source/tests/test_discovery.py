from yai_core import build_spec


def search_notes(keyword: str, limit: int = 5) -> list:
    """按关键词搜索笔记。"""
    return []


def test_build_spec_basic_types_and_required() -> None:
    spec = build_spec(search_notes)
    assert spec.name == "search_notes"
    assert spec.description == "按关键词搜索笔记。"
    props = spec.input_schema["properties"]
    assert props["keyword"]["type"] == "string"
    assert props["limit"]["type"] == "integer"
    assert props["limit"]["default"] == 5
    assert spec.input_schema["required"] == ["keyword"]


def test_llm_schema_shape() -> None:
    spec = build_spec(search_notes)
    llm = spec.llm_schema()
    assert llm["type"] == "function"
    assert llm["function"]["name"] == "search_notes"
    assert "parameters" in llm["function"]
