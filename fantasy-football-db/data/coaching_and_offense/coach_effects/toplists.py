import csv

def load(fn):
    return list(csv.DictReader(open(fn)))

def top(rows, ratekey, nkey, n_min, top_n=10):
    rows = [r for r in rows if int(r[nkey]) >= n_min]
    rows.sort(key=lambda r: -float(r[ratekey]))
    return rows[:top_n]

print("=== TOP position coaches by superstar-player-rate (min 15 distinct players) ===")
for r in top(load('/tmp/pfr/coach_effects/position_coach_superstar_playerlevel.csv'), 'superstar_player_rate', 'n_distinct_players', 15):
    print(r['coach_name'], r['position'], r['n_distinct_players'], r['n_ever_superstar'], f"{float(r['superstar_player_rate']):.1%}", 'base', f"{float(r['league_base_rate']):.1%}", 'p=', r['p_value'])

print("\n=== TOP OCs by superstar-player-rate (min 15 distinct players) ===")
for r in top(load('/tmp/pfr/coach_effects/oc_superstar_playerlevel.csv'), 'superstar_player_rate', 'n_distinct_players', 15):
    print(r['coach_name'], r['position'], r['n_distinct_players'], r['n_ever_superstar'], f"{float(r['superstar_player_rate']):.1%}", 'base', f"{float(r['league_base_rate']):.1%}", 'p=', r['p_value'])

print("\n=== TOP HCs by superstar-player-rate (min 15 distinct players) ===")
for r in top(load('/tmp/pfr/coach_effects/hc_superstar_playerlevel.csv'), 'superstar_player_rate', 'n_distinct_players', 15):
    print(r['coach_name'], r['position'], r['n_distinct_players'], r['n_ever_superstar'], f"{float(r['superstar_player_rate']):.1%}", 'base', f"{float(r['league_base_rate']):.1%}", 'p=', r['p_value'])

print("\n=== TOP position coaches by breakout-rate (min 10 distinct candidates) ===")
for r in top(load('/tmp/pfr/coach_effects/position_coach_breakout_playerlevel.csv'), 'breakout_player_rate', 'n_distinct_candidates', 10):
    print(r['coach_name'], r['position'], r['n_distinct_candidates'], r['n_ever_broke_out'], f"{float(r['breakout_player_rate']):.1%}", 'base', f"{float(r['league_base_rate']):.1%}", 'p=', r['p_value'])
