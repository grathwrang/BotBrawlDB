from flask import Flask, render_template, request, redirect, url_for, jsonify, send_file, flash
import time, os, json
from werkzeug.utils import secure_filename
from elo import get_expected, get_k_for_robot, DEFAULT_RATING, DEFAULT_K, KO_WEIGHT
from storage import load_db, save_db, DB_FILES, load_all, load_schedule, save_schedule, export_stats_csv
from schedule_engine import generate

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "static", "uploads")
ALLOWED_EXT = {"png","jpg","jpeg","gif","webp"}
# ensure uploads dir exists at runtime (Windows/Linux)
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY","devkey")

WEIGHT_CLASSES = list(DB_FILES.keys())
VALID_RESULTS = {"Red wins JD", "Red wins KO", "White wins JD", "White wins KO", "Draw"}

@app.template_filter('datetimefromts')
def datetimefromts(ts):
    try:
        import datetime
        return datetime.datetime.fromtimestamp(int(ts)).strftime('%Y-%m-%d %H:%M:%S')
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
        save_schedule(sched); return redirect(url_for("schedule"))
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
    wc = request.form.get("wc"); name = request.form.get("name"); present = request.form.get("present") == "1"
    db = load_db(wc)
    if name in db.get("robots", {}): db["robots"][name]["present"]=present; save_db(wc, db)
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
        db["history"] = [
            m
            for m in db.get("history", [])
            if m.get("red_corner") != name and m.get("white_corner") != name
        ]
        for robot in db.get("robots", {}).values():
            matches = robot.get("matches", []) or []
            robot["matches"] = [
                m for m in matches
                if m.get("red_corner") != name and m.get("white_corner") != name
            ]
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
    sched = load_schedule().get("list", [])
    all_dbs = load_all()
    presence = []
    for w, db in all_dbs.items():
        for name, info in (db.get("robots", {}) or {}).items():
            presence.append({"weight": w, "robot": name, "present": "Yes" if info.get("present") else ""})
    top = sched[0] if sched else None
    return render_template(
        "schedule.html",
        schedule=sched,
        presence=presence,
        top=top,
        weight_classes=WEIGHT_CLASSES  # <--- add this
    )


@app.post("/schedule/generate")
def schedule_generate():
    try: per = int(request.form.get("matchesPerRobot","1"))
    except Exception: per = 1
    interleave = request.form.get("interleave") == "1"
    sched_list = generate(desired_per_robot=per, interleave=interleave, db_by_class=load_all())
    save_schedule({"list": sched_list}); return redirect(url_for("schedule"))

@app.post("/schedule/clear")
def schedule_clear():
    save_schedule({"list": []}); return redirect(url_for("schedule"))

@app.post("/schedule/move")
def schedule_move():
    idx = int(request.form.get("index","-1")); direction = int(request.form.get("direction","0"))
    sched = load_schedule(); L = sched.get("list", [])
    if 0 <= idx < len(L):
        newi = idx + direction
        if 0 <= newi < len(L): L[idx], L[newi] = L[newi], L[idx]; save_schedule(sched)
    return redirect(url_for("schedule"))

@app.post("/schedule/delete")
def schedule_delete():
    idx = int(request.form.get("index","-1")); sched = load_schedule(); L = sched.get("list", [])
    if 0 <= idx < len(L): L.pop(idx); save_schedule(sched)
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
    save_schedule(sched); return redirect(url_for("schedule"))

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
    flash(f"Added fight: [{wc}] {red_norm} vs {white_norm} ({position}).", "info")
    return redirect(url_for("schedule"))


# -------- Overlay endpoint for current top match --------
@app.get("/overlay")
def overlay():
    sched = load_schedule().get("list", [])
    if not sched:
        return jsonify({"status":"empty"})
    top = sched[0]
    wc = top.get("weight_class"); red = top.get("red"); white = top.get("white")
    db = load_db(wc)
    robots = db.get("robots", {})
    r = robots.get(red, {}); w = robots.get(white, {})
    r_stats = robot_stats(db, red); w_stats = robot_stats(db, white)
    payload = {
        "weight_class": wc,
        "red": {"name": red, "elo": r.get("rating", DEFAULT_RATING), "driver": r.get("driver_name",""), "team": r.get("team_name",""), "wins": r_stats["wins"], "losses": r_stats["losses"], "draws": r_stats["draws"], "ko_wins": r_stats["ko_wins"], "ko_losses": r_stats["ko_losses"]},
        "white": {"name": white, "elo": w.get("rating", DEFAULT_RATING), "driver": w.get("driver_name",""), "team": w.get("team_name",""), "wins": w_stats["wins"], "losses": w_stats["losses"], "draws": w_stats["draws"], "ko_wins": w_stats["ko_wins"], "ko_losses": w_stats["ko_losses"]}
    }
    # JSON is programmatically digestible; also render pretty text if desired:
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
    sched = load_schedule().get("list", [])
    top = sched[0] if sched else None
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
                    "wins": rs["wins"], "losses": rs["losses"], "draws": rs["draws"], "ko_wins": rs["ko_wins"], "ko_losses": rs["ko_losses"]},
            "white": {"name": white, "elo": w.get("rating", DEFAULT_RATING), "driver": w.get("driver_name",""), "team": w.get("team_name",""),
                    "wins": ws["wins"], "losses": ws["losses"], "draws": ws["draws"], "ko_wins": ws["ko_wins"], "ko_losses": ws["ko_losses"]},
        }
    return render_template("public_schedule.html", schedule=sched, top=top_info)

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

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8000)



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
