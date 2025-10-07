import random
import unicodedata
from typing import Dict, Iterable, List, Optional, Set, Tuple

from elo import DEFAULT_RATING


try:  # pragma: no cover - fallback for tests that provide db explicitly
    from storage import load_all as _load_all_dbs
except Exception:  # pragma: no cover - allow generate() to be used without storage module
    _load_all_dbs = None


COOLDOWN_MATCHES = 3

RobotKey = Tuple[str, str]
PairKey = Tuple[str, str, str]


def _normalize(name: Optional[str]) -> str:
    if not name:
        return ""
    return unicodedata.normalize("NFKC", str(name)).strip()


def _canonicalize(name: Optional[str], roster: Iterable[str]) -> str:
    normalized = _normalize(name)
    if not normalized:
        return ""

    if normalized in roster:
        return normalized

    lowered = normalized.casefold()
    for candidate in roster:
        if candidate.casefold() == lowered:
            return candidate

    return normalized


def _collect_present(db_by_class: Dict[str, dict]) -> Dict[str, List[str]]:
    present = {}
    for weight_class, payload in db_by_class.items():
        roster = payload.get("robots") or {}
        contenders = [
            name
            for name, meta in roster.items()
            if meta and meta.get("present")
        ]
        if len(contenders) >= 2:
            present[weight_class] = sorted({_normalize(name) for name in contenders})
    return present


def _build_history_pairs(db_by_class: Dict[str, dict]) -> Set[PairKey]:
    seen: Set[PairKey] = set()
    for weight_class, payload in db_by_class.items():
        roster = payload.get("robots") or {}
        normalized_roster = {
            _normalize(name): meta for name, meta in roster.items()
        }
        history = payload.get("history") or []
        for match in history:
            red = _canonicalize(match.get("red_corner"), normalized_roster.keys())
            white = _canonicalize(match.get("white_corner"), normalized_roster.keys())
            if not red or not white:
                continue
            pair = tuple(sorted((red, white)))
            seen.add((weight_class, *pair))
    return seen


def _eligible_pairs(present: Dict[str, List[str]], history_pairs: Set[PairKey]) -> Dict[str, List[Tuple[str, str]]]:
    pairs: Dict[str, List[Tuple[str, str]]] = {}
    for weight_class, robots in present.items():
        class_pairs: List[Tuple[str, str]] = []
        for i in range(len(robots)):
            for j in range(i + 1, len(robots)):
                a, b = robots[i], robots[j]
                pair = (weight_class, *tuple(sorted((a, b))))
                if pair in history_pairs:
                    continue
                class_pairs.append(tuple(sorted((a, b))))
        if class_pairs:
            pairs[weight_class] = class_pairs
    return pairs


def _index_robot_opponents(pairs: Dict[str, List[Tuple[str, str]]]) -> Dict[RobotKey, List[str]]:
    mapping: Dict[RobotKey, List[str]] = defaultdict(list)
    for weight_class, class_pairs in pairs.items():
        for a, b in class_pairs:
            mapping[(weight_class, a)].append(b)
            mapping[(weight_class, b)].append(a)
    return mapping


def _cooldown_ok(last_seen: int, current_index: int) -> bool:
    return current_index - last_seen > COOLDOWN_MATCHES


def _available_opponents(
    key: RobotKey,
    opponents: Dict[RobotKey, List[str]],
    used_pairs: Set[PairKey],
    counts: Dict[RobotKey, int],
    desired_per_robot: int,
) -> int:
    weight_class, robot = key
    options = 0
    for opponent in opponents.get(key, []):
        pair = tuple(sorted((robot, opponent)))
        pair_key: PairKey = (weight_class, *pair)
        if pair_key in used_pairs:
            continue
        if counts[(weight_class, opponent)] >= desired_per_robot:
            continue
        if hist.get((wc, *pair), 0) == 0:
            return True
    return False
def build_history_counts(db_by_class):
    hist = {}
    for wc, db in db_by_class.items():
        seen={}
        for m in db.get("history", []):
            r=m.get("red_corner"); w=m.get("white_corner")
            if not r or not w: continue
            k=tuple(sorted([r,w])); seen[k]=seen.get(k,0)+1
        for (a,b),c in seen.items(): hist[(wc,a,b)]=c
    return hist
def present_by_class(db_by_class):
    out={}
    for wc,db in db_by_class.items():
        prs=[n for n,info in (db.get("robots",{}) or {}).items() if info.get("present")]
        if len(prs)>=2: out[wc]=prs
    return out
def rating_lookup(db_by_class):
    return {(wc,n): info.get("rating", DEFAULT_RATING) for wc,db in db_by_class.items() for n,info in (db.get("robots",{}) or {}).items()}
def generate(
    desired_per_robot: int = 1,
    interleave: bool = True,
    db_by_class: Optional[Dict[str, dict]] = None,
    seed: Optional[int] = None,
):
    if seed is not None:
        random.seed(seed)
    if db_by_class is None:
        if _load_all_dbs is None:
            raise RuntimeError("Database loader unavailable; provide db_by_class explicitly")
        db_by_class = _load_all_dbs()
    if not db_by_class:
        return []
    hist = build_history_counts(db_by_class); present = present_by_class(db_by_class)
    if not present: return []
    tonight={(wc,r):0 for wc,rs in present.items() for r in rs}; used_pairs=set(); sched=[]; last=set(); ratings=rating_lookup(db_by_class)
    def candidates():
        C=[]
        for wc,rs in present.items():
            for i in range(len(rs)):
                for j in range(i+1,len(rs)):
                    a,b=rs[i],rs[j]
                    if tonight[(wc,a)]>=desired_per_robot or tonight[(wc,b)]>=desired_per_robot: continue
                    key=tuple(sorted([a,b]))
                    if (wc,*key) in used_pairs: continue
                    met=hist.get((wc,*key),0); never=1 if met==0 else 0
                    fresh_penalty = 0
                    if met>0 and (
                        has_unscheduled_fresh_opponent(wc, a, present, hist, tonight, used_pairs, desired_per_robot)
                        or has_unscheduled_fresh_opponent(wc, b, present, hist, tonight, used_pairs, desired_per_robot)
                    ):
                        fresh_penalty = 1
                    diff=abs(ratings.get((wc,a),DEFAULT_RATING)-ratings.get((wc,b),DEFAULT_RATING))
                    consec = (a in last or b in last)
                    C.append((-never, fresh_penalty, met, diff, consec, random.random(), wc, a, b))
        return C
    while True:
        candidates: List[Tuple[Tuple[int, int, float], PairKey]] = []
        index = len(schedule)
        for weight_class, class_pairs in pairs.items():
            for a, b in class_pairs:
                pair_key: PairKey = (weight_class, a, b)
                if pair_key in used_pairs:
                    continue
                count_a = counts[(weight_class, a)]
                count_b = counts[(weight_class, b)]
                if count_a >= desired_per_robot or count_b >= desired_per_robot:
                    continue
                if not _cooldown_ok(last_seen[(weight_class, a)], index):
                    continue
                if not _cooldown_ok(last_seen[(weight_class, b)], index):
                    continue
                remaining_need = (desired_per_robot - count_a) + (desired_per_robot - count_b)
                available = _available_opponents((weight_class, a), opponents, used_pairs, counts, desired_per_robot)
                available += _available_opponents((weight_class, b), opponents, used_pairs, counts, desired_per_robot)
                candidates.append(
                    ((available, -remaining_need, random.random()), pair_key)
                )
        if not candidates:
            break
        candidates.sort(key=lambda item: item[0])
        chosen = candidates[0][1]
        weight_class, red, white = chosen
        schedule.append(chosen)
        counts[(weight_class, red)] += 1
        counts[(weight_class, white)] += 1
        last_seen[(weight_class, red)] = len(schedule) - 1
        last_seen[(weight_class, white)] = len(schedule) - 1
        used_pairs.add(_unique_pair_key(chosen))
    return schedule


def _unique_pair_key(pair: PairKey) -> PairKey:
    weight_class, a, b = pair
    ordered = tuple(sorted((a, b)))
    return (weight_class, *ordered)


def generate(
    desired_per_robot: int = 1,
    interleave: bool = True,
    db_by_class: Optional[Dict[str, dict]] = None,
    seed: Optional[int] = None,
) -> List[Dict[str, str]]:
    del interleave  # interleaving handled implicitly by cooldown logic
    if seed is not None:
        random.seed(seed)

    if db_by_class is None:
        if _load_all_dbs is None:
            raise RuntimeError("Database loader unavailable; provide db_by_class explicitly")
        db_by_class = _load_all_dbs()

    if not db_by_class:
        return []

    present = _collect_present(db_by_class)
    if not present:
        return []

    history_pairs = _build_history_pairs(db_by_class)
    pairs = _eligible_pairs(present, history_pairs)
    if not pairs:
        return []

    best_schedule: List[PairKey] = []
    attempts = max(5, sum(len(class_pairs) for class_pairs in pairs.values()))
    for _ in range(attempts):
        schedule_attempt = _run_single_attempt(present, pairs, desired_per_robot)
        if len(schedule_attempt) > len(best_schedule):
            best_schedule = schedule_attempt

    results: List[Dict[str, str]] = []
    used_pairs: Set[PairKey] = set()
    for weight_class, a, b in best_schedule:
        key = _unique_pair_key((weight_class, a, b))
        if key in used_pairs:
            continue
        used_pairs.add(key)
        if random.random() < 0.5:
            red, white = a, b
        else:
            red, white = b, a
        results.append({"weight_class": weight_class, "red": red, "white": white})

    return results
