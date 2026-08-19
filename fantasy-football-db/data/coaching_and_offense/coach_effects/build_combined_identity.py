import json, csv, collections, statistics
from scipy.stats import ttest_1samp, ttest_ind

player_seasons = json.load(open('/tmp/pfr/coach_effects/player_seasons_with_draft.json'))
baseline = json.load(open('/tmp/pfr/coach_effects/draft_tier_baseline.json'))

coach_rows = list(csv.DictReader(open('/tmp/pfr/coach_effects/coach_table.csv')))

# Build: coach_name -> set of (season, team) where role in (OC, HC)  ["offensive command tenure"]
tenure = collections.defaultdict(set)
role_detail = collections.defaultdict(list)  # coach_name -> list of (season, team, role)
for row in coach_rows:
    if row['role'] in ('OC', 'HC'):
        tenure[row['coach_name']].add((int(row['season']), row['team']))
        role_detail[row['coach_name']].append((int(row['season']), row['team'], row['role']))

# Index player_seasons by (season, team) -> list of player dicts
by_team_season = collections.defaultdict(list)
for p in player_seasons:
    by_team_season[(p['season'], p['team'])].append(p)

def expected_tier_score(pos, dt):
    if dt == 'Unknown':
        return None
    return baseline[f'{pos}|{dt}']['avg_tier_score']

# For each coach's combined tenure, gather distinct skill players and their avg (actual - expected) tier score
results = []
for coach, seasons_teams in tenure.items():
    player_scores = collections.defaultdict(list)  # player_id -> list of (tier_score, expected)
    player_meta = {}
    for (season, team) in seasons_teams:
        for p in by_team_season.get((season, team), []):
            exp = expected_tier_score(p['position'], p['draft_tier'])
            if exp is None:
                continue
            player_scores[p['player_id']].append((p['tier_score'], exp))
            player_meta[p['player_id']] = (p['display_name'], p['position'], p['draft_tier'])
    if not player_scores:
        continue
    diffs = []
    for pid, vals in player_scores.items():
        avg_actual = sum(v[0] for v in vals) / len(vals)
        avg_exp = sum(v[1] for v in vals) / len(vals)
        diffs.append(avg_actual - avg_exp)
    n = len(diffs)
    mean_diff = statistics.mean(diffs)
    if n >= 2 and statistics.pstdev(diffs) > 0:
        try:
            _, p_val = ttest_1samp(diffs, 0)
        except Exception:
            p_val = float('nan')
    else:
        p_val = float('nan')
    n_oc_seasons = len(set(s for s,t,r in role_detail[coach] if r=='OC'))
    n_hc_seasons = len(set(s for s,t,r in role_detail[coach] if r=='HC'))
    results.append((coach, n, round(mean_diff,3), p_val, n_oc_seasons, n_hc_seasons))

results.sort(key=lambda x: (x[3] if x[3]==x[3] else 1))
with open('/tmp/pfr/coach_effects/combined_oc_hc_overperformance.csv', 'w', newline='') as f:
    w = csv.writer(f)
    w.writerow(['coach_name', 'n_distinct_skill_players', 'avg_overperformance_vs_draft_tier_expected',
                'p_value', 'n_seasons_as_OC', 'n_seasons_as_HC'])
    for row in results:
        w.writerow(row)

qualified = [r for r in results if r[1] >= 15]
n_tests = len(qualified)
bonf = 0.05/n_tests if n_tests else 1
sig = [r for r in qualified if r[3]==r[3] and r[3] < 0.05]
sig_bonf = [r for r in qualified if r[3]==r[3] and r[3] < bonf]
print(f'Coaches with >=15 distinct skill players across combined OC+HC tenure: {n_tests}')
print(f'p<0.05: {len(sig)}, Bonferroni thresh {bonf:.5f} -> {len(sig_bonf)} survive')
print('\nTop 20 by overperformance (all n>=15, regardless of significance):')
top20 = sorted(qualified, key=lambda x: -x[2])[:20]
for r in top20:
    print(' ', r)
print('\nBottom 10 (worst overperformance):')
for r in sorted(qualified, key=lambda x: x[2])[:10]:
    print(' ', r)
