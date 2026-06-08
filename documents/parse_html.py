"""Parse the HTML documents (Blogs and FAQs) into clean .txt files.

Walks documents/HTML/{Blogs,FAQs}, strips boilerplate (scripts, styles, nav,
headers, footers, ads, banners, etc.), keeps only readable text, and writes a
matching .txt file into documents/Text/{Blogs,FAQs}.
"""

from pathlib import Path
import re

from bs4 import BeautifulSoup, Comment

# Where the source HTML lives and where cleaned text should go.
SRC_ROOT = Path("documents/HTML")
OUT_ROOT = Path("documents/Text")
CATEGORIES = ["Blogs", "FAQs"]

# Tags whose content is never article text.
STRIP_TAGS = [
    "script", "style", "noscript", "template", "svg", "iframe", "form",
    "nav", "header", "footer", "aside", "button", "input", "select",
    "label", "link", "meta",
]

# Elements whose class/id hints at boilerplate (ads, banners, menus, social,
# cookie notices, related posts, comments, sidebars, etc.).
BOILERPLATE_RE = re.compile(
    r"(nav|menu|header|footer|sidebar|widget|banner|ad-|ads|advert|promo|"
    r"cookie|consent|popup|modal|social|share|subscribe|newsletter|breadcrumb|"
    r"related|comment|pagination|skip-link|search-form|sr-only|screen-reader)",
    re.IGNORECASE,
)


def clean_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")

    # Drop comments.
    for c in soup.find_all(string=lambda t: isinstance(t, Comment)):
        c.extract()

    # Drop non-content tags entirely.
    for el in soup(STRIP_TAGS):
        el.decompose()

    # Drop elements flagged as boilerplate by class or id. Never remove the
    # structural wrappers themselves (their classes often contain words like
    # "menu" without being boilerplate).
    structural = {"html", "body", "article", "main"}
    for attr in ("class", "id"):
        for el in soup.find_all(attrs={attr: BOILERPLATE_RE}):
            if el.name not in structural:
                el.decompose()

    # Prefer the main article container if the page provides one.
    root = soup.find("article") or soup.find("main") or soup.body or soup

    text = root.get_text(separator="\n")

    # Collapse whitespace: trim lines, drop blanks, squeeze blank runs.
    lines = [ln.strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln]
    return "\n".join(lines)


def main() -> None:
    total = 0
    for category in CATEGORIES:
        src_dir = SRC_ROOT / category
        out_dir = OUT_ROOT / category
        if not src_dir.is_dir():
            print(f"skip: {src_dir} not found")
            continue
        out_dir.mkdir(parents=True, exist_ok=True)

        for html_file in sorted(src_dir.glob("*.html")):
            raw = html_file.read_text(encoding="utf-8", errors="ignore")
            text = clean_html(raw)
            out_file = out_dir / (html_file.stem + ".txt")
            out_file.write_text(text, encoding="utf-8")
            print(f"{html_file.name} -> {out_file}  ({len(text)} chars)")
            total += 1
    print(f"\nDone. Wrote {total} text files under {OUT_ROOT}/")


if __name__ == "__main__":
    main()
