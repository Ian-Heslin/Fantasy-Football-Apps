import json, csv, collections, statistics
from scipy.stats import ttest_1samp, ttest_ind

player_seasons = json.load(open('/tmp/pfr/coach_effects/player_seasons_with_draft.json'))
baseline = json.load(open('/tmp/pfr/coach_effects/draft_tier_baseline.json'))

coach_tbl = collections.defaultdict(list)
with open('/tmp/pfr/coach_effects/coach_table.csv') as f:
    for row in csv.DictReader(f):
        coach_tbl[(int(row['season']), row['team'], row['role'])].append(row['coach_name'])

POS_ROLE = {'QB': 'QB', 'RB': 'RB', 'WR': 'WR', 'TE': 'TE'}

# Build per-player career average tier_score/ppg + draft tier (player-level, across ALL seasons/coaches -- the "true talent" baseline)
by_player = collections.defaultdict(list)
for p in player_seasons:
    by_player[(p['player_id'], p['position'])].append(p)

# Build population distributions per (pos, draft_tier) of PLAYER-LEVEL avg tier score (for t-tests)
pop_dist = collections.defaultdict(list)  # (pos, draft_tier) -> list of (player_id, avg_tier_score)
for (pid, pos), seasons in by_player.items():
    dt = seasons[0]['draft_tier']
    if dt == 'Unknown':
        continue
    avg_score = sum(s['tier_score'] for s in seasons) / len(seasons)
    pop_dist[(pos, dt)].append((pid, avg_score))

# ============================================================
# ANALYSIS: for each (coach, role, position, draft_tier), collect DISTINCT players
# coached by them at that position, and their player-level avg tier_score (across ALL
# their seasons under that specific coach, not their whole career -- i.e. "how did this
# player perform while playing for this coach").
# ============================================================
def player_avg_under_coach(role_key_builder):
    # coach -> position -> draft_tier -> {player_id: [scores while under this coach]}
    data = collections.defaultdict(lambda: collections.defaultdict(lambda: collections.defaultdict(lambda: collections.defaultdict(list))))
    for p in player_seasons:
        pos = p['position']
        dt = p['draft_tier']
        if dt == 'Unknown':
            continue
        role = role_key_builder(pos)
        names = coach_tbl.get((p['season'], p['team'], role), [])
        for name in names:
            data[name][pos][dt][p['player_id']].append(p['tier_score'])
    return data

def report(data, filename, min_players=5):
    rows_out = []
    for coach, pos_dict in data.items():
        for pos, dt_dict in pos_dict.items():
            for dt, players in dt_dict.items():
                n = len(players)
                if n < min_players:
                    continue
                player_avgs = [sum(v)/len(v) for v in players.values()]
                coach_mean = statistics.mean(player_avgs)
                pop = pop_dist.get((pos, dt), [])
                pop_scores = [s for pid, s in pop]
                base_mean = baseline[f'{pos}|{dt}']['avg_tier_score']
                if len(player_avgs) >= 2 and len(pop_scores) >= 2:
                    try:
                        _, p_val = ttest_1samp(player_avgs, base_mean)
                    except Exception:
                        p_val = float('nan')
                else:
                    p_val = float('nan')
                rows_out.append((coach, pos, dt, n, round(coach_mean, 3), round(base_mean, 3), round(coach_mean - base_mean, 3), p_val))
    rows_out.sort(key=lambda x: (x[7] if x[7] == x[7] else 1))
    with open(filename, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['coach_name', 'position', 'draft_tier', 'n_distinct_players', 'coach_avg_tier_score',
                     'league_baseline_tier_score', 'overperformance', 'p_value'])
        for row in rows_out:
            w.writerow(row)
    return rows_out

pos_data = player_avg_under_coach(lambda pos: POS_ROLE[pos])
oc_data = player_avg_under_coach(lambda pos: 'OC')
hc_data = player_avg_under_coach(lambda pos: 'HC')

pos_out = report(pos_data, '/tmp/pfr/coach_effects/draft_tier_position_coach.csv', min_players=5)
oc_out = report(oc_data, '/tmp/pfr/coach_effects/draft_tier_oc.csv', min_players=5)
hc_out = report(hc_data, '/tmp/pfr/coach_effects/draft_tier_hc.csv', min_players=5)

for label, out in [('Position coaches', pos_out), ('OCs', oc_out), ('HCs', hc_out)]:
    n_tests = len(out)
    bonf = 0.05 / n_tests if n_tests else 1
    sig = [r for r in out if r[7] == r[7] and r[7] < 0.05]
    sig_bonf = [r for r in out if r[7] == r[7] and r[7] < bonf]
    print(f'\n{label}: {n_tests} tested (min 5 players/bucket), {len(sig)} at p<0.05, Bonferroni {bonf:.5f} -> {len(sig_bonf)} survive')
    print('Top 15 by overperformance among p<0.05:')
    for r in sorted(sig, key=lambda x: -x[6])[:15]:
        print(' ', r)

print('\n\n=== Day2/Day3+UDFA only, top overperformers (p<0.05, any n>=5) ===')
for label, out in [('Position coaches', pos_out), ('OCs', oc_out), ('HCs', hc_out)]:
    late = [r for r in out if r[2] in ('Day2','Day3+UDFA') and r[7]==r[7] and r[7]<0.05]
    late.sort(key=lambda x: -x[6])
    print(f'\n{label} (late-round specific):')
    for r in late[:15]:
        print(' ', r)
