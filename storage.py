import os, json, datetime, tempfile, shutil, csv
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
DB_FILES = {
    "Antweights": os.path.join(DATA_DIR, "elo_antweights.txt"),
    "Beetleweights": os.path.join(DATA_DIR, "elo_beetleweights.txt"),
    "Sumos": os.path.join(DATA_DIR, "elo_sumos.txt"),
}
SCHEDULE_FP = os.path.join(DATA_DIR, "schedule.json")
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
