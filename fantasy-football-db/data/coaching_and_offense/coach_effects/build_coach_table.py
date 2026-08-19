import json, re, csv, collections

TEAM_MAP = {
    'Arizona Cardinals': 'ARI', 'Atlanta Falcons': 'ATL', 'Baltimore Ravens': 'BAL',
    'Buffalo Bills': 'BUF', 'Carolina Panthers': 'CAR', 'Chicago Bears': 'CHI',
    'Cincinnati Bengals': 'CIN', 'Cleveland Browns': 'CLE', 'Dallas Cowboys': 'DAL',
    'Denver Broncos': 'DEN', 'Detroit Lions': 'DET', 'Green Bay Packers': 'GB',
    'Houston Texans': 'HOU', 'Indianapolis Colts': 'IND', 'Jacksonville Jaguars': 'JAX',
    'Kansas City Chiefs': 'KC', 'Las Vegas Raiders': 'LV', 'Oakland Raiders': 'LV',
    'Los Angeles Chargers': 'LAC', 'San Diego Chargers': 'LAC',
    'Los Angeles Rams': 'LA', 'St. Louis Rams': 'LA',
    'Miami Dolphins': 'MIA', 'Minnesota Vikings': 'MIN', 'New England Patriots': 'NE',
    'New Orleans Saints': 'NO', 'New York Giants': 'NYG', 'New York Jets': 'NYJ',
    'Philadelphia Eagles': 'PHI', 'Pittsburgh Steelers': 'PIT', 'San Francisco 49ers': 'SF',
    'Seattle Seahawks': 'SEA', 'Tampa Bay Buccaneers': 'TB', 'Tennessee Titans': 'TEN',
    'Washington Redskins': 'WAS', 'Washington Football Team': 'WAS', 'Washington Commanders': 'WAS',
}

rows = [json.loads(l) for l in open('/tmp/pfr/coaching/staff_rows.jsonl')]

def is_assistant_like(role_lower):
    bad_words = ['assistant', 'quality control', 'intern', 'consultant', 'analyst',
                 'senior offensive assistant', 'senior defensive assistant']
    return any(role_lower.startswith(w) for w in ['assistant']) or 'quality control' in role_lower or 'intern' in role_lower or role_lower.startswith('senior')

def classify(section, role):
    r = role.lower().strip()
    cats = []
    # Head coach
    if section in ('head_coaches', 'head_coach'):
        if r == 'head coach' or r.startswith('interim head coach') or r == 'co-head coach':
            cats.append('HC')
    # Coordinators - match anywhere, broad net
    if 'offensive coordinator' in r:
        cats.append('OC')
    if 'defensive coordinator' in r:
        cats.append('DC')
    # Position coaches - exclude assistant/quality-control/intern/analyst variants
    if not is_assistant_like(r):
        if 'quarterback' in r:
            cats.append('QB')
        if 'running back' in r:
            cats.append('RB')
        if 'wide receiver' in r:
            cats.append('WR')
        if 'tight end' in r:
            cats.append('TE')
        if 'offensive line' in r:
            cats.append('OL')
    return cats

# Build: (season, team_abbr, role_cat) -> set of coach names
table = collections.defaultdict(set)
unmatched_teams = set()
for row in rows:
    team_abbr = TEAM_MAP.get(row['team_name'])
    if team_abbr is None:
        unmatched_teams.add(row['team_name'])
        continue
    cats = classify(row['section'], row['role'])
    for cat in cats:
        table[(row['season'], team_abbr, cat)].add(row['name'])

print('unmatched team names:', unmatched_teams)
print('total (season,team,cat) keys:', len(table))

# Write out long-format coach table
with open('/tmp/pfr/coach_effects/coach_table.csv', 'w', newline='') as f:
    w = csv.writer(f)
    w.writerow(['season', 'team', 'role', 'coach_name'])
    for (season, team, cat), names in sorted(table.items()):
        for name in sorted(names):
            w.writerow([season, team, cat, name])

# Sanity: how many team-seasons have exactly 1 coach per role vs 2+
from collections import Counter
counts = Counter(len(v) for v in table.values())
print('distribution of #names per (season,team,role):', counts)

# Coverage per role
role_counts = Counter(k[2] for k in table.keys())
print('team-season coverage per role:', role_counts)
