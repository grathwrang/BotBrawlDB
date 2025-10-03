import schedule_engine


def test_has_unscheduled_fresh_opponent_recognizes_available_pair():
    db = {
        'feather': {
            'robots': {
                'Alpha': {'present': True, 'rating': 1000},
                'Bravo': {'present': True, 'rating': 1010},
                'Charlie': {'present': True, 'rating': 980},
                'Delta': {'present': True, 'rating': 990},
            },
            'history': [
                {'red_corner': 'Alpha', 'white_corner': 'Bravo'},
                {'red_corner': 'Alpha', 'white_corner': 'Charlie'},
            ],
        }
    }

    hist = schedule_engine.build_history_counts(db)
    present = schedule_engine.present_by_class(db)
    tonight = {(wc, r): 0 for wc, robots in present.items() for r in robots}
    used_pairs = set()

    assert schedule_engine.has_unscheduled_fresh_opponent(
        'feather', 'Alpha', present, hist, tonight, used_pairs, desired_per_robot=1
    )

    used_pairs.add(('feather', 'Alpha', 'Delta'))
    assert not schedule_engine.has_unscheduled_fresh_opponent(
        'feather', 'Alpha', present, hist, tonight, used_pairs, desired_per_robot=1
    )


def test_scheduler_defers_repeats_until_fresh_pairs_exhausted():
    db = {
        'feather': {
            'robots': {
                'Alpha': {'present': True, 'rating': 1000},
                'Bravo': {'present': True, 'rating': 1020},
                'Charlie': {'present': True, 'rating': 980},
                'Delta': {'present': True, 'rating': 1010},
            },
            'history': [
                {'red_corner': 'Alpha', 'white_corner': 'Bravo'},
                {'red_corner': 'Alpha', 'white_corner': 'Charlie'},
                {'red_corner': 'Bravo', 'white_corner': 'Delta'},
                {'red_corner': 'Charlie', 'white_corner': 'Delta'},
            ],
        }
    }

    desired = 2
    schedule = schedule_engine.generate(
        desired_per_robot=desired, interleave=True, db_by_class=db, seed=5
    )

    hist = schedule_engine.build_history_counts(db)
    present = schedule_engine.present_by_class(db)
    tonight = {(wc, r): 0 for wc, robots in present.items() for r in robots}
    used_pairs = set()

    repeat_seen = False
    for match in schedule:
        wc = match['weight_class']
        red = match['red']
        white = match['white']
        pair = tuple(sorted([red, white]))
        met = hist.get((wc, *pair), 0)

        if met > 0:
            repeat_seen = True
            fresh_options = []
            for i in range(len(present[wc])):
                for j in range(i + 1, len(present[wc])):
                    a = present[wc][i]
                    b = present[wc][j]
                    if tonight[(wc, a)] >= desired or tonight[(wc, b)] >= desired:
                        continue
                    candidate = tuple(sorted([a, b]))
                    if (wc, *candidate) in used_pairs:
                        continue
                    if hist.get((wc, *candidate), 0) == 0:
                        fresh_options.append(candidate)
            assert not fresh_options, (
                f"Repeat pairing {pair} scheduled before exhausting fresh options: {fresh_options}"
            )

        tonight[(wc, red)] += 1
        tonight[(wc, white)] += 1
        used_pairs.add((wc, *pair))

    assert repeat_seen, "Expected the scenario to include at least one repeat pairing"
