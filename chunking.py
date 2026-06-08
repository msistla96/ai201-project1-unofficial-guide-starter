"""
chunking.py — Milestone 3: load -> clean -> chunk -> store

Reads the three local sources for the Unofficial Immigration Guide and turns
them into chunks with a single, consistent metadata schema (so downstream
embedding / retrieval doesn't care which source a chunk came from):

  - Blogs  : documents/Text/Blogs/*.txt
             Paragraph-packed chunks, ~500 tokens, ~75-token overlap.
             A single paragraph over the limit is split by sentence.
  - FAQs   : documents/Text/FAQs/*.txt
             One chunk per FAQ (question + answer kept together for context).
  - Reddit : scripts/Reddit/us_all_posts.json
             Primary chunk = post *title* + a top-level comment (plus its
             nested reply subtree), split only when the comment has replies.
             The post *body* is a separate next-level (parent) chunk, split if
             long, retrievable on demand for context. Comment chunks link to
             their parent via metadata.extra.parent_id.

Strategy and sizes come from the "Chunking Strategy" section of planning.md.

Token counts use a word-based approximation (words * 1.3). Good enough for
first-pass chunking; swap in tiktoken later if eval shows boundary issues.

Every chunk is a JSON object with the shape:

    {
      "chunk_id": "<source_type>_<stable-id>_<n>",
      "text": "<the chunk text>",
      "metadata": {
        "source_type": "blog" | "faq" | "reddit",
        "source":      "<filename / subreddit>",
        "title":       "<doc or post title>",
        "url":         "<url or null>",
        "date":        "<ISO 8601 or null>",
        "author":      "<author or null>",
        "token_estimate": <int>,
        "extra":       { ... source-specific fields ... }
      }
    }

Output: documents/chunks.jsonl  (one JSON object per line)

Run:
    python chunking.py
"""

import os
import re
import json
import html
import logging
from datetime import datetime, timezone

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)

# --- Config -----------------------------------------------------------------

HERE = os.path.dirname(os.path.abspath(__file__))

BLOG_DIR = os.path.join(HERE, "documents", "Text", "Blogs")
FAQ_DIR = os.path.join(HERE, "documents", "Text", "FAQs")
PLAIN_FAQ_DIR = os.path.join(HERE, "documents", "Plain Text", "FAQs")
REDDIT_JSON = os.path.join(HERE, "scripts", "Reddit", "us_all_posts.json")
OUTPUT_PATH = os.path.join(HERE, "documents", "chunks.jsonl")

# Sizes from planning.md -> Chunking Strategy.
BLOG_MAX_TOKENS = 200
BLOG_OVERLAP_TOKENS = 75          
REDDIT_MAX_TOKENS = 200
FAQ_MAX_TOKENS = 200             # FAQs stay whole; only split if truly huge
MIN_CHUNK_TOKENS = 8             # drop near-empty fragments

_DEAD_BODIES = {"[deleted]", "[removed]", "", "[unavailable]"}

# --- Token estimate ---------------------------------------------------------

def estimate_tokens(text):
    """Word-based token approximation."""
    return int(len(text.split()) * 1.3)


# --- Text helpers -----------------------------------------------------------

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


def clean_text(text):
    """Unescape HTML entities and normalise whitespace, keep paragraph breaks."""
    if not text:
        return ""
    text = html.unescape(text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # collapse 3+ newlines to a paragraph break, trim trailing spaces per line
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def is_dead(body):
    return (body or "").strip().lower() in _DEAD_BODIES


def _split_oversize(text, max_tokens):
    """Split one oversize block into <= max_tokens pieces by sentence."""
    sentences = _SENTENCE_RE.split(text)
    pieces, buf = [], []
    for sent in sentences:
        candidate = " ".join(buf + [sent]).strip()
        if buf and estimate_tokens(candidate) > max_tokens:
            pieces.append(" ".join(buf).strip())
            buf = [sent]
        else:
            buf.append(sent)
    if buf:
        pieces.append(" ".join(buf).strip())
    return [p for p in pieces if p]


def _overlap_tail(text, overlap_tokens):
    """Return the trailing ~overlap_tokens words of text (word-approx)."""
    if overlap_tokens <= 0:
        return ""
    words = text.split()
    n = max(1, int(overlap_tokens / 1.3))
    return " ".join(words[-n:])


# --- Chunking strategies ----------------------------------------------------

def chunk_blog(body, max_tokens=BLOG_MAX_TOKENS, overlap_tokens=BLOG_OVERLAP_TOKENS):
    """Paragraph-packed chunks with a small word overlap (blogs).

    Paragraphs (split on blank lines) are greedily packed until adding the next
    one would exceed max_tokens. A single paragraph larger than the limit is
    split by sentence. Each new chunk is seeded with the tail of the previous
    one to give ~overlap_tokens of overlap.
    """
    paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()]
    chunks, buf = [], []

    def flush():
        if buf:
            chunks.append("\n\n".join(buf).strip())
            buf.clear()

    for para in paragraphs:
        if estimate_tokens(para) > max_tokens:
            flush()
            chunks.extend(_split_oversize(para, max_tokens))
            continue
        candidate = "\n\n".join(buf + [para])
        if buf and estimate_tokens(candidate) > max_tokens:
            tail = _overlap_tail(buf[-1], overlap_tokens)
            flush()
            if tail:
                buf.append(tail)
        buf.append(para)
    flush()
    return chunks


def chunk_faq(question, answer, max_tokens=FAQ_MAX_TOKENS):
    """One chunk per FAQ: question + answer kept together for context.

    Only split when an answer is unusually large, in which case the question is
    repeated at the head of every piece so each chunk stands on its own.
    """
    q = (question or "").strip()
    a = (answer or "").strip()
    block = f"Q: {q}\nA: {a}".strip()
    if estimate_tokens(block) <= max_tokens:
        return [block]
    pieces = _split_oversize(a, max_tokens - estimate_tokens(f"Q: {q}\nA: "))
    return [f"Q: {q}\nA: {p}".strip() for p in pieces]


def chunk_reddit_comment(post_title, comment_body, replies_text, max_tokens=REDDIT_MAX_TOKENS):
    """Primary chunk: post *title* + a top-level comment (+ its reply subtree).

    The post title (not the post body) anchors the comment so the chunk is
    self-contained. Per planning.md, the token limit is applied only when the
    comment has replies; a lone comment is kept whole.
    """
    header = f"[Post] {post_title}".strip() if post_title else ""
    body = (comment_body or "").strip()
    if replies_text:
        full = f"{header}\n[Comment] {body}\n{replies_text}".strip()
        if estimate_tokens(full) > max_tokens:
            return _split_oversize(full, max_tokens)
        return [full]
    return [f"{header}\n[Comment] {body}".strip()]


def chunk_reddit_post(post_title, post_body, max_tokens=REDDIT_MAX_TOKENS):
    """Next-level (parent) chunk(s): the post title + body.

    The post body lives in its own chunk so it can be retrieved when a matched
    comment needs the original context. A long body is split by sentence, with
    the title repeated on each piece so every parent chunk stands alone.
    """
    header = f"[Post] {post_title}".strip() if post_title else ""
    body = (post_body or "").strip()
    if not body:
        return [header] if header else []
    full = f"{header}\n{body}".strip()
    if estimate_tokens(full) <= max_tokens:
        return [full]
    budget = max(max_tokens - estimate_tokens(header), max_tokens // 2)
    pieces = _split_oversize(body, budget)
    return [f"{header}\n{p}".strip() for p in pieces]


# --- Reddit helpers ---------------------------------------------------------

def _flatten_replies(replies, depth=1):
    """Flatten a reply subtree into indented '> ' lines, skipping dead bodies."""
    lines = []
    for r in replies or []:
        body = clean_text(r.get("body", ""))
        if not is_dead(body):
            indent = "  " * depth
            lines.append(f"{indent}> {body}")
        lines.extend(_flatten_replies(r.get("replies"), depth + 1))
    return lines


def _iso_from_utc(ts):
    if not ts:
        return None
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()
    except (ValueError, OSError, TypeError):
        return None


# --- Loaders: each yields (texts, base_metadata, stable_id) ----------------

_DATE_RE = re.compile(
    r"^(January|February|March|April|May|June|July|August|September|October|"
    r"November|December)\s+\d{1,2},\s+\d{4}$"
)


def _parse_blog_date(line):
    line = line.strip()
    if _DATE_RE.match(line):
        try:
            return datetime.strptime(line, "%B %d, %Y").date().isoformat()
        except ValueError:
            return None
    return None


def load_blogs():
    """Yield blog chunk records. Title = line 1, optional date = line 2."""
    if not os.path.isdir(BLOG_DIR):
        logger.warning("Blog dir not found: %s", BLOG_DIR)
        return
    for fname in sorted(os.listdir(BLOG_DIR)):
        if not fname.endswith(".txt"):
            continue
        path = os.path.join(BLOG_DIR, fname)
        with open(path, encoding="utf-8") as f:
            raw = f.read()
        lines = [ln for ln in raw.split("\n")]
        title = (lines[0].strip() if lines else fname).strip() or fname
        date = _parse_blog_date(lines[1]) if len(lines) > 1 else None
        # body = everything after the title (and date line, if present)
        body_start = 2 if date else 1
        body = clean_text("\n".join(lines[body_start:]))
        if not body:
            continue
        stable = re.sub(r"[^a-z0-9]+", "_", os.path.splitext(fname)[0].lower()).strip("_")
        meta = {
            "source_type": "blog",
            "source": fname,
            "title": title,
            "url": None,
            "date": date,
            "author": None,
            "extra": {},
        }
        yield chunk_blog(body), meta, stable


def load_faqs():
    """Yield FAQ chunk records. Each '#N: question' block becomes one chunk."""
    if not os.path.isdir(FAQ_DIR):
        logger.warning("FAQ dir not found: %s", FAQ_DIR)
        return
    marker = re.compile(r"^#(\d+):\s*(.+)$")
    for fname in sorted(os.listdir(FAQ_DIR)):
        if not fname.endswith(".txt"):
            continue
        path = os.path.join(FAQ_DIR, fname)
        with open(path, encoding="utf-8") as f:
            lines = f.read().split("\n")

        title = fname
        # Best-effort title: first substantive line (>= 5 words) that isn't a
        # byline/date header. Skips "Author:", the author name, "Updated", date.
        for ln in lines:
            s = ln.strip()
            if (
                len(s.split()) >= 5
                and not s.lower().startswith(("author", "updated"))
                and not _parse_blog_date(s)
            ):
                title = s
                break

        # Walk the file, collecting (number, question, answer-lines) blocks.
        faqs, cur_num, cur_q, cur_a = [], None, None, []
        for ln in lines:
            m = marker.match(ln.strip())
            if m:
                if cur_num is not None:
                    faqs.append((cur_num, cur_q, "\n".join(cur_a)))
                cur_num, cur_q, cur_a = m.group(1), m.group(2).strip(), []
            elif cur_num is not None:
                if ln.strip().lower().startswith("disclaimer:"):
                    break
                cur_a.append(ln)
        if cur_num is not None:
            faqs.append((cur_num, cur_q, "\n".join(cur_a)))

        stable_base = re.sub(r"[^a-z0-9]+", "_", os.path.splitext(fname)[0].lower()).strip("_")
        for num, q, a in faqs:
            a = clean_text(a)
            if not a:
                continue
            meta = {
                "source_type": "faq",
                "source": fname,
                "title": title,
                "url": None,
                "date": None,
                "author": None,
                "extra": {"faq_number": int(num), "question": q},
            }
            yield chunk_faq(q, a), meta, f"{stable_base}_{num}"


_PLAIN_DATE_RE = re.compile(r"\((\d{1,2})\.([A-Za-z]{3,9})\.(\d{4})\)")
_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


def _parse_plain_date(text):
    """Pull the trailing (DD.Mon.YYYY) date from a Murthy-style FAQ answer."""
    matches = _PLAIN_DATE_RE.findall(text)
    if not matches:
        return None
    day, mon, year = matches[-1]  # use the last/most-recent date in the answer
    month = _MONTHS.get(mon[:3].lower())
    if not month:
        return None
    try:
        return datetime(int(year), month, int(day)).date().isoformat()
    except ValueError:
        return None


def load_plain_faqs():
    """Yield FAQ chunks from documents/Plain Text/FAQs (one Q&A per file).

    Format: question on line 1, an 'Answer' marker line, then the answer, with
    a trailing (DD.Mon.YYYY) date. Mapped onto the same 'faq' schema as the
    other sources for consistency.
    """
    if not os.path.isdir(PLAIN_FAQ_DIR):
        logger.warning("Plain FAQ dir not found: %s", PLAIN_FAQ_DIR)
        return
    for fname in sorted(os.listdir(PLAIN_FAQ_DIR)):
        path = os.path.join(PLAIN_FAQ_DIR, fname)
        if not os.path.isfile(path) or fname.startswith("."):
            continue
        with open(path, encoding="utf-8") as f:
            lines = [ln for ln in f.read().split("\n")]

        nonempty = [ln for ln in lines if ln.strip()]
        if not nonempty:
            continue
        question = nonempty[0].strip()

        # Answer = everything after the first standalone "Answer" marker.
        answer_lines, started = [], False
        for ln in lines:
            if not started:
                if ln.strip().lower() == "answer":
                    started = True
                continue
            answer_lines.append(ln)
        answer = clean_text("\n".join(answer_lines)) if started else clean_text(
            "\n".join(lines[1:]))
        if not answer:
            continue

        date = _parse_plain_date(answer)
        # Drop the trailing parenthetical date(s) from the chunk text itself.
        answer = _PLAIN_DATE_RE.sub("", answer).strip()

        stable = re.sub(r"[^a-z0-9]+", "_", os.path.splitext(fname)[0].lower()).strip("_")
        meta = {
            "source_type": "faq",
            "source": f"Plain Text/FAQs/{fname}",
            "title": question,
            "url": None,
            "date": date,
            "author": None,
            "extra": {"question": question, "faq_set": "murthy"},
        }
        yield chunk_faq(question, answer), meta, stable


def load_reddit():
    """Yield Reddit chunk records: primary 'comment' chunks (post title +
    comment) plus next-level 'post' chunks (the post body) for context."""
    if not os.path.isfile(REDDIT_JSON):
        logger.warning("Reddit JSON not found: %s", REDDIT_JSON)
        return
    with open(REDDIT_JSON, encoding="utf-8") as f:
        posts = json.load(f)

    for post in posts:
        post_id = post.get("post_id") or post.get("id") or ""
        subreddit = post.get("subreddit", "")
        title = clean_text(post.get("title", "")) or "(untitled)"
        date = _iso_from_utc(post.get("created_utc"))
        url = post.get("url")

        def base_meta(extra):
            return {
                "source_type": "reddit",
                "source": f"r/{subreddit}" if subreddit else "reddit",
                "title": title,
                "url": url,
                "date": date,
                "author": post.get("author"),
                "extra": extra,
            }

        # 1) Primary chunks: post title + each top-level comment (+ replies).
        for idx, comment in enumerate(post.get("comments", [])):
            body = clean_text(comment.get("body", ""))
            if is_dead(body):
                continue
            replies_text = "\n".join(_flatten_replies(comment.get("replies")))
            texts = chunk_reddit_comment(title, body, replies_text)
            cid = comment.get("comment_id") or str(idx)
            meta = base_meta({
                "post_id": post_id,
                "kind": "comment",
                "level": "comment",          # primary retrieval unit
                "parent_id": f"reddit_{post_id}_post",
                "comment_id": cid,
                "comment_author": comment.get("author"),
                "score": comment.get("score", 0),
                "has_replies": bool(comment.get("replies")),
            })
            yield texts, meta, f"{post_id}_c_{cid}"

        # 2) Next-level (parent) chunk(s): the post body, retrieved when a
        #    matched comment needs the original context. Split if long.
        post_body = clean_text(post.get("body", ""))
        post_texts = chunk_reddit_post(title, post_body)
        if post_texts:
            yield (
                post_texts,
                base_meta({
                    "post_id": post_id,
                    "kind": "post",
                    "level": "post",         # parent / context, retrieved on demand
                    "score": post.get("score", 0),
                    "num_comments": post.get("num_comments", 0),
                    "flair": post.get("flair"),
                }),
                f"{post_id}_post",
            )


# --- Chunk assembly ----------------------------------------------------------

def _records_to_chunks(texts, meta, stable_id):
    """Attach the consistent schema + a stable chunk_id to each text piece."""
    out = []
    for i, text in enumerate(texts):
        text = text.strip()
        if estimate_tokens(text) < MIN_CHUNK_TOKENS:
            continue
        m = dict(meta)
        m["token_estimate"] = estimate_tokens(text)
        out.append({
            "chunk_id": f"{meta['source_type']}_{stable_id}_{i}",
            "text": text,
            "metadata": m,
        })
    return out


def run(output_path=OUTPUT_PATH):
    """Load every source, clean, chunk, and write chunks.jsonl."""
    all_chunks = []
    for loader in (load_blogs, load_faqs, load_plain_faqs, load_reddit):
        before = len(all_chunks)
        for texts, meta, stable_id in loader():
            all_chunks.extend(_records_to_chunks(texts, meta, stable_id))
        logger.info("%s -> %d chunk(s)", loader.__name__, len(all_chunks) - before)

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        for chunk in all_chunks:
            f.write(json.dumps(chunk, ensure_ascii=False) + "\n")

    by_type = {}
    for c in all_chunks:
        t = c["metadata"]["source_type"]
        by_type[t] = by_type.get(t, 0) + 1
    logger.info("Wrote %d chunk(s) to %s %s", len(all_chunks), output_path, by_type)
    return all_chunks


if __name__ == "__main__":
    run()
