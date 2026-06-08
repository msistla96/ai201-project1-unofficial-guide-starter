"""
generator.py — Generation stage (see Architecture diagram).

Takes the chunks returned by retriever.Retriever.retrieve() and asks the LLM
(llama-3.3-70b-versatile via Groq) to write an answer grounded ONLY in those
chunks, with inline source citations like [1], [2]. A "Sources" list mapping
each citation number to its title/url is appended to every answer.
"""

import logging

from groq import Groq
from config import GROQ_API_KEY, LLM_MODEL, UTILITY_MODEL

logger = logging.getLogger(__name__)

_client = Groq(api_key=GROQ_API_KEY)

SYSTEM_PROMPT = """\
You are The Unofficial Immigration Guide, an assistant that answers questions about US \
immigration using ONLY the context sources provided by the user.

Rules:
- Base every claim strictly on the context sources. Do not use outside knowledge.
- Cite the sources you used inline with bracketed numbers, e.g. [1], [2]. 
- If the context does not contain enough information to answer, say so plainly \
and do not guess. Do not fabricate citations.
- If the question is outside US immigration or unrelated to the context, say it \
is outside the scope of this guide. Do not cite any sources.
- The context is drawn from forums and community posts (Reddit, FAQs, blogs), \
so it may be anecdotal — note when guidance reflects user experience rather \
than official rules, and remind the user to verify with official USCIS sources \
for anything time-sensitive.
- Be concise and direct. Answer in plain language.\
"""

NO_CONTEXT_MESSAGE = (
    "I couldn't find anything relevant in the guide. "
    "Try rephrasing your question."
)


def build_context(retrieved_chunks):
    """Render numbered context blocks and a parallel sources footer.

    Returns (context_text, sources_footer). Numbering is shared so the model's
    inline [n] citations line up with the Sources list.
    """
    context_lines, source_lines = [], []
    for i, chunk in enumerate(retrieved_chunks, 1):
        meta = chunk.get("metadata", {})
        title = meta.get("title") or meta.get("source") or "source"
        url = meta.get("url") or "(no url)"
        context_lines.append(
            f"[{i}] (source: {meta.get('source')}, type: {meta.get('doc_type')})\n"
            f"{chunk['text']}"
        )
        source_lines.append(f"[{i}] {title} — {url}")
    return "\n\n".join(context_lines), "\n".join(source_lines)

def generate_response(
    query: str,
    retrieved_chunks: list[dict],
) -> str:
    """Generate a grounded, citation-bearing answer. Returns a string."""
    if not retrieved_chunks:
        return NO_CONTEXT_MESSAGE

    context_text, sources_footer = build_context(retrieved_chunks)

    # Current turn: inject context into the user message
    current_user_message = (
        f"Context sources:\n{context_text}\n\n"
        f"Question: {query}\n\n"
        f"Answer using only the sources above, citing them inline as [n]."
    )

    # Build message list: system → history → current query
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    messages.append({"role": "user", "content": current_user_message})

    try:
        completion = _client.chat.completions.create(
            model=LLM_MODEL,
            messages=messages,
            temperature=0.2,
        )
    except Exception:
        logger.exception("LLM generation failed")
        raise

    answer = completion.choices[0].message.content.strip()
    full_response = f"{answer}\n\n---\n**Sources**\n{sources_footer}"


    return full_response


def test_generator():
    from retriever import Retriever, EVAL_QUESTIONS

    # Without filters
    retriever = Retriever()
    for i,question in enumerate(EVAL_QUESTIONS):
        chunks1 = retriever.semantic_search(question)
        print(f"Q{i}:\n")
        response = generate_response(question, chunks1)
        print(response)

    # With filters(one query)
    retriever = Retriever()
    filter = {"source": {"$in": ["r/h1b"]}}
    chunks = retriever.semantic_search(EVAL_QUESTIONS[2], where = filter)
    response = generate_response(question, chunks)
    print(response)


if __name__ == "__main__":
    test_generator()
