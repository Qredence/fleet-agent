from app.agent.tools import CORPUS, get_current_time, search_docs


def test_search_docs_ranks_relevant_chunks():
    result = search_docs("state snapshot delta")
    assert "AG-UI" in result or "state" in result.lower()
    assert result.startswith("* ")


def test_search_docs_no_match_returns_safe_message():
    assert search_docs("zzzqqxyw") == "No documentation matched the query."


def test_search_docs_result_is_bounded():
    result = search_docs("agent ui state delta snapshot process panel dspy")
    assert len(result) <= 1200
    assert result.startswith("* ")
    assert result.count("\n* ") <= 2  # at most 3 bullets total


def test_search_docs_uses_corpus_titles():
    for chunk in CORPUS:
        assert chunk["title"] and chunk["text"]


def test_get_current_time_is_utc_iso():
    value = get_current_time()
    assert value.endswith("+00:00")
    assert "T" in value
