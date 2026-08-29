"""Seed the skill market with demo data (for dev/testing).

Usage:
    MHC_MARKET_DATA=/tmp/mhc-market-dev MHC_MARKET_SECRET=dev-secret \
        uv run python scripts/seed_market.py

Idempotent-ish: re-running overwrites the demo skills' content and
re-flags featured, and re-adds the demo stories. Use --data/--secret
to override env.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
import zipfile
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "mhc-market-backend" / "src")
)

from mhc_market_backend.store import MarketStore

# slug, display_name, category, featured, author, description, icon
SKILLS = [
    ("daily-standup-notes", "Daily Standup Notes", "office", True, "alice",
     "Turn messy bullet points into a crisp standup update: done / doing / blocked.", "📝"),
    ("code-review-checklist", "Code Review Checklist", "coding", True, "alice",
     "Review any diff for correctness, security, and readability with a fixed checklist.", "🔍"),
    ("weekly-report", "Weekly Report Writer", "office", False, "alice",
     "Summarize a week of commits and notes into a stakeholder-friendly report.", "📊"),
    ("git-commit-pro", "Git Commit Pro", "coding", False, "bob",
     "Write conventional commits (feat/fix/…) with scope and a clean body.", "🌿"),
    ("email-polisher", "Email Polisher", "writing", False, "bob",
     "Rewrite drafts to be shorter, politer, and clearer — keeps your tone.", "✉️"),
    ("sql-explainer", "SQL Explainer", "coding", False, "bob",
     "Explain a SQL query line by line, flag full scans and missing indexes.", "🗄️"),
    ("meeting-agenda", "Meeting Agenda Builder", "efficiency", False, "demo",
     "Turn a topic into a timed agenda with owners and expected outcomes.", "📅"),
    ("blog-outline", "Blog Outline Sketcher", "writing", False, "demo",
     "Outline a blog post: hook, sections, takeaways, CTA.", "✍️"),
]

# author, display_name, title, content
STORIES = [
    ("alice", "Daily Standup Notes", "我怎么用每日站会笔记技能把 5 分钟开完",
     """## 背景

我们团队每天早上站会，每个人 1 分钟。以前我总是一边翻 Jira 一边想昨天干了啥，经常超时。

## 我怎么用

添加 **daily-standup-notes** 到我的技能后，我把昨天的提交记录和随手记的要点直接贴给助手，它按「昨天完成 / 今天计划 / 阻塞」三段式输出，直接念就行。

## 效果

- 站会发言从 3 分钟压到 40 秒
- 阻塞项再也没漏过

强烈推荐给任何被站会折磨的人。
"""),
    ("bob", "SQL Explainer", "接手祖传 SQL 全靠它",
     """## 祖传代码救星

前任同事留下一个 300 行的 SQL，没人敢动。我把 **sql-explainer** 添加到我的技能，把查询贴进去。

它逐段解释了每个 CTE 在干什么，还标出了两个隐式笛卡尔积和一个缺索引的全表扫描。

## 建议

配合你自己的 schema 文件一起贴进去，解释会更准。
"""),
]


def skill_zip_body(name: str, display: str, description: str, icon: str) -> str:
    icon_line = f"\nicon: {icon}" if icon else ""
    # Description must be quoted — free text often contains colons,
    # and unquoted colons break YAML frontmatter parsing.
    safe_desc = json.dumps(description, ensure_ascii=False)
    return (
        f"---\nname: {name}\ndescription: {safe_desc}{icon_line}\n---\n\n"
        f"# {display}\n\n"
        "This is demo content seeded by `scripts/seed_market.py`. "
        f"Act as a helpful assistant specialized in **{display}**.\n\n"
        "## How to use\n\n"
        f"1. Paste your {display.lower()} material.\n"
        "2. The assistant rewrites/organizes it following best practices.\n"
    )


def skill_zip(name: str, display: str, description: str, icon: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            f"{name}/SKILL.md", skill_zip_body(name, display, description, icon)
        )
    return buf.getvalue()


def _sha(name: str, display: str, description: str, icon: str) -> str:
    """Same algorithm as SkillStore.content_sha: sha256 over each
    file's relative path + bytes (relative to the skill dir, i.e.
    'SKILL.md', not slug-prefixed)."""
    h = hashlib.sha256()
    h.update(b"SKILL.md")
    h.update(b"\0")
    h.update(skill_zip_body(name, display, description, icon).encode("utf-8"))
    h.update(b"\0")
    return h.hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.environ.get("MHC_MARKET_DATA", ""))
    ap.add_argument("--secret", default=os.environ.get("MHC_MARKET_SECRET", ""))
    args = ap.parse_args()
    if not args.data or not args.secret:
        ap.error("--data/--secret or MHC_MARKET_DATA/MHC_MARKET_SECRET required")

    store = MarketStore(Path(args.data))
    skill_key: dict[str, str] = {}  # display_name -> market key
    for slug, display, category, featured, author, description, icon in SKILLS:
        meta = store.publish(
            slug=slug,
            user=author,
            zip_bytes=skill_zip(slug, display, description, icon),
            sha=_sha(slug, display, description, icon),
            display_name=display,
            description=description,
            category=category,
            icon=icon,
        )
        skill_key[display] = meta["slug"]
        if featured:
            store.set_featured(meta["slug"], True)
        print(f"seeded {meta['slug']} (author={author}, featured={featured})")
    for author, slug, title, content in STORIES:
        key = skill_key[slug]  # STORIES reference display names now
        store.add_story(user=author, title=title, skill_slug=key, content=content)
        print(f"seeded story by {author}: {title}")
    print(f"done: {len(SKILLS)} skills, {len(STORIES)} stories in {args.data}")


if __name__ == "__main__":
    main()
