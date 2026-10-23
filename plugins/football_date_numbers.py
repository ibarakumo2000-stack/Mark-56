"""
football_date_numbers.py — JARVIS plugin

Tracks football matches by date and computes a digit-reduced "numerology"
value for each date component:
  MOP = Month of Play, digit-root of the month number
  DOP = Day of Play, digit-root of the day number
  YOP = Year of Play, digit-root of the year number
  SDOP = "next day" figure — digit-root of (day + 1)

Digit-root ("plus all the numbers until one digit remains") — e.g. 2026 ->
2+0+2+6=10 -> 1+0=1. Matches the MOP-10 -> 1 example given.

"Tomorrow" is computed from a REAL calendar date (via datetime), so month/
year rollovers (e.g. Dec 31 -> Jan 1) are handled correctly — not a blind
+1 on the day number alone.

All data is saved to disk per date and persists across sessions. Matches can
later have a result recorded (update_result) — needed for any real pattern
tracking between the computed numbers and actual outcomes, since there's
nothing to find a pattern in without a result to compare against.

If the data file is ever found corrupted, it is backed up (never silently
discarded/overwritten) and the response says so plainly.

ASSUMPTION, worth confirming: SDOP applies the same digit-root reduction to
(day + 1) as every other field, for consistency — correct this if SDOP was
meant to stay as a raw, unreduced number.

Drop this file into /plugins/ — no other file needs to change.
"""

import json
import re
from pathlib import Path
from datetime import date, timedelta

PLUGIN = {
    "name": "football_date_numbers",
    "description": (
        "Tracks football matches by date and computes digit-reduced date "
        "numbers for each: MOP (month), DOP (day), YOP (year), and SDOP "
        "(next day's digit-root). Can store a match for a date, record its "
        "result afterward (needed for any pattern tracking against the "
        "numbers), retrieve a date's stored matches/results/numbers, compute "
        "'tomorrow' automatically (real calendar rollover, not a blind +1), "
        "and combine fields on request (e.g. 'YOP plus DOP'). Use for 'add "
        "this match', 'the result was X', 'what are the numbers for "
        "today/tomorrow', 'YOP plus DOP for [date]', 'show me everything stored'."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "enum": ["add_match", "update_result", "get_day", "calculate", "list_days"],
                "description": "add_match: store a match for a date (before it's "
                                "played — no result yet). update_result: record "
                                "the outcome of an already-stored match, needed "
                                "for any real pattern tracking against the "
                                "numbers. get_day: retrieve a date's matches + "
                                "numbers. calculate: combine two or more fields "
                                "(MOP/DOP/YOP/SDOP) for a date. "
                                "list_days: list every stored date.",
            },
            "date": {
                "type": "STRING",
                "description": "A date as YYYY-MM-DD, or literally 'today' or "
                                "'tomorrow'. Defaults to 'today' if omitted.",
            },
            "team_a": {"type": "STRING", "description": "First team (for add_match/update_result)."},
            "team_b": {"type": "STRING", "description": "Second team (for add_match/update_result)."},
            "result": {
                "type": "STRING",
                "description": "The match outcome, e.g. '2-1' or 'Arsenal win' "
                                "or 'draw' (for update_result). Free text.",
            },
            "fields": {
                "type": "ARRAY",
                "description": "Which fields to combine, e.g. ['YOP','DOP'] "
                                "(for action=calculate). At least 2 needed.",
                "items": {"type": "STRING", "enum": ["MOP", "DOP", "YOP", "SDOP"]},
            },
        },
        "required": ["action"],
    },
}

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_PATH = BASE_DIR / "data" / "football_date_numbers.json"


def digit_root(n: int) -> int:
    """Repeatedly sums digits until one digit remains. 0 -> 0."""
    n = abs(int(n))
    if n == 0:
        return 0
    while n >= 10:
        n = sum(int(d) for d in str(n))
    return n


def compute_fields(d: date) -> dict:
    return {
        "MOP": digit_root(d.month),
        "DOP": digit_root(d.day),
        "YOP": digit_root(d.year),
        "SDOP": digit_root(d.day + 1),
    }


def _resolve_date(date_str: str) -> date:
    text = (date_str or "today").strip().lower()
    if text in ("", "today"):
        return date.today()
    if text == "tomorrow":
        return date.today() + timedelta(days=1)
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str.strip()):
        raise ValueError(f"'{date_str}' isn't a date I understand — use YYYY-MM-DD, 'today', or 'tomorrow'.")
    try:
        y, m, dd = (int(p) for p in date_str.strip().split("-"))
        return date(y, m, dd)
    except ValueError:
        raise ValueError(f"'{date_str}' isn't a real calendar date.")


def _load_store():
    """Returns (store, recovery_note). recovery_note is '' unless a corrupted
    file was found and backed up — never silently discards existing data."""
    if not DATA_PATH.is_file():
        return {}, ""
    try:
        return json.loads(DATA_PATH.read_text(encoding="utf-8")), ""
    except Exception:
        backup_path = DATA_PATH.with_suffix(f".corrupted-{int(__import__('time').time())}.json")
        try:
            DATA_PATH.rename(backup_path)
            note = (f" (Note: the data file was corrupted and has been backed up to "
                     f"{backup_path.name} rather than discarded — past data may be "
                     f"recoverable from it; starting fresh from here.)")
        except Exception:
            note = " (Note: the data file was corrupted and unreadable.)"
        return {}, note


def _save_store(store: dict):
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    DATA_PATH.write_text(json.dumps(store, indent=2), encoding="utf-8")


def _get_or_create_entry(store: dict, d: date) -> dict:
    key = d.isoformat()
    if key not in store:
        store[key] = {"date": key, **compute_fields(d), "matches": []}
    return store[key]


def _format_match(m: dict) -> str:
    base = f"{m['team_a']} vs {m['team_b']}"
    if m.get("result"):
        base += f" (result: {m['result']})"
    return base


def run(parameters: dict, player=None, session_memory=None) -> str:
    action = (parameters.get("action") or "").strip().lower()
    date_str = (parameters.get("date") or "today").strip()
    team_a = (parameters.get("team_a") or "").strip()
    team_b = (parameters.get("team_b") or "").strip()
    result_val = (parameters.get("result") or "").strip()
    fields_raw = parameters.get("fields") or []

    if action not in ("add_match", "update_result", "get_day", "calculate", "list_days"):
        return "Sir, tell me add_match, update_result, get_day, calculate, or list_days."

    try:
        store, recovery_note = _load_store()

        if action == "add_match":
            if not team_a or not team_b:
                return "Sir, I need both team names to add a match."
            d = _resolve_date(date_str)
            entry = _get_or_create_entry(store, d)
            entry["matches"].append({"team_a": team_a, "team_b": team_b, "result": None})
            _save_store(store)
            result_text = (f"Saved {team_a} vs {team_b} for {d.isoformat()}. "
                            f"MOP={entry['MOP']}, DOP={entry['DOP']}, "
                            f"YOP={entry['YOP']}, SDOP={entry['SDOP']}.")

        elif action == "update_result":
            if not team_a or not team_b or not result_val:
                return "Sir, I need both team names and the result to update."
            d = _resolve_date(date_str)
            entry = store.get(d.isoformat())
            match = None
            if entry:
                for m in entry["matches"]:
                    if m["team_a"] == team_a and m["team_b"] == team_b:
                        match = m
                        break
            if match is None:
                return f"Sir, I don't have {team_a} vs {team_b} stored for {d.isoformat()} — add it first."
            match["result"] = result_val
            _save_store(store)
            result_text = f"Updated {team_a} vs {team_b} on {d.isoformat()} with result: {result_val}."

        elif action == "get_day":
            d = _resolve_date(date_str)
            entry = store.get(d.isoformat())
            if entry is None:
                fields_now = compute_fields(d)
                result_text = (f"No matches stored for {d.isoformat()} yet, but the numbers are: "
                                f"MOP={fields_now['MOP']}, DOP={fields_now['DOP']}, "
                                f"YOP={fields_now['YOP']}, SDOP={fields_now['SDOP']}.")
            else:
                matches = entry["matches"]
                match_list = "; ".join(_format_match(m) for m in matches) or "none stored"
                result_text = (f"{d.isoformat()}: MOP={entry['MOP']}, DOP={entry['DOP']}, "
                                f"YOP={entry['YOP']}, SDOP={entry['SDOP']}. Matches: {match_list}.")

        elif action == "calculate":
            requested = [f.strip().upper() for f in fields_raw if f.strip()]
            valid_fields = [f for f in requested if f in ("MOP", "DOP", "YOP", "SDOP")]
            ignored = [f for f in requested if f not in ("MOP", "DOP", "YOP", "SDOP")]
            if len(valid_fields) < 2:
                return "Sir, give me at least two valid fields to combine, e.g. YOP and DOP."
            d = _resolve_date(date_str)
            computed = compute_fields(d)
            values = [computed[f] for f in valid_fields]
            raw_sum = sum(values)
            reduced = digit_root(raw_sum)
            breakdown = " + ".join(f"{f}({computed[f]})" for f in valid_fields)
            result_text = (f"For {d.isoformat()}: {breakdown} = {raw_sum}, "
                            f"which reduces to {reduced}.")
            if ignored:
                result_text += f" (Ignored unrecognized field(s): {', '.join(ignored)}.)"

        elif action == "list_days":
            if not store:
                return "Sir, nothing's been stored yet." + recovery_note
            lines = []
            for key in sorted(store.keys()):
                e = store[key]
                n_matches = len(e["matches"])
                n_with_results = sum(1 for m in e["matches"] if m.get("result"))
                lines.append(f"{key} ({n_matches} match{'es' if n_matches != 1 else ''}, "
                              f"{n_with_results} with a result recorded)")
            result_text = "Stored dates: " + "; ".join(lines)

        result_text += recovery_note

    except ValueError as e:
        return f"Sir, {e}"
    except Exception as e:
        return f"Sir, football_date_numbers failed: {e}"

    if player:
        try:
            player.write_log(f"JARVIS: {result_text}")
        except Exception:
            pass

    return result_text
