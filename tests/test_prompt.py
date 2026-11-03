from app.generate import REFUSAL, build_messages, generate


def sample_chunks():
    return [
        {"source": "a.md", "text": "Alpha text."},
        {"source": "b.md", "text": "Beta text."},
    ]


def test_context_is_numbered_and_has_sources():
    msgs = build_messages("What is alpha?", sample_chunks())
    user = msgs[1]["content"]
    assert "[1] (source: a.md)\nAlpha text." in user
    assert "[2] (source: b.md)\nBeta text." in user
    assert user.endswith("Question: What is alpha?")


def test_system_prompt_forbids_outside_knowledge():
    assert "ONLY" in build_messages("q", sample_chunks())[0]["content"]


def test_no_chunks_means_refusal_without_calling_llm():
    # would raise (no API key) if it tried to call the LLM
    assert generate("anything", []) == REFUSAL