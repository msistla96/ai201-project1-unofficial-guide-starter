"""
clean_posts.py — quick cleanup pass on the scraped Reddit dump.

  1. Drops every post from r/legaladvice.
  2. Drops every comment (at any nesting depth) with score < 1.

Reads scripts/Reddit/us_all_posts.json and writes a cleaned copy. By default
it writes in place after saving a .bak; pass --out to write elsewhere.

Run:
    python scripts/clean_posts.py
    python scripts/clean_posts.py --out scripts/Reddit/us_all_posts.clean.json
"""

import os
import json
import shutil
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PATH = os.path.join(HERE, "Reddit", "us_all_posts.json")

REMOVE_SUBREDDITS = {"legaladvice"}
MIN_COMMENT_SCORE = 1


def load_posts(path):
    """Load the post array, salvaging complete posts if the file is truncated."""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    try:
        return json.loads(text), False
    except json.JSONDecodeError:
        pass

    # Truncated dump: walk the top-level array object-by-object and keep every
    # post that decodes cleanly, discarding the trailing partial one.
    dec = json.JSONDecoder()
    i = text.find("[")
    if i == -1:
        raise ValueError("no JSON array found in file")
    i += 1
    posts = []
    n = len(text)
    while i < n:
        while i < n and text[i] in " \t\r\n,":
            i += 1
        if i >= n or text[i] == "]":
            break
        try:
            obj, end = dec.raw_decode(text, i)
        except json.JSONDecodeError:
            break  # hit the truncated tail
        posts.append(obj)
        i = end
    return posts, True


def filter_comments(comments):
    """Recursively drop comments with score < MIN_COMMENT_SCORE."""
    kept = []
    dropped = 0
    for c in comments or []:
        sub_kept, sub_dropped = filter_comments(c.get("replies"))
        dropped += sub_dropped
        if c.get("score", 0) < MIN_COMMENT_SCORE:
            dropped += 1  # this comment is dropped, but keep counting its tree above
            continue
        c["replies"] = sub_kept
        kept.append(c)
    return kept, dropped


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--path", default=DEFAULT_PATH, help="input JSON path")
    ap.add_argument("--out", default=None, help="output path (default: in place + .bak)")
    args = ap.parse_args()

    posts, salvaged = load_posts(args.path)
    if salvaged:
        print(f"WARNING: input was truncated; salvaged {len(posts)} complete post(s).")

    kept_posts = []
    removed_posts = 0
    removed_comments = 0
    for post in posts:
        if (post.get("subreddit") or "").lower() in REMOVE_SUBREDDITS:
            removed_posts += 1
            continue
        post["comments"], dropped = filter_comments(post.get("comments"))
        removed_comments += dropped
        kept_posts.append(post)

    out_path = args.out or args.path
    if out_path == args.path:
        shutil.copy2(args.path, args.path + ".bak")

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(kept_posts, f, ensure_ascii=False, indent=2)

    print(f"Posts: {len(posts)} -> {len(kept_posts)} "
          f"(removed {removed_posts} from r/legaladvice)")
    print(f"Comments dropped (score < {MIN_COMMENT_SCORE}): {removed_comments}")
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
