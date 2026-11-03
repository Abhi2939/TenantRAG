from groq import Groq

from app.config import settings

REFUSAL = "I don't know based on the provided documents."

SYSTEM_PROMPT = (
    "You answer questions using ONLY the numbered context passages provided. "
    "If the passages do not contain the answer, reply exactly: "
    f'"{REFUSAL}" '
    "Do not use outside knowledge. Be concise. "
    "Cite the passages you used like [1] or [2]."
)

_client: Groq | None = None

def _get_client() -> Groq:
    global _client
    if _client is None:
        if not settings.groq_api_key:
            raise RuntimeError("GROQ_API_KEY is not set")
        _client = Groq(api_key=settings.groq_api_key)
    return _client

def build_message(question: str,chunks: list[dict]) -> list[dict]:
    context = "\n\n".join(
        f"[{i}] (source: {c['source']})\n{c['text']}" for i, c in enumerate(chunks, 1)
    )
    user = f"Context:\n{context}\n\nQuestion: {question}"
    return[
        {"role":"system","content":SYSTEM_PROMPT},
        {"role":"user","content":user},
    ]

def generate(question:str,chunks:list[dict]) -> str:
    if not chunks:
        return REFUSAL

    resp = _get_client().chat.completions.create(
        model=settings.llm_model,
        messages=build_message(question,chunks),
        temperature=0,
        max_completion_tokens=settings.llm_max_tokens,
        extra_body={"reasoning_effort": settings.llm_reasoning_effort},
    )

    return (resp.choices[0].message.content or "").strip()

