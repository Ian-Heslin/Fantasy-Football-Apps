import csv, collections

pts = {}
with open('/tmp/pfr/player_team_season.csv') as f:
    for row in csv.DictReader(f):
        pts[(row['player_id'], int(row['season']))] = row['team']

coach_tbl = collections.defaultdict(list)
with open('/tmp/pfr/coach_effects/coach_table.csv') as f:
    for row in csv.DictReader(f):
        coach_tbl[(int(row['season']), row['team'], row['role'])].append(row['coach_name'])

def base_tier(t):
    return t[:-1] if t.endswith('*') else t
SUPERSTAR_TIERS = {'Superstar', 'League Winner'}

player_seasons = []
with open('/tmp/pfr/all_rankings_tiered.csv') as f:
    for row in csv.DictReader(f):
        pos = row['position']
        if pos not in ('QB','RB','WR','TE'):
            continue
        tier = base_tier(row['tier'])
        if tier == 'Uncategorized (<4 games)':
            continue
        season = int(row['season'])
        team = pts.get((row['player_id'], season))
        if team is None:
            continue
        player_seasons.append({
            'player_id': row['player_id'], 'display_name': row['display_name'], 'season': season,
            'position': pos, 'team': team, 'is_superstar': tier in SUPERSTAR_TIERS,
        })

def inspect(name, pos, role_key):
    matches = []
    for r in player_seasons:
        if r['position'] != pos: continue
        names = coach_tbl.get((r['season'], r['team'], role_key), [])
        if name in names:
            matches.append(r)
    distinct_players = set(m['display_name'] for m in matches)
    superstar_matches = [m for m in matches if m['is_superstar']]
    distinct_superstar_players = set(m['display_name'] for m in superstar_matches)
    print(f'\n=== {name} ({role_key}, {pos}) ===')
    print(f'total player-seasons: {len(matches)}, distinct players: {len(distinct_players)}')
    print(f'superstar-tier seasons: {len(superstar_matches)}, distinct superstar players: {len(distinct_superstar_players)}')
    print('superstar player-seasons:', sorted([(m['display_name'], m['season']) for m in superstar_matches]))

inspect('James Saxon', 'RB', 'RB')
inspect('Al Saunders', 'RB', 'OC')
inspect('Cam Cameron', 'RB', 'OC')
inspect('Kyle Shanahan', 'TE', 'HC')
inspect('Sean McDermott', 'QB', 'HC')
inspect('Tom Melvin', 'TE', 'TE')
