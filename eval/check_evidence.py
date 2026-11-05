"""Sanity-check eval/questions.json against the documents in data/docs/ BEFORE ingesting.

Usage (from the project root):
    python -m eval.check_evidence                     # defaults: chunk 300 words, overlap 50
    python -m eval.check_evidence --size 500 --overlap 60

For every answerable question it reports:
  - how many times the evidence phrase appears in the docs (want exactly 1)
  - how many simulated word-chunks contain the whole phrase (want >= 1; 0 means the
    phrase would straddle a chunk boundary and always score as a MISS)
Also warns if an unanswerable question's keywords look answered by the docs.
The simulated chunking is an approximation: your ingest.py may split differently, so
after ingesting, re-check with:  select count(*) from chunks where text ilike '%phrase%';
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def chunk_words(text: str, size: int, overlap: int) -> list[str]:
    words = text.split()
    step = max(1, size - overlap)
    return [" ".join(words[i:i + size]) for i in range(0, max(1, len(words)), step)]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--size", type=int, default=300)
    p.add_argument("--overlap", type=int, default=50)
    p.add_argument("--docs", default=str(ROOT / "data" / "docs"))
    p.add_argument("--file", default=str(ROOT / "eval" / "questions.json"))
    args = p.parse_args()

    files = sorted(f for f in Path(args.docs).glob("*") if f.suffix in {".md", ".txt"})
    if not files:
        sys.exit(f"No .md/.txt documents in {args.docs}")
    texts = {f.name: f.read_text(encoding="utf-8") for f in files}
    total_words = sum(len(t.split()) for t in texts.values())
    all_chunks = [c for t in texts.values() for c in chunk_words(t, args.size, args.overlap)]
    full = normalize(" ".join(texts.values()))
    print(f"{len(files)} docs, {total_words} words, ~{len(all_chunks)} simulated chunks "
          f"(size={args.size}, overlap={args.overlap})\n")

    questions = json.loads(Path(args.file).read_text(encoding="utf-8"))
    problems = 0
    for q in questions:
        if not q.get("answerable", True):
            continue
        ev = normalize(q["evidence"])
        occurrences = full.count(ev)
        in_chunks = sum(ev in normalize(c) for c in all_chunks)
        ok = occurrences == 1 and in_chunks >= 1
        problems += not ok
        print(f"{q['id']}  occurrences={occurrences}  chunks={in_chunks}  {'ok' if ok else 'CHECK'}  {q['evidence']!r}")

    print(f"\n{problems} problem(s) among answerable questions.")
    print("\nUnanswerable questions: confirm by eye that none is answered in the docs:")
    for q in questions:
        if not q.get("answerable", True):
            print(f"  {q['id']}: {q['question']}")


if __name__ == "__main__":
    main()