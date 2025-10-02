from flask import Flask, render_template, request, redirect, url_for, jsonify, send_file, flash
import time, os, copy
from datetime import datetime
from zoneinfo import ZoneInfo
from werkzeug.utils import secure_filename
from elo import get_expected, get_k_for_robot, DEFAULT_RATING, DEFAULT_K, KO_WEIGHT
from storage import (
    load_db,
    save_db,
    DB_FILES,
    load_all,
    load_schedule,
    save_schedule,
    export_stats_csv,
    load_judging_state,
    save_judging_state,
    update_judging_state,
)
from schedule_engine import generate
from judging import (
    CATEGORY_SPECS,
    CATEGORY_KEYS,
    JUDGE_COUNT,
    ensure_state_for_schedule,
    build_state_payload,
    create_judge_record,
    matches_card,
    normalize_match,
)

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "static", "uploads")
ALLOWED_EXT = {"png","jpg","jpeg","gif","webp"}
# ensure uploads dir exists at runtime (Windows/Linux)
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY","devkey")

WEIGHT_CLASSES = list(DB_FILES.keys())
VALID_RESULTS = {"Red wins JD", "Red wins KO", "White wins JD", "White wins KO", "Draw"}
JUDGE_IDS = list(range(1, JUDGE_COUNT + 1))
JUDGE_LABELS = {i: f"Judge {i}" for i in JUDGE_IDS}

@app.template_filter('datetimefromts')
def datetimefromts(ts):
    try:
        return datetime.fromtimestamp(int(ts), ZoneInfo("America/Toronto")).strftime('%Y-%m-%d %H:%M:%S')
    except Exception:
        return ts

def get_settings(db):
    s = db.get("settings") or {}
    return int(s.get("K", DEFAULT_K)), float(s.get("ko_weight", KO_WEIGHT))

@app.context_processor
def inject_globals():
    sched = load_schedule().get("list", [])
    top = sched[0] if sched else None
    return {"WEIGHT_CLASSES": WEIGHT_CLASSES, "TOP_MATCH": top}

def robot_stats(db, name):
    info = db.get("robots", {}).get(name, {})
    wins=losses=draws=ko_wins=ko_losses=0
    for m in info.get("matches", []):
        res = m.get("result","")
        if res=="Draw": draws+=1; continue
        robot_is_red = (m.get("red_corner")==name)
        red_win = res.startswith("Red wins")
        is_ko = "KO" in res
        won = (red_win and robot_is_red) or ((not red_win) and (not robot_is_red))
        if won: wins+=1; ko_wins+= int(is_ko)
        else: losses+=1; ko_losses+= int(is_ko)
    return {"wins":wins,"losses":losses,"draws":draws,"ko_wins":ko_wins,"ko_losses":ko_losses}


def get_synced_judging_state():
    schedule_data = load_schedule()
    schedule_list = schedule_data.get("list", []) if isinstance(schedule_data, dict) else []
    state = load_judging_state()
    state, changed = ensure_state_for_schedule(state, schedule_list)
    if changed:
        save_judging_state(state)
    return state, schedule_data, schedule_list


def sync_judging_with_schedule(schedule_data):
    state = load_judging_state()
    schedule_list = schedule_data.get("list", []) if isinstance(schedule_data, dict) else []
    state, changed = ensure_state_for_schedule(state, schedule_list)
    if changed:
        save_judging_state(state)
    return state


def robot_display(weight_class, name):
    stats_template = {"wins": 0, "losses": 0, "draws": 0, "ko_wins": 0, "ko_losses": 0}
    base_payload = {
        "name": name or "",
        "image": "",
        "driver": "",
        "team": "",
        "rating": None,
        **stats_template,
    }
    if not weight_class or not name or weight_class not in WEIGHT_CLASSES:
        return dict(base_payload)
    try:
        db = load_db(weight_class)
    except KeyError:
        return dict(base_payload)
    robots = db.get("robots", {}) or {}
    info = robots.get(name)
    stats = robot_stats(db, name) if info is not None else stats_template
    if info is None:
        payload = dict(base_payload)
        payload["name"] = name
        payload.update(stats)
        return payload
    return {
        "name": name,
        "image": info.get("image", ""),
        "driver": info.get("driver_name", ""),
        "team": info.get("team_name", ""),
        "rating": info.get("rating", DEFAULT_RATING),
        "wins": stats.get("wins", 0),
        "losses": stats.get("losses", 0),
        "draws": stats.get("draws", 0),
        "ko_wins": stats.get("ko_wins", 0),
        "ko_losses": stats.get("ko_losses", 0),
    }


def finalize_current_match(state, schedule_data):
    current = state.get("current")
    if not current:
        return state, schedule_data
    history_entry = copy.deepcopy(current)
    history_entry["completed_at"] = int(time.time())
    normalized_entry, _ = normalize_match(history_entry)
    if normalized_entry:
        history_entry = normalized_entry
    state.setdefault("history", [])
    state["history"].insert(0, history_entry)
    state["current"] = None
    save_judging_state(state)

    schedule_list = schedule_data.get("list", []) if isinstance(schedule_data, dict) else []
    if schedule_list:
        if matches_card(history_entry, schedule_list[0]):
            schedule_list.pop(0)
        else:
            for idx, card in enumerate(list(schedule_list)):
                if matches_card(history_entry, card):
                    schedule_list.pop(idx)
                    break
    save_schedule(schedule_data)

    state, changed = ensure_state_for_schedule(state, schedule_list)
    if changed:
        save_judging_state(state)
    return state, schedule_data

@app.route("/")
def index():
    wc = request.args.get("wc", WEIGHT_CLASSES[0])
    if wc not in WEIGHT_CLASSES: wc = WEIGHT_CLASSES[0]
    db = load_db(wc)
    robots = sorted(db.get("robots", {}).items(), key=lambda x: x[1].get("rating", DEFAULT_RATING), reverse=True)
    k, ko = get_settings(db)
    status = "Ready"
    return render_template("index.html", wc=wc, robots=robots, k=k, ko=ko, status=status)

@app.post("/submit_match")
def submit_match():
    wc = request.form.get("wc")
    red = request.form.get("red","").strip()
    white = request.form.get("white","").strip()
    result = request.form.get("result")
    if wc not in WEIGHT_CLASSES or not red or not white or result not in VALID_RESULTS or red == white:
        flash("Bad match input", "error")
        return redirect(url_for("index", wc=wc or WEIGHT_CLASSES[0]))
    db = load_db(wc)
    robots = db.setdefault("robots", {})
    # Allow case-insensitive robot name input
    if red not in robots or white not in robots:
        lower_map = {k.lower(): k for k in robots.keys()}
        if red not in robots and red.lower() in lower_map:
            red = lower_map[red.lower()]
        if white not in robots and white.lower() in lower_map:
            white = lower_map[white.lower()]
    if red not in robots or white not in robots:
        flash("Robot not found", "error"); return redirect(url_for("index", wc=wc))
    rr = robots[red]; rw = robots[white]
    old_r = rr.get("rating", DEFAULT_RATING); old_w = rw.get("rating", DEFAULT_RATING)
    e_r = get_expected(old_r, old_w); e_w = 1 - e_r
    k_base, ko_w = get_settings(db)
    if result == "Red wins JD": s_r,s_w,w_r,w_w=1,0,1,1
    elif result == "Red wins KO": s_r,s_w,w_r,w_w=1,0,ko_w,1
    elif result == "White wins JD": s_r,s_w,w_r,w_w=0,1,1,1
    elif result == "White wins KO": s_r,s_w,w_r,w_w=0,1,1,ko_w
    else: s_r,s_w,w_r,w_w=0.5,0.5,1,1
    k_r = get_k_for_robot(len(rr.get("matches", [])), k_base)
    k_w = get_k_for_robot(len(rw.get("matches", [])), k_base)
    new_r = round(old_r + k_r * ((s_r * w_r) - e_r))
    new_w = round(old_w + k_w * ((s_w * w_w) - e_w))
    mid = db.get("next_match_id", 1); ts = int(time.time())
    entry = {"match_id": mid,"timestamp": ts,"red_corner": red,"white_corner": white,"result": result,
             "old_rating_red": old_r,"old_rating_white": old_w,"new_rating_red": new_r,"new_rating_white": new_w,
             "change_red": new_r-old_r,"change_white": new_w-old_w}
    db.setdefault("history", []).append(entry); db["next_match_id"]=mid+1
    rr["rating"]=new_r; rw["rating"]=new_w
    rr.setdefault("matches", []).append(entry); rw.setdefault("matches", []).append(entry)
    save_db(wc, db)

    if request.form.get("popFromSchedule") == "1":
        sched = load_schedule(); L = sched.get("list", [])
        # pop match case/whitespace-insensitively so minor mismatches don't block
        wc_norm = (wc or "").strip().lower()
        red_norm = (red or "").strip().lower()
        white_norm = (white or "").strip().lower()
        for i, m in enumerate(L):
            if (m.get("weight_class","").strip().lower() == wc_norm and
                m.get("red","").strip().lower() == red_norm and
                m.get("white","").strip().lower() == white_norm):
                L.pop(i)
                break
        save_schedule(sched)
        sync_judging_with_schedule(sched)
        return redirect(url_for("schedule"))
    return redirect(url_for("index", wc=wc))

@app.post("/undo")
def undo():
    wc = request.form.get("wc")
    if wc not in WEIGHT_CLASSES: wc = WEIGHT_CLASSES[0]
    db = load_db(wc); hist = db.get("history", [])
    if not hist: flash("No matches to undo","info"); return redirect(url_for("index", wc=wc))
    last = hist.pop(); red,white = last["red_corner"], last["white_corner"]
    robots = db.get("robots", {})
    if red in robots:
        r = robots[red]; r["rating"]= last["old_rating_red"]
        r["matches"]=[m for m in r.get("matches",[]) if m.get("match_id")!= last["match_id"]]
    if white in robots:
        w = robots[white]; w["rating"]= last["old_rating_white"]
        w["matches"]=[m for m in w.get("matches",[]) if m.get("match_id")!= last["match_id"]]
    save_db(wc, db); return redirect(url_for("index", wc=wc))

@app.post("/reset_all")
def reset_all():
    wc = request.form.get("wc")
    if wc not in WEIGHT_CLASSES: wc = WEIGHT_CLASSES[0]
    db = load_db(wc)
    robots = db.get("robots", {})
    for r in robots.values():
        r["rating"]=DEFAULT_RATING
        r["matches"]=[]
    db["history"]=[]; db["next_match_id"]=1
    save_db(wc, db); flash("All Elo reset for " + wc, "info")
    return redirect(url_for("index", wc=wc))

@app.post("/robot/presence")
def robot_presence():
    wc = (request.form.get("wc") or "").strip()
    name = (request.form.get("name") or "").strip()
    present = request.form.get("present") == "1"

    if wc not in WEIGHT_CLASSES:
        return redirect(url_for("index", wc=WEIGHT_CLASSES[0]))

    db = load_db(wc)
    robots = db.get("robots", {}) or {}
    if name and name in robots:
        robots[name]["present"] = present
        save_db(wc, db)
    return redirect(url_for("index", wc=wc))

def save_upload(file):
    # Return a relative URL under /static/uploads or None
    if not file or file.filename == "":
        return None
    # tolerate files without extension
    ext = file.filename.rsplit(".",1)[-1].lower() if "." in file.filename else ""
    if ext and ext not in ALLOWED_EXT:
        return None
    safe = secure_filename(file.filename or "upload")
    name = str(int(time.time()*1000)) + "_" + safe
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    path = os.path.join(UPLOAD_DIR, name)
    file.save(path)
    return "/static/uploads/" + name

@app.post("/robot/add")
def robot_add():
    wc = request.form.get("wc"); name = request.form.get("name","").strip()
    driver = request.form.get("driver","").strip(); team = request.form.get("team","").strip()
    try: rating = int(request.form.get("rating", DEFAULT_RATING))
    except Exception: rating = DEFAULT_RATING
    img_url = save_upload(request.files.get("image"))
    if not name or wc not in WEIGHT_CLASSES: flash("Bad input","error"); return redirect(url_for("index", wc=wc or WEIGHT_CLASSES[0]))
    db = load_db(wc)
    if name in db.get("robots", {}): flash("Robot exists","error"); return redirect(url_for("index", wc=wc))
    db["robots"][name]={"rating":rating,"matches":[],"driver_name":driver,"team_name":team,"weight_class":wc,"present":False}
    if img_url: db["robots"][name]["image"]=img_url
    save_db(wc, db); return redirect(url_for("index", wc=wc))

@app.post("/robot/edit")
def robot_edit():
    wc = request.form.get("wc"); old = request.form.get("old","").strip(); new = request.form.get("new","").strip()
    driver = request.form.get("driver","").strip(); team = request.form.get("team","").strip()
    try: rating = int(request.form.get("rating"))
    except Exception: rating = None
    img_url = save_upload(request.files.get("image"))
    if wc not in WEIGHT_CLASSES or old=="" or old not in load_db(wc).get("robots", {}): flash("Robot not found","error"); return redirect(url_for("index", wc=wc or WEIGHT_CLASSES[0]))
    db = load_db(wc)
    if new and new!=old and new in db.get("robots", {}): flash("Name already exists","error"); return redirect(url_for("index", wc=wc))
    if new and new!=old:
        db["robots"][new] = db["robots"].pop(old)
        for m in db.get("history", []):
            if m.get("red_corner")==old: m["red_corner"]=new
            if m.get("white_corner")==old: m["white_corner"]=new
        target=new
    else: target=old
    r = db["robots"][target]
    if rating is not None: r["rating"]=rating
    if driver: r["driver_name"]=driver
    if team: r["team_name"]=team
    if img_url: r["image"]=img_url
    save_db(wc, db); return redirect(url_for("index", wc=wc))

@app.post("/robot/delete")
def robot_delete():
    wc = request.form.get("wc"); name = request.form.get("name","").strip()
    if wc not in WEIGHT_CLASSES: wc = WEIGHT_CLASSES[0]
    db = load_db(wc)
    if name in db.get("robots", {}):
        del db["robots"][name]
        db["history"]=[m for m in db.get("history",[]) if m.get("red_corner")!=name and m.get("white_corner")!=name]
        save_db(wc, db)
    return redirect(url_for("index", wc=wc))

@app.get("/robot/<wc>/<name>")
def robot_info(wc, name):
    if wc not in WEIGHT_CLASSES: wc = WEIGHT_CLASSES[0]
    wc = (wc or '').strip(); name = (name or '').strip()
    if wc not in WEIGHT_CLASSES:
        return "Bad weight class", 404
    db = load_db(wc)
    info = db.get("robots", {}).get(name)
    if not info: return "Not found", 404
    matches = sorted(info.get("matches", []), key=lambda m: m["timestamp"], reverse=True)[:50]
    return render_template("robot.html", wc=wc, name=name, info=info, matches=matches)

@app.post("/save_settings")
def save_settings_route():
    wc = request.form.get("wc")
    if wc not in WEIGHT_CLASSES: wc = WEIGHT_CLASSES[0]
    db = load_db(wc)
    try: k = int(request.form.get("k")); ko = float(request.form.get("ko"))
    except Exception: flash("Invalid K/KO", "error"); return redirect(url_for("index", wc=wc))
    db.setdefault("settings", {})["K"]=k; db["settings"]["ko_weight"]=ko; save_db(wc, db)
    return redirect(url_for("index", wc=wc))

@app.get("/export/<wc>/csv")
def export_wc_csv(wc):
    if wc not in WEIGHT_CLASSES: return "Bad class", 400
    fp = export_stats_csv(wc); return send_file(fp, as_attachment=True, download_name=os.path.basename(fp))

@app.get("/schedule")
def schedule():
    state, _, schedule_list = get_synced_judging_state()
    all_dbs = load_all()
    presence = []
    for w, db in all_dbs.items():
        for name, info in (db.get("robots", {}) or {}).items():
            presence.append({"weight": w, "robot": name, "present": "Yes" if info.get("present") else ""})
    top = schedule_list[0] if schedule_list else None
    return render_template(
        "schedule.html",
        schedule=schedule_list,
        presence=presence,
        top=top,
        weight_classes=WEIGHT_CLASSES,
        judge_panel=build_state_payload(state, history_limit=10),
        category_specs=CATEGORY_SPECS,
        judge_labels=JUDGE_LABELS,
    )


@app.post("/schedule/generate")
def schedule_generate():
    try: per = int(request.form.get("matchesPerRobot","1"))
    except Exception: per = 1
    interleave = request.form.get("interleave") == "1"
    sched_list = generate(desired_per_robot=per, interleave=interleave, db_by_class=load_all())
    schedule_data = {"list": sched_list}
    save_schedule(schedule_data)
    sync_judging_with_schedule(schedule_data)
    return redirect(url_for("schedule"))

@app.post("/schedule/clear")
def schedule_clear():
    schedule_data = {"list": []}
    save_schedule(schedule_data)
    sync_judging_with_schedule(schedule_data)
    return redirect(url_for("schedule"))

@app.post("/schedule/move")
def schedule_move():
    idx = int(request.form.get("index","-1")); direction = int(request.form.get("direction","0"))
    sched = load_schedule(); L = sched.get("list", [])
    if 0 <= idx < len(L):
        newi = idx + direction
        if 0 <= newi < len(L):
            L[idx], L[newi] = L[newi], L[idx]
            save_schedule(sched)
            sync_judging_with_schedule(sched)
    return redirect(url_for("schedule"))

@app.post("/schedule/delete")
def schedule_delete():
    idx = int(request.form.get("index","-1")); sched = load_schedule(); L = sched.get("list", [])
    if 0 <= idx < len(L):
        L.pop(idx)
        save_schedule(sched)
        sync_judging_with_schedule(sched)
    return redirect(url_for("schedule"))

@app.post("/schedule/undo")
def schedule_undo():
    wc = request.form.get("wc")
    if wc not in WEIGHT_CLASSES: wc = WEIGHT_CLASSES[0]
    db = load_db(wc); hist = db.get("history", [])
    if not hist: flash("No matches to undo","info"); return redirect(url_for("schedule"))
    last = hist.pop(); red,white = last["red_corner"], last["white_corner"]
    robots = db.get("robots", {})
    if red in robots:
        r = robots[red]; r["rating"]= last["old_rating_red"]
        r["matches"]=[m for m in r.get("matches",[]) if m.get("match_id")!= last["match_id"]]
    if white in robots:
        w = robots[white]; w["rating"]= last["old_rating_white"]
        w["matches"]=[m for m in w.get("matches",[]) if m.get("match_id")!= last["match_id"]]
    save_db(wc, db)
    sched = load_schedule(); sched.setdefault("list", []); sched["list"].insert(0, {"weight_class": wc, "red": red, "white": white})
    save_schedule(sched)
    sync_judging_with_schedule(sched)
    return redirect(url_for("schedule"))

@app.post("/schedule/add")
def schedule_add():
    wc = request.form.get("wc", "").strip()
    red = request.form.get("red", "").strip()
    white = request.form.get("white", "").strip()
    position = request.form.get("position", "bottom")  # "top" or "bottom"

    # Basic validation
    if wc not in WEIGHT_CLASSES:
        flash("Invalid weight class.", "error")
        return redirect(url_for("schedule"))
    if not red or not white:
        flash("Please provide both robot names.", "error")
        return redirect(url_for("schedule"))
    if red == white:
        flash("Red and White robots must be different.", "error")
        return redirect(url_for("schedule"))

    # (Optional) Try to normalize names to existing robots for that class (case-insensitive)
    # If not found, we still allow the free-form names.
    db = load_db(wc)
    existing = {name.lower(): name for name in (db.get("robots", {}) or {}).keys()}
    red_norm = existing.get(red.lower(), red)
    white_norm = existing.get(white.lower(), white)

    item = {"weight_class": wc, "red": red_norm, "white": white_norm}

    sched = load_schedule()
    L = sched.get("list", [])
    if position == "top":
        L.insert(0, item)
    else:
        L.append(item)

    save_schedule(sched)
    sync_judging_with_schedule(sched)
    flash(f"Added fight: [{wc}] {red_norm} vs {white_norm} ({position}).", "info")
    return redirect(url_for("schedule"))


@app.post("/schedule/judge_history/update")
def schedule_judge_history_update():
    match_id = (request.form.get("match_id") or "").strip()
    judge_id_raw = (request.form.get("judge_id") or "").strip()
    if not match_id or not judge_id_raw.isdigit():
        flash("Invalid judge update request.", "error")
        return redirect(url_for("schedule"))
    judge_id = int(judge_id_raw)
    if judge_id not in JUDGE_IDS:
        flash("Unknown judge.", "error")
        return redirect(url_for("schedule"))

    sliders = {key: request.form.get(key) for key in CATEGORY_KEYS}
    state, _, _ = get_synced_judging_state()
    history = state.get("history", [])
    target_index = None
    for idx, entry in enumerate(history):
        if entry.get("match_id") == match_id:
            target_index = idx
            break
    if target_index is None:
        flash("Match not found in judging history.", "error")
        return redirect(url_for("schedule"))

    entry = history[target_index]
    entry.setdefault("judges", {})
    entry["judges"][str(judge_id)] = create_judge_record(
        judge_id,
        sliders,
        judge_name=request.form.get("judge_name"),
    )
    normalized_entry, _ = normalize_match(entry)
    if normalized_entry is not None:
        history[target_index] = normalized_entry
    state["history"] = history
    save_judging_state(state)
    flash(f"Updated Judge {judge_id} scorecard.", "info")
    return redirect(url_for("schedule"))


# -------- Judge scoring pages & APIs --------


@app.get("/judge/<int:judge_id>")
def judge_page(judge_id):
    if judge_id not in JUDGE_IDS:
        return "Unknown judge", 404
    state, _, _ = get_synced_judging_state()
    panel_data = build_state_payload(state)
    current_payload = panel_data.get("current")
    current_match = state.get("current") if isinstance(state, dict) else None
    if current_payload and current_match:
        weight_class = current_match.get("weight_class")
        current_payload["red_details"] = robot_display(weight_class, current_match.get("red"))
        current_payload["white_details"] = robot_display(weight_class, current_match.get("white"))
        existing_submission = current_match.get("judges", {}).get(str(judge_id))
        current_payload["existing_submission"] = existing_submission
        current_payload["match_id"] = current_match.get("match_id")
    panel_data["judge_id"] = judge_id
    panel_data["categories"] = CATEGORY_SPECS
    panel_data["judge_labels"] = panel_data.get("judge_labels", JUDGE_LABELS)
    panel_data["judge_ids"] = JUDGE_IDS
    panel_data["api"] = {
        "submit": url_for("judge_submit", judge_id=judge_id),
        "state": url_for("judge_state_api"),
    }
    return render_template(
        "judge.html",
        judge_id=judge_id,
        judge_label=JUDGE_LABELS[judge_id],
        current=current_payload,
        history=panel_data.get("history", []),
        categories=CATEGORY_SPECS,
        judge_labels=panel_data.get("judge_labels", JUDGE_LABELS),
        judge_state_json=panel_data,
        active_judge=judge_id,
    )


@app.get("/judge1")
def judge1_redirect():
    return redirect(url_for("judge_page", judge_id=1))


@app.get("/judge2")
def judge2_redirect():
    return redirect(url_for("judge_page", judge_id=2))


@app.get("/judge3")
def judge3_redirect():
    return redirect(url_for("judge_page", judge_id=3))


@app.get("/api/judge/state")
def judge_state_api():
    history_limit = request.args.get("history", type=int)
    state, _, _ = get_synced_judging_state()
    payload = build_state_payload(state, history_limit=history_limit)
    return jsonify(payload)


@app.post("/api/judge/<int:judge_id>/submit")
def judge_submit(judge_id):
    if judge_id not in JUDGE_IDS:
        return jsonify({"error": "Unknown judge"}), 404
    data = request.get_json(silent=True) or {}
    sliders = data.get("sliders", {})
    judge_name = (data.get("judge_name") or "").strip()
    match_id = data.get("match_id")
    if not judge_name:
        return jsonify({"error": "Judge name required"}), 400
    # unified, conflict-free state fetch
    state, schedule_data, schedule_list = get_synced_judging_state()
    judge_record = create_judge_record(judge_id, sliders, judge_name=judge_name)

    error_payload = {"error": "No active match"}
    error_status = 400

    class StateUpdateAbort(Exception):
        pass

    def mutate_state(current_state):
        nonlocal error_payload, error_status
        current_state, _ = ensure_state_for_schedule(current_state, schedule_list)
        current_match = current_state.get("current") if isinstance(current_state, dict) else None
        if not current_match:
            error_payload = {"error": "No active match"}
            error_status = 400
            raise StateUpdateAbort()
        if match_id and match_id != current_match.get("match_id"):
            error_payload = {"error": "Match has changed"}
            error_status = 409
            raise StateUpdateAbort()

        judges = current_match.setdefault("judges", {})
        judges[str(judge_id)] = judge_record
        normalized_current, _ = normalize_match(current_match)
        current_state["current"] = normalized_current
        return current_state

    try:
        state = update_judging_state(mutate_state)
    except StateUpdateAbort:
        return jsonify(error_payload), error_status

    current_match = state.get("current") if isinstance(state, dict) else None
    summary = current_match.get("summary") if current_match else None
    if summary and summary.get("is_complete"):
        state, schedule_data = finalize_current_match(state, schedule_data)

    payload = build_state_payload(state)
    return jsonify(payload)


# -------- Overlay endpoint for current top match --------
@app.get("/overlay")
def overlay():
    state, _, schedule_list = get_synced_judging_state()
    current_match = state.get("current") if isinstance(state, dict) else None
    if not current_match:
        if not schedule_list:
            return jsonify({"status": "empty"})
        top_card = schedule_list[0]
        wc = top_card.get("weight_class")
        red_name = top_card.get("red")
        white_name = top_card.get("white")
        return jsonify({
            "status": "pending",
            "match_id": None,
            "weight_class": wc,
            "red": robot_display(wc, red_name),
            "white": robot_display(wc, white_name),
            "headline": "Awaiting judges",
            "judges": [],
            "pending_judges": JUDGE_IDS,
        })

    normalized_current, _ = normalize_match(current_match)
    match_data = normalized_current or current_match
    wc = match_data.get("weight_class")
    red_name = match_data.get("red")
    white_name = match_data.get("white")
    summary = match_data.get("summary") or {}
    judge_cards = []
    for card in summary.get("judge_cards", []):
        judge_cards.append({
            "judge_id": card.get("judge_id"),
            "judge_name": card.get("judge_name", ""),
            "winner": card.get("winner"),
            "scoreline": card.get("scoreline"),
            "breakdown": card.get("breakdown"),
            "totals": card.get("totals", {}),
            "submitted_at": card.get("submitted_at"),
        })

    payload = {
        "status": "active",
        "match_id": match_data.get("match_id"),
        "weight_class": wc,
        "headline": summary.get("headline"),
        "winner": summary.get("winner"),
        "winner_name": summary.get("winner_name"),
        "decision": summary.get("decision"),
        "counts": summary.get("counts", {}),
        "is_complete": summary.get("is_complete"),
        "pending_judges": summary.get("pending_judges", []),
        "red": robot_display(wc, red_name),
        "white": robot_display(wc, white_name),
        "judges": judge_cards,
    }
    return jsonify(payload)


@app.get("/robot_card2/<path:wc>/<path:name>")
def robot_card2(wc, name):
    # Robust lookup: trims, case-insensitive, whitespace-collapsed
    wc = (wc or "").strip()
    name_in = (name or "").strip()
    if wc not in WEIGHT_CLASSES:
        return "Bad weight class", 404
    db = load_db(wc)
    robots = (db.get("robots", {}) or {})
    # exact
    info = robots.get(name_in); actual_name = name_in
    # casefold trim
    if not info:
        lower_map = { (k or "").strip().casefold(): k for k in robots.keys() }
        key = name_in.strip().casefold()
        if key in lower_map:
            actual_name = lower_map[key]
            info = robots[actual_name]
    # collapse whitespace + casefold
    if not info:
        import re as _re
        def norm(s): return _re.sub(r"\s+", " ", (s or "")).strip().casefold()
        target = norm(name_in)
        for k in robots.keys():
            if norm(k) == target:
                actual_name = k
                info = robots[k]
                break
    if not info:
        return "Not found", 404
    matches = sorted(info.get("matches", []), key=lambda m: m.get("timestamp", 0), reverse=True)[:50]
    return render_template("robot_card.html", wc=wc, name=actual_name, info=info, matches=matches)

@app.get("/debug/robots/<path:wc>")
def debug_robots(wc):
    wc = (wc or "").strip()
    if wc not in WEIGHT_CLASSES:
        return jsonify({"error":"bad class","classes":WEIGHT_CLASSES}), 400
    db = load_db(wc)
    return jsonify(sorted(list((db.get("robots", {}) or {}).keys())))


# ---------------- Public pages ----------------

@app.get("/SchedulePublic")
def schedule_public():
    state, schedule_data, schedule_list = get_synced_judging_state()
    if not isinstance(schedule_list, list):
        schedule_list = []
    top = schedule_list[0] if schedule_list else None
    # enrich top with metadata
    top_info = None
    if top:
        wc = top.get("weight_class"); red = top.get("red"); white = top.get("white")
        db = load_db(wc); robots = db.get("robots", {})
        r = robots.get(red, {}); w = robots.get(white, {})
        def stats(db, name):
            s = {"wins":0,"losses":0,"draws":0,"ko_wins":0,"ko_losses":0}
            info = db.get("robots",{}).get(name,{})
            for m in info.get("matches",[]):
                res = m.get("result","")
                if res == "Draw": s["draws"]+=1; continue
                robot_is_red = (m.get("red_corner")==name)
                red_win = res.startswith("Red wins")
                is_ko = "KO" in res
                won = (red_win and robot_is_red) or ((not red_win) and (not robot_is_red))
                if won: s["wins"]+=1; s["ko_wins"]+= int(is_ko)
                else: s["losses"]+=1; s["ko_losses"]+= int(is_ko)
            return s
        rs = stats(db, red); ws = stats(db, white)
        top_info = {
            "weight_class": wc,
            "red": {"name": red, "elo": r.get("rating", DEFAULT_RATING), "driver": r.get("driver_name",""), "team": r.get("team_name",""),
                "wins": rs["wins"], "losses": rs["losses"], "draws": rs["draws"], "ko_wins": rs["ko_wins"], "ko_losses": rs["ko_losses"],
                "image": r.get("image", "")},
            "white": {"name": white, "elo": w.get("rating", DEFAULT_RATING), "driver": w.get("driver_name",""), "team": w.get("team_name",""),
                "wins": ws["wins"], "losses": ws["losses"], "draws": ws["draws"], "ko_wins": ws["ko_wins"], "ko_losses": ws["ko_losses"],
                "image": w.get("image", "")},
        }
    # Build enriched schedule list with images for thumbnails
    enriched_schedule = []
    for idx, card in enumerate(schedule_list or []):
        if not isinstance(card, dict):
            continue
        wc = card.get("weight_class")
        red = card.get("red")
        white = card.get("white")
        red_img = ""; white_img = ""
        try:
            db_wc = load_db(wc) if wc in WEIGHT_CLASSES else None
            robots_wc = db_wc.get("robots", {}) if db_wc else {}
            red_img = robots_wc.get(red, {}).get("image", "") if red in robots_wc else ""
            white_img = robots_wc.get(white, {}).get("image", "") if white in robots_wc else ""
        except Exception:
            pass
        enriched_schedule.append({
            "weight_class": wc,
            "red": red,
            "white": white,
            "red_image": red_img,
            "white_image": white_img,
        })
    return render_template(
        "public_schedule.html",
        schedule=enriched_schedule,
        top=top_info,
        judge_panel=build_state_payload(state, history_limit=10),
        judge_labels=JUDGE_LABELS,
        category_specs=CATEGORY_SPECS,
    )

@app.get("/RankingsPublic")
def rankings_public():
    wc = request.args.get("wc", WEIGHT_CLASSES[0])
    if wc not in WEIGHT_CLASSES: wc = WEIGHT_CLASSES[0]
    db = load_db(wc)
    robots = db.get("robots", {}) or {}
    rows = []
    for name, info in robots.items():
        wins=losses=draws=0; ko_wins=ko_losses=0
        for m in info.get("matches", []):
            res = m.get("result","")
            if res == "Draw": draws+=1; continue
            robot_is_red = (m.get("red_corner")==name)
            red_win = res.startswith("Red wins"); is_ko = "KO" in res
            won = (red_win and robot_is_red) or ((not red_win) and (not robot_is_red))
            if won: wins+=1; ko_wins += int(is_ko)
            else: losses+=1; ko_losses += int(is_ko)
        rows.append({
            "name": name,
            "rating": info.get("rating", DEFAULT_RATING),
            "wins": wins, "losses": losses, "draws": draws,
            "ko_wins": ko_wins, "ko_losses": ko_losses,
            "driver": info.get("driver_name",""),
            "team": info.get("team_name",""),
            "image": info.get("image","")
        })
    rows.sort(key=lambda r: r["rating"], reverse=True)
    # rank index
    for i, r in enumerate(rows, start=1): r["rank"] = i
    return render_template("public_rankings.html", wc=wc, rows=rows)


@app.get("/robot_card/<path:wc>/<path:name>")
def robot_card(wc, name):
    wc = (wc or "").strip()
    name_in = (name or "").strip()
    if wc not in WEIGHT_CLASSES:
        return "Bad weight class", 404
    db = load_db(wc)
    robots = (db.get("robots", {}) or {})
    # 1) exact match
    info = robots.get(name_in)
    actual_name = name_in
    # 2) case-insensitive + trim
    if not info:
        lower_map = {k.casefold().strip(): k for k in robots.keys()}
        key = name_in.casefold().strip()
        if key in lower_map:
            actual_name = lower_map[key]
            info = robots[actual_name]
    # 3) collapse whitespace and compare case-insensitively
    if not info:
        import re as _re
        def norm(s): return _re.sub(r"\s+", " ", (s or "")).strip().casefold()
        target = norm(name_in)
        for k in robots.keys():
            if norm(k) == target:
                actual_name = k
                info = robots[k]
                break
    if not info:
        return "Not found", 404
    matches = sorted(info.get("matches", []), key=lambda m: m["timestamp"], reverse=True)[:50]
    return render_template("robot_card.html", wc=wc, name=actual_name, info=info, matches=matches)


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8000)
