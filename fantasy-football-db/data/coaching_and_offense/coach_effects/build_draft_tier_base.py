import csv, collections

# Load players.csv for draft info by gsis_id
draft_info = {}
with open('/tmp/pfr/players.csv') as f:
    for row in csv.DictReader(f):
        draft_info[row['gsis_id']] = row

def draft_tier(gsis_id):
    info = draft_info.get(gsis_id)
    if info is None:
        return 'Unknown'
    rd = info.get('draft_round', '')
    if rd == '' or rd is None:
        return 'Day3+UDFA'  # undrafted
    rd = int(rd)
    if rd == 1:
        return 'Day1'
    elif rd in (2, 3):
        return 'Day2'
    else:
        return 'Day3+UDFA'

# Player-team-season
pts = {}
with open('/tmp/pfr/player_team_season.csv') as f:
    for row in csv.DictReader(f):
        pts[(row['player_id'], int(row['season']))] = row['team']

def base_tier_str(t):
    return t[:-1] if t.endswith('*') else t

TIER_SCORE = {
    'Below Replacement Level': 0, 'Mid/replacement': 1, 'Starter': 2,
    'Star': 3, 'Superstar': 4, 'League Winner': 5,
}

POS_ROLE = {'QB': 'QB', 'RB': 'RB', 'WR': 'WR', 'TE': 'TE'}

player_seasons = []
with open('/tmp/pfr/all_rankings_tiered.csv') as f:
    for row in csv.DictReader(f):
        pos = row['position']
        if pos not in POS_ROLE:
            continue
        tier = base_tier_str(row['tier'])
        if tier == 'Uncategorized (<4 games)' or tier not in TIER_SCORE:
            continue
        season = int(row['season'])
        team = pts.get((row['player_id'], season))
        if team is None:
            continue
        player_seasons.append({
            'player_id': row['player_id'], 'display_name': row['display_name'],
            'season': season, 'position': pos, 'team': team,
            'tier_score': TIER_SCORE[tier], 'ppg': float(row['ppg']),
            'draft_tier': draft_tier(row['player_id']),
        })

print('total qualifying player-seasons:', len(player_seasons))

# Draft tier coverage
dt_counts = collections.Counter(p['draft_tier'] for p in player_seasons)
print('draft tier distribution (player-seasons):', dt_counts)

# League baseline: average tier_score by (position, draft_tier) -- computed at PLAYER level
# (average across a player's career under ANY coach, then averaged across players)
player_career_avg = collections.defaultdict(list)  # (position, draft_tier) -> list of per-player avg tier_score
by_player = collections.defaultdict(list)
for p in player_seasons:
    by_player[(p['player_id'], p['position'])].append(p)

for (pid, pos), seasons in by_player.items():
    dt = seasons[0]['draft_tier']
    if dt == 'Unknown':
        continue
    avg_score = sum(s['tier_score'] for s in seasons) / len(seasons)
    avg_ppg = sum(s['ppg'] for s in seasons) / len(seasons)
    player_career_avg[(pos, dt)].append((avg_score, avg_ppg))

print('\nLeague baseline: avg career tier-score and PPG by (position, draft tier):')
baseline = {}
for (pos, dt), vals in sorted(player_career_avg.items()):
    n = len(vals)
    avg_score = sum(v[0] for v in vals) / n
    avg_ppg = sum(v[1] for v in vals) / n
    baseline[(pos, dt)] = {'n_players': n, 'avg_tier_score': avg_score, 'avg_ppg': avg_ppg}
    print(f'  {pos} {dt}: n={n}, avg_tier_score={avg_score:.3f}, avg_ppg={avg_ppg:.2f}')

import json
json.dump(player_seasons, open('/tmp/pfr/coach_effects/player_seasons_with_draft.json', 'w'))
# json can't have tuple keys -- rewrite with string keys
baseline_str = {f'{pos}|{dt}': v for (pos, dt), v in baseline.items()}
json.dump(baseline_str, open('/tmp/pfr/coach_effects/draft_tier_baseline.json', 'w'))
