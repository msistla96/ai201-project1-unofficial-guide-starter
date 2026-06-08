import requests
import json
import time
from datetime import datetime, timedelta
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE_URL = "https://arctic-shift.photon-reddit.com/api"
HEADERS = {"User-Agent": "Mozilla/5.0"}

# ─────────────────────────────────────────
# Keywords
# ─────────────────────────────────────────

IMMIGRATION_KEYWORDS = [
    "H1B", "H4", "F1", "F2", "L1", "L2", "O1", "EB1", "EB2", "EB3",
    "B1", "B2", "K1", "J1", "TN", "OPT", "CPT", "STEM",
    "I-485", "I-130", "I-140", "I-765", "I-131", "I-90", "I-539",
    "I-864", "N-400", "USCIS", "EAD", "advance parole", "biometrics",
    "RFE", "NOID", "NTA", "priority date", "visa bulletin",
    "green card", "adjustment of status", "AOS", "naturalization",
    "US citizenship", "asylum", "refugee", "DACA", "TPS", "parole",
    "consular processing", "NVC", "US embassy", "USCIS interview",
    "premium processing", "case status", "receipt notice",
    "denied", "rejection", "delay", "processing time", "out of status",
    "overstay", "grace period", "deportation", "removal", "unlawful presence",
    "mandamus", "portability", "layoff", "job change", "amendment",
]

# US-specific signals — must match at least one
US_KEYWORDS = [
    # Agencies
    "USCIS", "ICE", "CBP", "DHS", "DOL", "DOS", "EOIR",
    "NVC", "SEVP", "OFLC", "NLRB",
    # Forms
    "I-485", "I-130", "I-140", "I-765", "I-131", "I-90",
    "I-539", "I-864", "I-693", "I-797", "I-94", "N-400",
    "DS-260", "DS-5540", "DS-160",
    # Visa types unique to US
    "H1B", "H4", "H2A", "H2B", "O1", "O2", "EB1", "EB2", "EB3",
    "EB4", "EB5", "TN visa", "E3", "K1", "K3", "DV lottery",
    "OPT", "CPT", "STEM OPT", "cap gap",
    # US-specific terms
    "green card", "lawful permanent resident", "LPR",
    "adjustment of status", "consular processing",
    "advance parole", "EAD", "work permit",
    "naturalization", "US citizenship", "DACA", "TPS",
    "visa bulletin", "priority date", "cutoff date",
    "PERM", "labor certification", "national interest waiver", "NIW",
    "asylum US", "immigration court", "BIA", "IJ",
    "US embassy", "US consulate", "visa stamp",
    "premium processing", "mandamus", "RFE", "NOID", "NTA",
    # US locations
    "United States", "America", "USA","US"
]

# Countries/systems that are NOT US — flag if only these appear
NON_US_SIGNALS = [
    "UK visa", "tier 2", "tier 4", "skilled worker visa",
    "canada PR", "express entry", "NOC code", "IRCC",
    "australia PR", "subclass", "points test",
    "schengen", "EU blue card",
    "india OCI", "PIO card",
]

# ─────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────

def get_date_range():
    now = datetime.utcnow()
    one_year_ago = now - timedelta(days=365)
    return one_year_ago.strftime("%Y-%m-%d"), now.strftime("%Y-%m-%d")

def is_deleted(text):
    if not text:
        return True
    return text.strip().lower() in ["[deleted]", "[removed]", "[ deleted ]", "[ removed ]"]

def is_valid_post(post):
    if is_deleted(post.get("title")):
        return False
    if is_deleted(post.get("author")):
        return False
    body = post.get("selftext", "")
    if body and is_deleted(body):
        return False
    return True

def is_us_related(post):
    """Must have at least one US-specific keyword and no dominant non-US signals"""
    text = f"{post.get('title', '')} {post.get('selftext', '')}".lower()

    # Check for non-US signals first
    non_us_matches = [kw for kw in NON_US_SIGNALS if kw.lower() in text]

    # Check for US signals
    us_matches = [kw for kw in US_KEYWORDS if kw.lower() in text]

    # Reject if only non-US signals and no US signals
    if non_us_matches and not us_matches:
        return False, []

    return len(us_matches) >= 1, us_matches

def is_immigration_related(post, min_keyword_matches=1):
    text = f"{post.get('title', '')} {post.get('selftext', '')}".lower()
    matches = [kw for kw in IMMIGRATION_KEYWORDS if kw.lower() in text]
    return len(matches) >= min_keyword_matches, matches

def is_lawyer_related(post):
    text = f"{post.get('title', '')} {post.get('selftext', '')}".lower()
    matches = [kw for kw in LAWYER_KEYWORDS if kw.lower() in text]
    return len(matches) >= 1, matches

def categorize_post(post):
    """Tag each post with its category"""
    categories = []
    _, lawyer_matches = is_lawyer_related(post)
    if lawyer_matches:
        categories.append("lawyer_seeking_or_review")
    _, immig_matches = is_immigration_related(post)
    if immig_matches:
        categories.append("immigration_process")
    if not categories:
        categories.append("general")
    return categories

# ─────────────────────────────────────────
# API calls
# ─────────────────────────────────────────

def get_posts(subreddit, after, before, max_posts=1000):
    """
    Paginated Arctic Shift fetch.

    Continues requesting pages until:
    - max_posts reached
    - no more results available
    """

    subreddit = subreddit.replace("r/", "").strip()

    all_posts = []
    seen_ids = set()

    current_after = after

    # Use whatever Arctic Shift allows
    PAGE_SIZE = "auto"

    while len(all_posts) < max_posts:

        params = {
            "subreddit": subreddit,
            "after": current_after,
            "before": before,
            "limit": PAGE_SIZE,
            "sort": "asc"
        }

        try:
            response = requests.get(
                f"{BASE_URL}/posts/search",
                params=params,
                headers=HEADERS,
                timeout=30
            )

            response.raise_for_status()

            batch = response.json().get("data", [])

            if not batch:
                print(
                    f"Finished r/{subreddit}: "
                    f"{len(all_posts)} posts collected"
                )
                break

            added = 0

            for post in batch:
                post_id = post.get("id")

                if not post_id:
                    continue

                if post_id in seen_ids:
                    continue

                seen_ids.add(post_id)
                all_posts.append(post)
                added += 1

            print(
                f"r/{subreddit}: "
                f"{len(all_posts)} total "
                f"(+{added} new)"
            )

            # Move cursor forward using newest post
            last_post = batch[-1]

            if not last_post.get("created_utc"):
                break

            current_after = int(last_post["created_utc"]) + 1

            time.sleep(1)

        except Exception as e:
            print(f"Error fetching r/{subreddit}: {e}")
            break

    return all_posts[:max_posts]

def get_comments(post_id, limit=20, max_retries=4):
    params = {
        "link_id": post_id,
        "limit": limit,
        "start_depth": 10,    # allow deeper nesting
        "start_breadth": 10   # allow wider threads
    }
    for attempt in range(max_retries):
        try:
            res = requests.get(
                f"{BASE_URL}/comments/tree",
                params=params,
                headers=HEADERS,
                timeout=30
            )
            # Back off on rate limits instead of dropping the post.
            if res.status_code == 429:
                wait = float(res.headers.get("Retry-After", 2 ** attempt))
                print(f"  Rate limited on {post_id}, waiting {wait:.1f}s...")
                time.sleep(wait)
                continue
            res.raise_for_status()
            return res.json().get("data", [])
        except Exception as e:
            if attempt == max_retries - 1:
                print(f"  Error fetching comments for {post_id}: {e}")
                return []
            time.sleep(2 ** attempt)
    return []

# ─────────────────────────────────────────
# Comment parser
# ─────────────────────────────────────────

def parse_comment_tree(nodes, depth=10, counter=None, max_comments=20):
    if counter is None:
        counter = [0]
    result = []
    for node in nodes:
        if counter[0] >= max_comments:
            break
        if node.get("kind") == "more":
            continue
        c = node.get("data", {})
        author = c.get("author", "")
        body = c.get("body", "")

        if is_deleted(author) or is_deleted(body) or author == "AutoModerator":
            replies = c.get("replies")
            if replies and isinstance(replies, dict):
                children = replies.get("data", {}).get("children", [])
                result.extend(parse_comment_tree(children, depth, counter, max_comments))
            continue

        comment = {
            "comment_id": c.get("id"),
            "author": author,
            "body": body,
            "score": c.get("score", 0),
            "created_utc": c.get("created_utc"),
            "depth": depth,
            "replies": []
        }
        counter[0] += 1

        replies = c.get("replies")
        if replies and isinstance(replies, dict):
            children = replies.get("data", {}).get("children", [])
            comment["replies"] = parse_comment_tree(children, depth + 1, counter, max_comments)

        result.append(comment)
    return result

# ─────────────────────────────────────────
# Main scraper
# ─────────────────────────────────────────

def fetch_and_filter_subreddit(subreddit, after, before, min_comments, min_score):
    """Fetch one subreddit and apply all filters. Returns a list of valid posts.

    Designed to be run concurrently — it only reads shared module-level data
    and returns its own results, so it is safe across threads.
    """
    print(f"\n--- Scraping r/{subreddit} ---")
    raw_posts = get_posts(subreddit, after, before, max_posts=10000)
    print(f"  r/{subreddit} raw posts: {len(raw_posts)}")

    # Filter 0: deleted/removed
    raw_posts = [p for p in raw_posts if is_valid_post(p)]
    print(f"  r/{subreddit} after removing deleted: {len(raw_posts)}")

    # Filter 1: must be US-related
    us_filtered = []
    for p in raw_posts:
        is_us, us_matches = is_us_related(p)
        if is_us:
            p["_us_matches"] = us_matches
            us_filtered.append(p)
    print(f"  r/{subreddit} after US filter: {len(us_filtered)}")
    raw_posts = us_filtered

    # Filter 2: min comments
    raw_posts = [p for p in raw_posts if p.get("num_comments", 0) >= min_comments]

    # Filter 3: min score
    raw_posts = [p for p in raw_posts if p.get("score", 0) >= min_score]

    print(f"  r/{subreddit} after all filters: {len(raw_posts)} valid US immigration posts")

    raw_posts.sort(key=lambda x: x.get("num_comments", 0), reverse=True)
    return raw_posts


def scrape_immigration_posts(
    subreddits,
    comment_limit=20,
    min_comments=10,
    min_score=1,
    comment_workers=5
):
    after, before = get_date_range()
    all_posts = {}

    # Fetch every subreddit in parallel — one worker per subreddit.
    workers = len(subreddits)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                fetch_and_filter_subreddit,
                subreddit, after, before, min_comments, min_score
            ): subreddit
            for subreddit in subreddits
        }

        for future in as_completed(futures):
            subreddit = futures[future]
            try:
                posts = future.result()
            except Exception as e:
                print(f"Error scraping r/{subreddit}: {e}")
                continue

            # Merge into the shared dict on the main thread (de-dupe by id).
            for post in posts:
                post_id = post.get("id")
                if post_id not in all_posts:
                    all_posts[post_id] = post

    print(f"\nTotal unique posts: {len(all_posts)}")

   
    posts_list = sorted(all_posts.values(), key=lambda x: x.get("num_comments", 0), reverse=True)
    posts_list = posts_list
    total = len(posts_list)
    # Fetch comments concurrently, but cap workers to stay under rate limits.
    def build_record(post):
        post_id = post.get("id")
        subreddit = post.get("subreddit", "")
        raw_comments = get_comments(post_id, limit=comment_limit)
        comments = parse_comment_tree(raw_comments, max_comments=comment_limit)
        return {
            "post_id": post_id,
            "subreddit": subreddit,
            "title": post.get("title"),
            "body": post.get("selftext", ""),
            "author": post.get("author"),
            "score": post.get("score", 0),
            "url": f"https://reddit.com/r/{subreddit}/comments/{post_id}",
            "created_utc": post.get("created_utc"),
            "num_comments": post.get("num_comments", 0),
            "flair": post.get("link_flair_text"),
            "categories": post.get("_categories", []),
            "matched_keywords": post.get("_matched_keywords", []),
            "lawyer_keywords": post.get("_lawyer_keywords", []),
            "us_signals": post.get("_us_matches", []),
            "comments": comments,
            "comments_fetched": len(comments)
        }

    final_records = []
    done = 0
    with ThreadPoolExecutor(max_workers=comment_workers) as executor:
        futures = {executor.submit(build_record, post): post for post in posts_list}
        for future in as_completed(futures):
            done += 1
            post = futures[future]
            try:
                record = future.result()
            except Exception as e:
                print(f"  Error building record for {post.get('id')}: {e}")
                continue
            print(f"[{done}/{total}] fetched comments for {record['post_id']} "
                  f"({record['num_comments']} comments)")
            final_records.append(record)

    return final_records

# ─────────────────────────────────────────
# Run
# ─────────────────────────────────────────

def main():
    SUBREDDITS = [
        "immigration",
        "USCIS",
        "greencard",
        "h1b",
        "f1visa",
        "DACA",
    ]

    COMMENT_LIMIT = 50
    MIN_COMMENTS = 10
    MIN_SCORE = 1

    data = scrape_immigration_posts(
        SUBREDDITS,
        comment_limit=COMMENT_LIMIT,
        min_comments=MIN_COMMENTS,
        min_score=MIN_SCORE
    )

    with open("us_all_posts.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    # Summary
    total_comments = sum(p["comments_fetched"] for p in data)
    all_keywords = []
    for post in data:
        all_keywords.extend(post["matched_keywords"])

    print(f"\n{'='*40}")
    print(f"Total posts:         {len(data)}")
    print(f"Total comments:      {total_comments}")
    print(f"\nTop matched keywords:")
    for kw, count in Counter(all_keywords).most_common(10):
        print(f"  {kw}: {count}")

    print(f"\nFiles saved:")
    print(f"  us_all_posts.json")


if __name__ == "__main__":
    main()