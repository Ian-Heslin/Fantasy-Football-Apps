import json, csv, collections

player_seasons = json.load(open('/tmp/pfr/coach_effects/player_seasons_with_draft.json'))
baseline = json.load(open('/tmp/pfr/coach_effects/draft_tier_baseline.json'))
coach_rows = list(csv.DictReader(open('/tmp/pfr/coach_effects/coach_table.csv')))

tenure = set()
for row in coach_rows:
    if row['coach_name'] == 'Kyle Shanahan' and row['role'] in ('OC', 'HC'):
        tenure.add((int(row['season']), row['team'], row['role']))

print('Kyle Shanahan tenure (season, team, role):')
for t in sorted(tenure):
    print(' ', t)

by_team_season = collections.defaultdict(list)
for p in player_seasons:
    by_team_season[(p['season'], p['team'])].append(p)

seasons_teams = set((s,t) for s,t,r in tenure)
player_scores = collections.defaultdict(list)
player_meta = {}
for (season, team) in seasons_teams:
    for p in by_team_season.get((season, team), []):
        exp = baseline.get(f"{p['position']}|{p['draft_tier']}", {}).get('avg_tier_score')
        if exp is None:
            continue
        player_scores[p['player_id']].append({'season': season, 'tier_score': p['tier_score'], 'ppg': p['ppg'], 'expected': exp})
        player_meta[p['player_id']] = (p['display_name'], p['position'], p['draft_tier'])

rows = []
for pid, seasons in player_scores.items():
    name, pos, dt = player_meta[pid]
    avg_actual = sum(s['tier_score'] for s in seasons) / len(seasons)
    avg_exp = seasons[0]['expected']
    avg_ppg = sum(s['ppg'] for s in seasons) / len(seasons)
    seasons_list = sorted(s['season'] for s in seasons)
    rows.append((name, pos, dt, seasons_list, round(avg_actual,2), round(avg_exp,2), round(avg_actual-avg_exp,2), round(avg_ppg,1)))

rows.sort(key=lambda r: -r[6])
print(f'\n{len(rows)} distinct skill-position players under Kyle Shanahan (OC or HC), sorted by overperformance:')
for r in rows:
    print(r)

with open('/tmp/pfr/coach_effects/shanahan_worked_example.csv', 'w', newline='') as f:
    w = csv.writer(f)
    w.writerow(['player','position','draft_tier','seasons_under_shanahan','avg_tier_score_under_him','draft_tier_expected_tier_score','overperformance','avg_ppg_under_him'])
    for r in rows:
        w.writerow([r[0], r[1], r[2], ';'.join(map(str,r[3])), r[4], r[5], r[6], r[7]])
