import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))

from app.config import settings
from app.generate import REFUSAL, _get_client, generate
from app.retrieve import retrieve
from app.db import close_pool,get_tenant_id_by_name

JUDGE_PROMPT = (
    "You are grading an answer against a reference answer.\n"
    "Question: {question}\n"
    "Reference answer: {reference}\n"
    "Candidate answer: {candidate}\n\n"
    "Does the candidate convey the same key facts as the reference, without "
    "contradicting it? Reply with exactly one word: CORRECT or INCORRECT."
)

# pure scoring (unit tested)

def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def hit_rank(evidence: str, chunks: list[dict]) -> int | None:
    """1-based rank of the first retrieved chunk containing the evidence phrase, else None."""
    ev = normalize(evidence)
    for i, c in enumerate(chunks, 1):
        if ev and ev in normalize(c["text"]):
            return i
    return None


def is_refusal(answer: str) -> bool:
    a = normalize(answer)
    return normalize(REFUSAL) in a or "i don't know" in a or "i do not know" in a


# LLM Judge

def judge(question: str, reference: str, candidate: str) -> bool | None:
    """True/False verdict, or None if the judge returned nothing usable."""
    resp = _get_client().chat.completions.create(
        model=settings.llm_model,
        messages=[{"role": "user", "content": JUDGE_PROMPT.format(
            question=question, reference=reference, candidate=candidate)}],
        temperature=0,
        max_completion_tokens=512,
        extra_body={"reasoning_effort": settings.llm_reasoning_effort},
    )
    verdict = (resp.choices[0].message.content or "").strip().upper()
    if verdict.startswith("CORRECT"):
        return True
    if verdict.startswith("INCORRECT"):
        return False
    return None


def evaluate(questions: list[dict], k: int, use_judge: bool,tenant_id: int,pause: float = 0.5) -> dict:
    rows = []
    for q in questions:
        chunks = retrieve(q["question"],tenant_id, k)
        row = {"id": q["id"], "question": q["question"], "answerable": q["answerable"]}

        if q["answerable"]:
            row["rank"] = hit_rank(q["evidence"], chunks)

        if use_judge:
            answer = generate(q["question"], chunks)
            row["answer"] = answer
            if q["answerable"]:
                row["correct"] = judge(q["question"], q["answer"], answer)
            else:
                row["correct"] = is_refusal(answer)  
            time.sleep(pause)  
        rows.append(row)

    ans = [r for r in rows if r["answerable"]]
    unans = [r for r in rows if not r["answerable"]]
    summary = {
        "n_answerable": len(ans),
        "n_unanswerable": len(unans),
        "retrieval_hit_at_1": sum(r["rank"] == 1 for r in ans) / len(ans) if ans else None,
        "retrieval_hit_at_k": sum(r["rank"] is not None for r in ans) / len(ans) if ans else None,
        "retrieval_mrr": sum(1 / r["rank"] for r in ans if r["rank"]) / len(ans) if ans else None,
    }
    if use_judge:
        graded = [r for r in ans if r["correct"] is not None]
        summary["answer_accuracy"] = sum(r["correct"] for r in graded) / len(graded) if graded else None
        summary["judge_errors"] = len(ans) - len(graded)
        summary["refusal_accuracy"] = sum(r["correct"] for r in unans) / len(unans) if unans else None
    return {"summary": summary, "rows": rows}

def fmt(x) -> str:
    return "n/a" if x is None else f"{x:.2f}"

def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--k", type=int, default=settings.top_k)
    p.add_argument("--no-judge", action="store_true")
    p.add_argument("--file", default=str(ROOT / "eval" / "questions.json"))
    p.add_argument("--tenant", default="default", help="tenant name to run the eval as")
    args = p.parse_args()

    questions = json.loads(Path(args.file).read_text(encoding="utf-8"))
    if not questions:
        sys.exit("eval/questions.json is empty. Add questions first (see the docstring).")
    for q in questions:
        q.setdefault("answerable", True)
        if q["answerable"] and not q.get("evidence"):
            sys.exit(f"{q['id']}: answerable questions need an 'evidence' phrase")

        tenant_id = get_tenant_id_by_name(args.tenant)
    if tenant_id is None:
        sys.exit(f"No tenant named {args.tenant!r}.")

    try:
        result = evaluate(questions, args.k, use_judge=not args.no_judge, tenant_id=tenant_id)
    finally:
        close_pool()

    print(f"\n{'id':<8}{'rank':<6}{'answer':<10}question")
    for r in result["rows"]:
        rank = "-" if not r["answerable"] else (str(r["rank"]) if r["rank"] else "MISS")
        ok = "" if "correct" not in r else {True: "ok", False: "WRONG", None: "?"}[r["correct"]]
        print(f"{r['id']:<8}{rank:<6}{ok:<10}{r['question'][:70]}")

    s = result["summary"]
    print(f"\nAnswerable: {s['n_answerable']}   Unanswerable: {s['n_unanswerable']}")
    print(f"Retrieval  hit@1={fmt(s['retrieval_hit_at_1'])}  hit@{args.k}={fmt(s['retrieval_hit_at_k'])}  MRR={fmt(s['retrieval_mrr'])}")
    if "answer_accuracy" in s:
        print(f"Answers    accuracy={fmt(s['answer_accuracy'])} (judge errors: {s['judge_errors']})  refusal accuracy={fmt(s['refusal_accuracy'])}")

    # Save the run together with the config that produced it, so baselines are reproducible.
    out_dir = ROOT / "eval" / "results"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / f"{datetime.now():%Y%m%d-%H%M%S}.json"
    out.write_text(json.dumps({
        "config": {
            "tenant": args.tenant,
            "embedding_model": settings.embedding_model, "chunk_size": settings.chunk_size,
            "chunk_overlap": settings.chunk_overlap, "top_k": args.k, "llm_model": settings.llm_model,
        },
        **result,
    }, indent=2), encoding="utf-8")
    print(f"\nSaved {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
