import schedule_engine


def test_generate_loads_db_when_not_provided(monkeypatch):
    sample_db = {
        "feather": {
            "robots": {
                "Alpha": {"present": True, "rating": 1000},
                "Bravo": {"present": True, "rating": 1000},
            },
            "history": [],
        }
    }

    calls = {"count": 0}

    def fake_load_all():
        calls["count"] += 1
        return sample_db

    monkeypatch.setattr(schedule_engine, "_load_all_dbs", fake_load_all)

    schedule = schedule_engine.generate(seed=1)

    assert calls["count"] == 1
    assert len(schedule) == 1
    match = schedule[0]
    assert match["weight_class"] == "feather"
    assert {match["red"], match["white"]} == {"Alpha", "Bravo"}


def test_has_unscheduled_fresh_opponent_recognizes_available_pair():
    db = {
        'feather': {
            'robots': {
                'Alpha': {'present': True, 'rating': 1000},
                'Bravo': {'present': True, 'rating': 1010},
                'Charlie': {'present': True, 'rating': 980},
                'Delta': {'present': True, 'rating': 990},
            },
            "history": [],
        }
    }

    calls = {"count": 0}

    def fake_load_all():
        calls["count"] += 1
        return sample_db

    monkeypatch.setattr(schedule_engine, "_load_all_dbs", fake_load_all)

    schedule = schedule_engine.generate(seed=1)

    assert calls["count"] == 1
    assert len(schedule) == 1
    match = schedule[0]
    assert match["weight_class"] == "feather"
    assert {match["red"], match["white"]} == {"Alpha", "Bravo"}


def test_generate_avoids_history_and_repeats():
    db = {
        "feather": {
            "robots": {
                "Alpha": {"present": True},
                "Bravo": {"present": True},
                "Charlie": {"present": True},
                "Delta": {"present": True},
            },
            "history": [
                {"red_corner": "Alpha", "white_corner": "Bravo"},
                {"red_corner": "Charlie", "white_corner": "Delta"},
            ],
        }
    }

    schedule = schedule_engine.generate(db_by_class=db, seed=2)

    scheduled_pairs = [frozenset((match["red"], match["white"])) for match in schedule]

    assert all(pair not in {frozenset({"Alpha", "Bravo"}), frozenset({"Charlie", "Delta"})} for pair in scheduled_pairs)
    assert len(scheduled_pairs) == len(set(scheduled_pairs)), "No pair should repeat in a single night"


def test_generate_enforces_cooldown_spacing():
    robots = {
        name: {"present": True}
        for name in ["Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot", "Gamma", "Hotel"]
    }
    db = {
        "feather": {
            "robots": robots,
            "history": [],
        }
    }

    schedule = schedule_engine.generate(db_by_class=db, seed=3)

    assert len(schedule) == 4, "With eight robots only four matches fit under cooldown constraints"

    last_seen = {}
    for index, match in enumerate(schedule):
        red = match["red"]
        white = match["white"]
        for robot in (red, white):
            if robot in last_seen:
                assert index - last_seen[robot] > schedule_engine.COOLDOWN_MATCHES
            last_seen[robot] = index

    assert len({frozenset((m["red"], m["white"])) for m in schedule}) == len(schedule)
    assert len({m["red"] for m in schedule}.union({m["white"] for m in schedule})) == 8
