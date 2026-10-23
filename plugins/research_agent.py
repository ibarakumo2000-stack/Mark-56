"""
research_agent.py — JARVIS plugin

"Jarvis, find 10 luxury shoe brands in Nigeria and analyze their pricing" —
runs several targeted web searches, reads the top results, and uses Gemini
to synthesize a structured comparison: what was found, how the items differ,
what patterns/outliers show up, and what data couldn't be confidently found
(rather than inventing numbers to fill gaps).

Deeper/broader than the existing `web_search` tool — that's for a quick
single lookup; this is for open-ended comparative/analytical research
across multiple sources. Use web_search instead for "what's the weather"
or "who won the game" style single-fact questions.

TRACKING: pass track=true with a topic and JARVIS saves a structured
snapshot. Ask again later with the same topic (track=true) and it diffs
against the last snapshot — new items, removed items, changed values —
so it can report "abnormalities" / what's changed / new updates over time.

Drop this file into /plugins/ — no other file needs to change.
"""

import re
import json
from pathlib import Path
from datetime import datetime

PLUGIN = {
    "name": "research_agent",
    "description": (
        "Performs deep, multi-source research: runs several targeted web "
        "searches, reads top results, and uses AI to synthesize a structured "
        "comparison — highlighting differences, patterns, trends, and "
        "outliers/anomalies in the data, and flagging what it genuinely "
        "couldn't confirm rather than guessing. Use for open-ended "
        "comparative or analytical requests ('find and compare X', "
        "'research Y and analyze Z', 'what are the differences between...'). "
        "Do NOT use for a quick single-fact lookup ('what's the weather', "
        "'who won the game') — use web_search for those instead. Can also "
        "TRACK a topic over time (track=true): saves a snapshot, and the "
        "next tracked call on the same topic reports what's changed since — "
        "new items, removed items, or changed values — as well as spotting "
        "abnormalities/updates."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "query": {
                "type": "STRING",
                "description": "The research request, as close to verbatim as "
                                "possible, e.g. '10 luxury shoe brands in "
                                "Nigeria and their pricing'.",
            },
            "num_items": {
                "type": "INTEGER",
                "description": "How many items/entities to find, if the "
                                "request implies a count (e.g. 10). Defaults "
                                "to 8 if not specified.",
            },
            "track": {
                "type": "BOOLEAN",
                "description": "If true, save this as a tracked snapshot and "
                                "diff against the last one for the same topic "
                                "(reports new/removed/changed items). Use when "
                                "the user says 'track', 'monitor', 'keep an "
                                "eye on', or 'check for updates on' something.",
            },
            "track_label": {
                "type": "STRING",
                "description": "Optional short label identifying the tracked "
                                "topic, so future track calls on the same "
                                "subject match up. Defaults to a slug of the query.",
            },
        },
        "required": ["query"],
    },
}

BASE_DIR = Path(__file__).resolve().parent.parent
REPORTS_DIR = Path.home() / "Desktop" / "JarvisResearch"
SNAPSHOTS_DIR = BASE_DIR / "data" / "research_tracking"

_MAX_QUERIES = 6
_RESULTS_PER_QUERY = 5
_MAX_PAGES_TO_FETCH = 5
_PAGE_EXCERPT_CHARS = 1500
_FETCH_TIMEOUT = 8


# ─────────────────────────── Gemini access ──────────────────────────────

def _get_api_key() -> str:
    from memory.config_manager import get_gemini_key
    key = get_gemini_key()
    if not key:
        raise ValueError("no Gemini API key configured")
    return key


def _ask_gemini(prompt: str) -> str:
    from google import genai
    client = genai.Client(api_key=_get_api_key())
    response = client.models.generate_content(model="gemini-flash-latest", contents=prompt)
    text = getattr(response, "text", None)
    if not text and getattr(response, "candidates", None):
        parts = response.candidates[0].content.parts
        text = "".join(getattr(p, "text", "") or "" for p in parts)
    text = (text or "").strip()
    if not text:
        raise ValueError("Gemini returned an empty response.")
    return text


# ─────────────────────────── web search / fetch ─────────────────────────

def _get_ddgs():
    try:
        from ddgs import DDGS
        return DDGS
    except ImportError:
        from duckduckgo_search import DDGS
        return DDGS


def _ddg_search(query: str, max_results: int = _RESULTS_PER_QUERY) -> list:
    DDGS = _get_ddgs()
    results = []
    try:
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                results.append({
                    "title": r.get("title", ""),
                    "snippet": r.get("body", ""),
                    "url": r.get("href", ""),
                })
    except Exception:
        pass
    return results


def _fetch_page_excerpt(url: str) -> str:
    import requests
    from bs4 import BeautifulSoup
    try:
        resp = requests.get(url, timeout=_FETCH_TIMEOUT,
                             headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = " ".join(soup.get_text(separator=" ").split())
        return text[:_PAGE_EXCERPT_CHARS]
    except Exception:
        return ""


def _plan_search_queries(query: str, num_items: int) -> list:
    prompt = (
        f"A user wants this researched: \"{query}\" (looking for around "
        f"{num_items} items/entities if that applies). Propose up to "
        f"{_MAX_QUERIES} concrete, varied web search queries that would "
        f"together gather good source material for this — different angles "
        f"(e.g. listicles, review sites, official/pricing sources, recent "
        f"news). Respond with ONLY a JSON array of strings, nothing else. "
        f"Example: [\"query one\", \"query two\"]"
    )
    try:
        text = _ask_gemini(prompt)
        match = re.search(r"\[.*\]", text, re.S)
        if match:
            queries = json.loads(match.group(0))
            queries = [q for q in queries if isinstance(q, str) and q.strip()][:_MAX_QUERIES]
            if queries:
                return queries
    except Exception:
        pass
    return [query]  # graceful fallback — just search the raw query


# ─────────────────────────── synthesis ──────────────────────────────────

def _build_synthesis_prompt(query: str, num_items: int, gathered_text: str) -> str:
    return f"""You are a careful research analyst. The user asked: "{query}"
(roughly {num_items} items/entities, if that applies to the request).

Below is raw material gathered from multiple web searches (titles, snippets,
and excerpts from top pages). Use ONLY this material — do not invent specific
numbers, prices, or facts that aren't supported by it. If something relevant
isn't confidently found in the material, say so explicitly rather than
guessing.

--- GATHERED MATERIAL ---
{gathered_text}
--- END MATERIAL ---

Respond in EXACTLY this structure, with these exact fenced block labels,
nothing before the first block or after the last:

```json
[{{"name": "...", "key_facts": {{"attribute": "value, or 'not found'"}}}}, ...]
```

```summary
2-4 plain spoken sentences: the single most useful takeaway, and any
standout pattern or outlier. No markdown formatting in this block.
```

```report
Full markdown report:
1. A comparison table of the items found (or a clear list if a table
   doesn't fit the data) with the relevant attributes for "{query}".
2. A "## Patterns & Differences" section: trends, clusters, and any
   outliers/anomalies (e.g. one item priced far outside the rest).
3. A "## Data Gaps" section: anything relevant that couldn't be
   confidently confirmed from the material.
```"""


def _parse_blocks(text: str):
    def _extract(label):
        m = re.search(rf"```{label}\s*(.*?)```", text, re.S)
        return m.group(1).strip() if m else ""

    json_block = _extract("json")
    summary_block = _extract("summary")
    report_block = _extract("report")

    structured = []
    if json_block:
        try:
            structured = json.loads(json_block)
        except Exception:
            structured = []

    return structured, summary_block, report_block


# ─────────────────────────── tracking / diffing ─────────────────────────

def _slugify(text: str) -> str:
    keep = [c if c.isalnum() else "_" for c in text.strip().lower()]
    slug = "".join(keep)
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug.strip("_")[:50] or "topic"


def _diff_snapshots(old_items: list, new_items: list) -> str:
    old_by_name = {i.get("name", ""): i.get("key_facts", {}) for i in old_items if i.get("name")}
    new_by_name = {i.get("name", ""): i.get("key_facts", {}) for i in new_items if i.get("name")}

    added = [n for n in new_by_name if n not in old_by_name]
    removed = [n for n in old_by_name if n not in new_by_name]
    changed = []
    for name in set(old_by_name) & set(new_by_name):
        old_facts, new_facts = old_by_name[name], new_by_name[name]
        for key in set(old_facts) | set(new_facts):
            ov, nv = old_facts.get(key), new_facts.get(key)
            if ov != nv and nv not in (None, "", "not found"):
                changed.append(f"{name}: {key} changed from '{ov}' to '{nv}'")

    if not added and not removed and not changed:
        return "No changes detected since the last check."

    parts = []
    if added:
        parts.append("New: " + ", ".join(added))
    if removed:
        parts.append("No longer appearing: " + ", ".join(removed))
    if changed:
        parts.append("Changed — " + "; ".join(changed))
    return " | ".join(parts)


def _load_snapshot(slug: str):
    path = SNAPSHOTS_DIR / f"{slug}.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _save_snapshot(slug: str, items: list, query: str):
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    path = SNAPSHOTS_DIR / f"{slug}.json"
    path.write_text(json.dumps({
        "query": query,
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "items": items,
    }, indent=2), encoding="utf-8")


# ─────────────────────────── main entry point ────────────────────────────

def run(parameters: dict, player=None, session_memory=None) -> str:
    query = (parameters.get("query") or "").strip()
    try:
        num_items = int(parameters.get("num_items") or 8)
    except (TypeError, ValueError):
        num_items = 8
    track = bool(parameters.get("track", False))
    track_label = (parameters.get("track_label") or "").strip()

    if not query:
        return "Sir, what would you like me to research?"

    try:
        api_key_ok = True
        _get_api_key()
    except Exception as e:
        return f"Sir, I can't run research without a Gemini API key configured: {e}"

    try:
        search_queries = _plan_search_queries(query, num_items)

        seen_urls = set()
        all_results = []
        for q in search_queries:
            for r in _ddg_search(q):
                if r["url"] and r["url"] not in seen_urls:
                    seen_urls.add(r["url"])
                    all_results.append(r)

        if not all_results:
            return f"Sir, I couldn't find any web results for '{query}' — the search may have failed or returned nothing."

        gathered_parts = []
        for r in all_results:
            gathered_parts.append(f"- {r['title']} ({r['url']}): {r['snippet']}")

        for r in all_results[:_MAX_PAGES_TO_FETCH]:
            excerpt = _fetch_page_excerpt(r["url"])
            if excerpt:
                gathered_parts.append(f"\n[Excerpt from {r['url']}]\n{excerpt}")

        gathered_text = "\n".join(gathered_parts)

        synthesis_prompt = _build_synthesis_prompt(query, num_items, gathered_text)
        raw_response = _ask_gemini(synthesis_prompt)
        structured, summary, report = _parse_blocks(raw_response)

        if not report:
            report = raw_response  # fallback: block parsing failed, use raw text as-is
        if not summary:
            summary = report[:400]

        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = REPORTS_DIR / f"{_slugify(query)}_{stamp}.md"
        report_path.write_text(f"# Research: {query}\n\n{report}\n", encoding="utf-8")

        result_text = f"{summary} Full report saved to {report_path}."

        if track:
            slug = _slugify(track_label) if track_label else _slugify(query)
            previous = _load_snapshot(slug)
            if structured:
                if previous is None:
                    result_text += " (Baseline saved for tracking — I'll report changes next time you check this.)"
                else:
                    diff_summary = _diff_snapshots(previous.get("items", []), structured)
                    result_text += f" Since last check: {diff_summary}"
                _save_snapshot(slug, structured, query)
            else:
                result_text += " (Couldn't extract structured data for tracking this time — nothing saved.)"

    except Exception as e:
        return f"Sir, research_agent failed: {e}"

    if player:
        try:
            player.write_log(f"JARVIS: {result_text}")
        except Exception:
            pass

    return result_text
