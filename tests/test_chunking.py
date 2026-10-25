import pytest

from app.chunking import chunk_text


def words(n):
    return " ".join(f"w{i}" for i in range(n))


def test_empty_text_gives_no_chunks():
    assert chunk_text("   ", 10, 2) == []


def test_short_text_is_one_chunk():
    assert chunk_text(words(5), 10, 2) == [words(5)]


def test_chunks_overlap_by_exact_amount():
    chunks = chunk_text(words(25), 10, 3)
    a, b = chunks[0].split(), chunks[1].split()
    assert a[-3:] == b[:3]


def test_every_word_is_covered_and_nothing_exceeds_size():
    text = words(103)
    chunks = chunk_text(text, 10, 3)
    assert all(len(c.split()) <= 10 for c in chunks)
    assert chunks[-1].split()[-1] == "w102"
    covered = {w for c in chunks for w in c.split()}
    assert covered == set(text.split())


def test_exact_fit_has_no_trailing_duplicate_chunk():
    assert len(chunk_text(words(10), 10, 3)) == 1


def test_invalid_params():
    with pytest.raises(ValueError):
        chunk_text("a b", 5, 5)
    with pytest.raises(ValueError):
        chunk_text("a b", 0, 0)