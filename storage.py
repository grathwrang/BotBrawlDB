import os, json, datetime, tempfile, shutil, csv, time
from typing import Callable, Any, Optional

try:
    import fcntl  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover - Windows fallback
    fcntl = None
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
DB_FILES = {
    "Antweights": os.path.join(DATA_DIR, "elo_antweights.txt"),
    "Beetleweights": os.path.join(DATA_DIR, "elo_beetleweights.txt"),
    "Sumos": os.path.join(DATA_DIR, "elo_sumos.txt"),
}
SCHEDULE_FP = os.path.join(DATA_DIR, "schedule.json")
JUDGING_FP = os.path.join(DATA_DIR, "judging.json")
JUDGING_LOCK_FP = os.path.join(DATA_DIR, "judging.lock")
DEFAULT_RATING = 1000; DEFAULT_K = 32; KO_WEIGHT = 1.10
def ensure_dirs(): os.makedirs(DATA_DIR, exist_ok=True)
def _blank_db():
    return {"robots": {}, "history": [], "next_match_id": 1, "settings": {"K": DEFAULT_K, "ko_weight": KO_WEIGHT}}
def load_db(weight_class):
    ensure_dirs(); fp = DB_FILES[weight_class]
    if not os.path.exists(fp): return _blank_db()
    with open(fp, "r", encoding="utf-8") as f:
        try: return json.load(f)
        except Exception:
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S"); shutil.copy(fp, fp + ".corrupt_" + ts); return _blank_db()
def save_db(weight_class, db):
    ensure_dirs(); fp = DB_FILES[weight_class]
    fd, tmp = tempfile.mkstemp(prefix="._elo_", dir=DATA_DIR)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=2, ensure_ascii=False); f.flush(); os.fsync(f.fileno())
    os.replace(tmp, fp)
def load_all(): return {wc: load_db(wc) for wc in DB_FILES.keys()}
def export_stats_csv(weight_class):
    db = load_db(weight_class); robots = db.get("robots", {}); rows = []
    for name, info in robots.items():
        matches = info.get("matches", []); wins=losses=draws=ko_wins=ko_losses=0; last_ts=None
        for m in matches:
            ts=m.get("timestamp"); last_ts = max(last_ts, ts) if last_ts is not None else ts
            res = m.get("result",""); robot_is_red = (m.get("red_corner")==name)
            if res=="Draw": draws+=1; continue
            red_win = res.startswith("Red wins"); is_ko = "KO" in res
            won = (red_win and robot_is_red) or ((not red_win) and (not robot_is_red))
            if won: wins+=1; ko_wins+= int(is_ko)
            else: losses+=1; ko_losses+= int(is_ko)
        total = wins+losses+draws
        rows.append({"robot":name,"rating":info.get("rating",DEFAULT_RATING),"matches":total,
                     "wins":wins,"losses":losses,"draws":draws,"ko_wins":ko_wins,"ko_losses":ko_losses,
                     "win_rate": round(wins/total,4) if total else 0.0,
                     "last_match_date": (datetime.datetime.fromtimestamp(last_ts).strftime('%Y-%m-%d %H:%M:%S') if last_ts else "")})
    outdir = os.path.join(DATA_DIR,"exports"); os.makedirs(outdir, exist_ok=True)
    fp = os.path.join(outdir, f"{weight_class.lower()}_stats.csv")
    with open(fp,"w",newline="",encoding="utf-8") as f:
        import csv as _csv; w = _csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["robot","rating","matches","wins","losses","draws","ko_wins","ko_losses","win_rate","last_match_date"])
        w.writeheader(); [w.writerow(r) for r in rows]
    return fp
def load_schedule():
    ensure_dirs()
    if not os.path.exists(SCHEDULE_FP): return {"list":[]}
    with open(SCHEDULE_FP,"r",encoding="utf-8") as f:
        try: return json.load(f)
        except Exception: return {"list":[]}
def save_schedule(sched):
    ensure_dirs(); fd,tmp = tempfile.mkstemp(prefix="._elo_sched_", dir=DATA_DIR)
    with os.fdopen(fd,"w",encoding="utf-8") as f:
        json.dump(sched,f,indent=2,ensure_ascii=False); f.flush(); os.fsync(f.fileno())
    os.replace(tmp, SCHEDULE_FP)

def _blank_judging_state():
    return {
        "current": None,
        "history": [],
        "_meta": {"version": 0, "updated_at": int(time.time())},
    }


def _ensure_state_metadata(state, *, bump: bool = True, timestamp: Optional[int] = None):
    if not isinstance(state, dict):
        state = _blank_judging_state()
    meta = state.get("_meta")
    if not isinstance(meta, dict):
        meta = {}
    current_version = int(meta.get("version", 0))
    if bump:
        current_version += 1
    meta["version"] = current_version
    now = int(time.time()) if timestamp is None else int(timestamp)
    existing_updated_at = meta.get("updated_at")
    if bump or existing_updated_at is None:
        meta["updated_at"] = now
    else:
        try:
            meta["updated_at"] = int(existing_updated_at)
        except (TypeError, ValueError):
            meta["updated_at"] = now
    state["_meta"] = meta
    return state

def load_judging_state():
    ensure_dirs()
    if not os.path.exists(JUDGING_FP):
        state = _blank_judging_state()
        save_judging_state(state)
        return state
    with open(JUDGING_FP, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
            if not isinstance(data, dict):
                return _blank_judging_state()
            if "_meta" not in data:
                data = _ensure_state_metadata(data, bump=False)
                save_judging_state(data, bump=False)
            return data
        except Exception:
            return _blank_judging_state()

def save_judging_state(state, *, bump: bool = True):
    ensure_dirs()
    state = _ensure_state_metadata(state, bump=bump)
    fd, tmp = tempfile.mkstemp(prefix="._judging_", dir=DATA_DIR)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, JUDGING_FP)


def update_judging_state(mutator: Callable[[Any], Any]):
    """Atomically load, mutate, and persist the judging state."""
    ensure_dirs()
    lock_file = open(JUDGING_LOCK_FP, "a+")
    try:
        if fcntl is not None:
            fcntl.flock(lock_file, fcntl.LOCK_EX)
        state = load_judging_state()
        original_snapshot = json.dumps(
            state, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        new_state = mutator(state)
        if new_state is None or not isinstance(new_state, dict):
            new_state = state
        updated_snapshot = json.dumps(
            new_state, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        changed = updated_snapshot != original_snapshot
        has_meta = isinstance(new_state.get("_meta"), dict) if isinstance(new_state, dict) else False
        if changed:
            save_judging_state(new_state, bump=True)
        elif not has_meta:
            save_judging_state(new_state, bump=False)
        return new_state
    finally:
        if fcntl is not None:
            fcntl.flock(lock_file, fcntl.LOCK_UN)
        lock_file.close()
