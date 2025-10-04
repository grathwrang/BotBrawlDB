import random
import unicodedata
from collections import defaultdict
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from storage import load_all as _load_all_dbs

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
    present: Dict[str, List[str]] = {}
    for weight_class, payload in db_by_class.items():
        roster = payload.get("robots") or {}
        contenders = [
            _normalize(name)
            for name, meta in roster.items()
            if meta and meta.get("present")
        ]
        if len(contenders) >= 2:
            unique_contenders = sorted({name for name in contenders if name})
            if len(unique_contenders) >= 2:
                present[weight_class] = unique_contenders
    return present


def _build_history_pairs(db_by_class: Dict[str, dict]) -> Set[PairKey]:
    seen: Set[PairKey] = set()
    for weight_class, payload in db_by_class.items():
        roster = payload.get("robots") or {}
        normalized_roster = {_normalize(name) for name in roster.keys()}
        history = payload.get("history") or []
        for match in history:
            red = _canonicalize(match.get("red_corner"), normalized_roster)
            white = _canonicalize(match.get("white_corner"), normalized_roster)
            if not red or not white:
                continue
            ordered = tuple(sorted((red, white)))
            seen.add((weight_class, *ordered))
    return seen


def _eligible_pairs(
    present: Dict[str, List[str]], history_pairs: Set[PairKey]
) -> Dict[str, List[Tuple[str, str]]]:
    pairs: Dict[str, List[Tuple[str, str]]] = {}
    for weight_class, robots in present.items():
        class_pairs: List[Tuple[str, str]] = []
        for i in range(len(robots)):
            for j in range(i + 1, len(robots)):
                a, b = robots[i], robots[j]
                pair_key: PairKey = (weight_class, *tuple(sorted((a, b))))
                if pair_key in history_pairs:
                    continue
                class_pairs.append(tuple(sorted((a, b))))
        if class_pairs:
            pairs[weight_class] = class_pairs
    return pairs


def _index_robot_opponents(
    pairs: Dict[str, List[Tuple[str, str]]]
) -> Dict[RobotKey, List[str]]:
    mapping: Dict[RobotKey, List[str]] = defaultdict(list)
    for weight_class, class_pairs in pairs.items():
        for a, b in class_pairs:
            mapping[(weight_class, a)].append(b)
            mapping[(weight_class, b)].append(a)
    return mapping


def _unique_pair_key(pair: PairKey) -> PairKey:
    weight_class, a, b = pair
    ordered = tuple(sorted((a, b)))
    return (weight_class, *ordered)


def _max_possible_matches(
    present: Dict[str, List[str]], desired_per_robot: int
) -> int:
    total = 0
    for robots in present.values():
        total += (len(robots) * max(desired_per_robot, 0)) // 2
    return total


def _current_options(
    key: RobotKey,
    opponents: Dict[RobotKey, List[str]],
    used_pairs: Set[PairKey],
    counts: Dict[RobotKey, int],
    desired_per_robot: int,
    index: int,
    last_seen: Dict[RobotKey, int],
) -> int:
    if counts[key] >= desired_per_robot:
        return 0
    weight_class, robot = key
    options = 0
    for opponent in opponents.get(key, []):
        pair_key = (weight_class, *tuple(sorted((robot, opponent))))
        if pair_key in used_pairs:
            continue
        if counts[(weight_class, opponent)] >= desired_per_robot:
            continue
        if index - last_seen[key] <= COOLDOWN_MATCHES:
            continue
        if index - last_seen[(weight_class, opponent)] <= COOLDOWN_MATCHES:
            continue
        options += 1
    return options


def _search_schedule(
    all_pairs: Sequence[PairKey],
    opponents: Dict[RobotKey, List[str]],
    desired_per_robot: int,
    target: int,
) -> List[PairKey]:
    if desired_per_robot <= 0:
        return []

    used_pairs: Set[PairKey] = set()
    counts: Dict[RobotKey, int] = defaultdict(int)
    last_seen: Dict[RobotKey, int] = defaultdict(lambda: -COOLDOWN_MATCHES - 1)
    best_schedule: List[PairKey] = []

    def backtrack(schedule: List[PairKey]) -> bool:
        nonlocal best_schedule
        if len(schedule) > len(best_schedule):
            best_schedule = list(schedule)
            if len(best_schedule) >= target:
                return True
        index = len(schedule)

        candidates: List[Tuple[Tuple[int, int, float], PairKey, PairKey]] = []
        for pair in all_pairs:
            unique_key = _unique_pair_key(pair)
            if unique_key in used_pairs:
                continue
            weight_class, a, b = pair
            key_a = (weight_class, a)
            key_b = (weight_class, b)
            if counts[key_a] >= desired_per_robot or counts[key_b] >= desired_per_robot:
                continue
            if index - last_seen[key_a] <= COOLDOWN_MATCHES:
                continue
            if index - last_seen[key_b] <= COOLDOWN_MATCHES:
                continue
            options_a = _current_options(
                key_a, opponents, used_pairs, counts, desired_per_robot, index, last_seen
            )
            options_b = _current_options(
                key_b, opponents, used_pairs, counts, desired_per_robot, index, last_seen
            )
            if options_a == 0 or options_b == 0:
                continue
            candidates.append(
                ((min(options_a, options_b), options_a + options_b, random.random()), pair, unique_key)
            )

        if not candidates:
            return False

        candidates.sort(key=lambda item: item[0])
        for _, pair, unique_key in candidates:
            weight_class, a, b = pair
            key_a = (weight_class, a)
            key_b = (weight_class, b)

            schedule.append(pair)
            used_pairs.add(unique_key)
            counts[key_a] += 1
            counts[key_b] += 1
            prev_a = last_seen[key_a]
            prev_b = last_seen[key_b]
            last_seen[key_a] = len(schedule) - 1
            last_seen[key_b] = len(schedule) - 1

            if backtrack(schedule):
                return True

            schedule.pop()
            used_pairs.remove(unique_key)
            counts[key_a] -= 1
            counts[key_b] -= 1
            last_seen[key_a] = prev_a
            last_seen[key_b] = prev_b

        return False

    backtrack([])
    return best_schedule


def generate(
    desired_per_robot: int = 1,
    interleave: bool = True,
    db_by_class: Optional[Dict[str, dict]] = None,
    seed: Optional[int] = None,
) -> List[Dict[str, str]]:
    del interleave
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
    eligible_pairs = _eligible_pairs(present, history_pairs)
    if not eligible_pairs:
        return []

    opponents = _index_robot_opponents(eligible_pairs)
    all_pairs: List[PairKey] = []
    for weight_class, class_pairs in eligible_pairs.items():
        for a, b in class_pairs:
            all_pairs.append((weight_class, a, b))

    if not all_pairs:
        return []

    random.shuffle(all_pairs)

    max_matches = _max_possible_matches(present, desired_per_robot)
    schedule_pairs = _search_schedule(all_pairs, opponents, desired_per_robot, max_matches)
    if len(schedule_pairs) < max_matches:
        # Try additional shuffled orders to escape unlucky ordering
        attempts = min(10, max(1, len(all_pairs)))
        best_pairs = list(schedule_pairs)
        for _ in range(attempts):
            random.shuffle(all_pairs)
            candidate = _search_schedule(all_pairs, opponents, desired_per_robot, max_matches)
            if len(candidate) > len(best_pairs):
                best_pairs = candidate
                if len(best_pairs) >= max_matches:
                    break
        schedule_pairs = best_pairs

    results: List[Dict[str, str]] = []
    used_pairs: Set[PairKey] = set()
    for weight_class, a, b in schedule_pairs:
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
