from eval.run_eval import hit_rank, is_refusal, normalize


def chunks(*texts):
    return [{"text": t} for t in texts]


def test_normalize_collapses_whitespace_and_case():
    assert normalize("  Hello\n  WORLD ") == "hello world"


def test_hit_rank_finds_first_matching_chunk():
    cs = chunks("nothing here", "the answer is forty two", "forty two again")
    assert hit_rank("forty two", cs) == 2


def test_hit_rank_ignores_case_and_line_breaks():
    assert hit_rank("Forty\nTwo", chunks("so FORTY   two it is")) == 1


def test_hit_rank_miss_returns_none():
    assert hit_rank("absent phrase", chunks("a", "b")) is None


def test_empty_evidence_never_matches():
    assert hit_rank("", chunks("anything")) is None


def test_refusal_detection():
    assert is_refusal("I don't know based on the provided documents.")
    assert not is_refusal("The default is 300 words [1].")