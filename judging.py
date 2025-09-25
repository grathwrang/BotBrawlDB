import time
import uuid
from typing import Dict, Tuple, Any, List, Optional
from storage import load_all

CATEGORY_SPECS = [
    {"key": "damage", "label": "Damage", "max": 8},
    {"key": "aggression", "label": "Aggression", "max": 5},
    {"key": "control", "label": "Control", "max": 6},
]
CATEGORY_KEYS = [spec["key"] for spec in CATEGORY_SPECS]
JUDGE_COUNT = 3


def default_state() -> Dict[str, Any]:
    return {"current": None, "history": []}


def create_match_record(card: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "match_id": uuid.uuid4().hex,
        "weight_class": card.get("weight_class"),
        "red": card.get("red"),
        "white": card.get("white"),
        "created_at": int(time.time()),
        "judges": {},
    }


def sanitize_slider_values(raw: Dict[str, Any]) -> Dict[str, int]:
    sanitized: Dict[str, int] = {}
    for spec in CATEGORY_SPECS:
        key = spec["key"]
        max_val = spec["max"]
        val = raw.get(key, max_val // 2)
        try:
            val_int = int(val)
        except (TypeError, ValueError):
            val_int = max_val // 2
        if val_int < 0:
            val_int = 0
        if val_int > max_val:
            val_int = max_val
        sanitized[key] = val_int
    return sanitized


def create_judge_record(
    judge_id: int,
    sliders: Dict[str, Any],
    judge_name: Optional[str] = None,
    submitted_at: Optional[int] = None,
) -> Dict[str, Any]:
    sanitized = sanitize_slider_values(sliders)
    scores: Dict[str, Dict[str, Any]] = {}
    totals = {"red": 0, "white": 0}
    breakdown_parts: List[str] = []
    name_value = (judge_name or "").strip()
    for spec in CATEGORY_SPECS:
        key = spec["key"]
        max_val = spec["max"]
        red_points = sanitized[key]
        white_points = max_val - red_points
        scores[key] = {
            "label": spec["label"],
            "max": max_val,
            "red": red_points,
            "white": white_points,
        }
        totals["red"] += red_points
        totals["white"] += white_points
        breakdown_parts.append(f"{spec['label']} {red_points}-{white_points}")
    if totals["red"] > totals["white"]:
        winner = "red"
    elif totals["white"] > totals["red"]:
        winner = "white"
    else:
        winner = "draw"
    record = {
        "judge_id": int(judge_id),
        "submitted_at": int(submitted_at if submitted_at is not None else time.time()),
        "judge_name": name_value,
        "sliders": sanitized,
        "scores": scores,
        "totals": totals,
        "winner": winner,
        "scoreline": f"{totals['red']}-{totals['white']}",
        "breakdown": " \u00b7 ".join(breakdown_parts),
    }
    return record


def _normalize_judge_record(record: Dict[str, Any], judge_id: int) -> Tuple[Dict[str, Any], bool]:
    rec = dict(record or {})
    rec["judge_id"] = int(rec.get("judge_id", judge_id) or judge_id)
    sliders = rec.get("sliders") or {}
    submitted_at = rec.get("submitted_at")
    normalized = create_judge_record(
        rec["judge_id"],
        sliders,
        judge_name=rec.get("judge_name"),
        submitted_at=submitted_at,
    )
    changed = normalized != record
    return normalized, changed


def _norm_text(value: Any) -> str:
    return (value or "").strip().casefold()


def matches_card(match: Dict[str, Any], card: Dict[str, Any]) -> bool:
    if not match or not card:
        return False
    return (
        _norm_text(match.get("weight_class")) == _norm_text(card.get("weight_class"))
        and _norm_text(match.get("red")) == _norm_text(card.get("red"))
        and _norm_text(match.get("white")) == _norm_text(card.get("white"))
    )


def normalize_match(match: Optional[Dict[str, Any]], judge_count: int = JUDGE_COUNT) -> Tuple[Optional[Dict[str, Any]], bool]:
    if not match:
        return None, False
    changed = False
    normalized = dict(match)
    if not normalized.get("match_id"):
        normalized["match_id"] = uuid.uuid4().hex
        changed = True
    judges = normalized.get("judges") or {}
    cleaned: Dict[str, Dict[str, Any]] = {}
    for idx in range(1, judge_count + 1):
        key = str(idx)
        rec = judges.get(key)
        if rec is None and idx in judges:
            rec = judges[idx]
        if rec is not None:
            normalized_rec, rec_changed = _normalize_judge_record(rec, idx)
            cleaned[key] = normalized_rec
            if rec_changed:
                changed = True
    for key, rec in judges.items():
        key_str = str(key)
        if key_str not in cleaned:
            jid = int(key) if str(key).isdigit() else judge_count + 1
            normalized_rec, rec_changed = _normalize_judge_record(rec, jid)
            cleaned[key_str] = normalized_rec
            if rec_changed:
                changed = True
    if cleaned != judges:
        normalized["judges"] = cleaned
        changed = True
    summary = compute_match_summary(normalized, judge_count=judge_count)
    if normalized.get("summary") != summary:
        normalized["summary"] = summary
        changed = True
    return normalized, changed


def compute_match_summary(match: Dict[str, Any], judge_count: int = JUDGE_COUNT) -> Dict[str, Any]:
    judges = match.get("judges") or {}
    ordered: List[Dict[str, Any]] = []
    counts = {"red": 0, "white": 0, "draw": 0}
    pending: List[int] = []
    for idx in range(1, judge_count + 1):
        rec = judges.get(str(idx))
        if rec is not None:
            rec_copy = dict(rec)
            rec_copy["judge_id"] = int(rec_copy.get("judge_id", idx) or idx)
            ordered.append(rec_copy)
            counts[rec_copy.get("winner", "draw")] = counts.get(rec_copy.get("winner", "draw"), 0) + 1
        else:
            pending.append(idx)
    ordered.sort(key=lambda r: r.get("judge_id", 0))
    is_complete = len(ordered) == judge_count and judge_count > 0
    if counts["red"] > counts["white"]:
        final = "red"
    elif counts["white"] > counts["red"]:
        final = "white"
    else:
        final = "draw"
    winner_name = None
    decision = "draw"
    red_name = match.get("red", "Red")
    white_name = match.get("white", "White")
    if final != "draw":
        winner_name = red_name if final == "red" else white_name
        if is_complete and counts[final] == judge_count:
            decision = "unanimous decision"
        elif is_complete and counts[final] + counts["draw"] == judge_count and counts["draw"] > 0:
            decision = "majority decision"
        elif is_complete:
            decision = "split decision"
        else:
            decision = "decision"
    scorecard_strings: List[str] = []
    for rec in ordered:
        rec["winner_name"] = red_name if rec.get("winner") == "red" else white_name if rec.get("winner") == "white" else None
        scorecard_strings.append(
            f"Judge {rec.get('judge_id')}: {red_name} {rec.get('totals', {}).get('red', 0)}-"
            f"{rec.get('totals', {}).get('white', 0)} {white_name}"
        )
    if is_complete and ordered:
        base = "Draw" if final == "draw" else f"{winner_name} wins via {decision}"
        cards_text = " · ".join(scorecard_strings)
        headline = base + (f" — {cards_text}" if cards_text else "")
    else:
        if ordered:
            have_text = " · ".join(scorecard_strings)
            headline = "Waiting for judges scores..."
            if have_text:
                headline += f" (have: {have_text})"
        else:
            headline = "Waiting for judges scores..."
        if pending:
            headline += f" — Pending Judge{'s' if len(pending) > 1 else ''} {', '.join(str(p) for p in pending)}"
    return {
        "counts": counts,
        "winner": final,
        "winner_name": winner_name,
        "decision": decision,
        "scorecard_strings": scorecard_strings,
        "pending_judges": pending,
        "is_complete": is_complete,
        "judge_cards": ordered,
        "headline": headline,
    }


def build_match_payload(match: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not match:
        return None
    summary = match.get("summary") or compute_match_summary(match)
    return {
        "match_id": match.get("match_id"),
        "weight_class": match.get("weight_class"),
        "red": match.get("red"),
        "white": match.get("white"),
        "created_at": match.get("created_at"),
        "completed_at": match.get("completed_at"),
        "judges": summary.get("judge_cards", []),
        "pending_judges": summary.get("pending_judges", []),
        "is_complete": summary.get("is_complete", False),
        "headline": summary.get("headline", ""),
        "winner": summary.get("winner"),
        "winner_name": summary.get("winner_name"),
        "decision": summary.get("decision"),
        "scorecard_strings": summary.get("scorecard_strings", []),
        "counts": summary.get("counts", {}),
    }


def build_state_payload(state: Dict[str, Any], history_limit: Optional[int] = None) -> Dict[str, Any]:
    """Build the payload for judge panels.

    Augmentation: include recent KO fights (entered via Elo submission) so that
    they appear in the unified results list even if they never went through the
    judging subsystem. We synthesize a minimal match payload for those entries.
    """
    raw_history = state.get("history", []) or []

    # Collect existing match identity triples to avoid duplicates
    seen_keys = set()
    normalized_history: List[Dict[str, Any]] = []
    for entry in raw_history:
        if not isinstance(entry, dict):
            continue
        key = (
            str(entry.get("weight_class", "")).strip().lower(),
            str(entry.get("red", "")).strip().lower(),
            str(entry.get("white", "")).strip().lower(),
            int(entry.get("completed_at") or entry.get("created_at") or 0),
        )
        seen_keys.add(key)
        normalized_history.append(entry)

    # Load Elo DBs and harvest KO results not already represented.
    try:
        all_dbs = load_all()
    except Exception:
        all_dbs = {}
    for wc, db in (all_dbs or {}).items():
        hist = (db or {}).get("history", []) or []
        for h in reversed(hist[-150:]):  # limit recent slice per class for perf
            result = h.get("result")
            if not isinstance(result, str):
                continue
            if "KO" not in result:
                continue  # only augment KO fights
            red = h.get("red_corner")
            white = h.get("white_corner")
            ts = int(h.get("timestamp") or 0)
            key = (str(wc).strip().lower(), str(red).strip().lower(), str(white).strip().lower(), ts)
            if key in seen_keys:
                continue
            # Determine winner name & decision label
            if result.startswith("Red wins KO"):
                winner_name = red
                decision = "ko"
            elif result.startswith("White wins KO"):
                winner_name = white
                decision = "ko"
            else:
                winner_name = None
                decision = "ko"
            synth = {
                "match_id": f"elo_{wc}_{h.get('match_id')}",
                "weight_class": wc,
                "red": red,
                "white": white,
                "created_at": ts,
                "completed_at": ts,
                "judges": [],
                "pending_judges": [],
                "is_complete": True,
                "headline": f"{winner_name} wins via KO" if winner_name else "KO recorded",
                "winner": "red" if winner_name == red else ("white" if winner_name == white else "draw"),
                "winner_name": winner_name,
                "decision": "KO",
                "scorecard_strings": [],
                "counts": {},
                # Embed a summary so build_match_payload does not overwrite winner
                "summary": {
                    "counts": {},
                    "winner": "red" if winner_name == red else ("white" if winner_name == white else "draw"),
                    "winner_name": winner_name,
                    "decision": "KO",
                    "scorecard_strings": [],
                    "pending_judges": [],
                    "is_complete": True,
                    "judge_cards": [],
                    "headline": f"{winner_name} wins via KO" if winner_name else "KO recorded",
                },
            }
            normalized_history.append(synth)
            seen_keys.add(key)

    # Sort combined history by completion timestamp desc
    normalized_history.sort(key=lambda e: int(e.get("completed_at") or e.get("created_at") or 0), reverse=True)

    if history_limit is not None:
        normalized_history = normalized_history[:history_limit]

    meta = state.get("_meta") or {}
    meta_payload = {"version": int(meta.get("version", 0)), "updated_at": meta.get("updated_at")}
    return {
        "judge_count": JUDGE_COUNT,
        "judge_labels": {i: f"Judge {i}" for i in range(1, JUDGE_COUNT + 1)},
        "current": build_match_payload(state.get("current")),
        "history": [build_match_payload(entry) for entry in normalized_history],
        "meta": meta_payload,
    }


def ensure_state_for_schedule(state: Dict[str, Any], schedule_list: List[Dict[str, Any]], judge_count: int = JUDGE_COUNT) -> Tuple[Dict[str, Any], bool]:
    if not isinstance(state, dict):
        state = default_state()
    changed = False
    history = state.get("history")
    if not isinstance(history, list):
        state["history"] = []
        history = state["history"]
        changed = True
    normalized_history: List[Dict[str, Any]] = []
    for entry in history:
        normalized_entry, entry_changed = normalize_match(entry, judge_count=judge_count)
        normalized_history.append(normalized_entry or {})
        if entry_changed:
            changed = True
    if normalized_history != history:
        state["history"] = normalized_history
        changed = True
    current = state.get("current")
    top_card = schedule_list[0] if schedule_list else None
    if top_card:
        if current and matches_card(current, top_card):
            normalized_current, cur_changed = normalize_match(current, judge_count=judge_count)
            if cur_changed:
                state["current"] = normalized_current
                changed = True
        else:
            state["current"] = create_match_record(top_card)
            changed = True
    else:
        if current is not None:
            state["current"] = None
            changed = True
    return state, changed
