import random
from elo import DEFAULT_RATING


def has_unscheduled_fresh_opponent(wc, robot, present, hist, tonight, used_pairs, desired_per_robot):
    """Return True if *robot* still has an opponent it has never faced available tonight."""
    if tonight.get((wc, robot), 0) >= desired_per_robot:
        return False
    for opponent in present.get(wc, []):
        if opponent == robot:
            continue
        if tonight.get((wc, opponent), 0) >= desired_per_robot:
            continue
        pair = tuple(sorted([robot, opponent]))
        if (wc, *pair) in used_pairs:
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
def generate(desired_per_robot=1, interleave=True, db_by_class=None, seed=None):
    if seed is not None: random.seed(seed)
    if not db_by_class: return []
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
        if all(c>=desired_per_robot for c in tonight.values()): break
        C=candidates()
        if not C: break
        if not interleave:
            best={}
            for c in C:
                wc=c[5]
                if wc not in best or c<best[wc]: best[wc]=c
            chosen=min(best.values())
        else:
            chosen=min(C)
        _,_,_,_,_,_,wc,a,b=chosen
        red,white=(a,b) if random.random()<0.5 else (b,a)
        sched.append({"weight_class":wc,"red":red,"white":white})
        tonight[(wc,a)]+=1; tonight[(wc,b)]+=1; used_pairs.add((wc,*sorted([a,b]))); last={a,b}
    return sched
