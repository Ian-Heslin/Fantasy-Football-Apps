import pandas as pd
import numpy as np
from scipy import stats

ct = pd.read_csv('/tmp/pfr/coach_effects/coach_table.csv')
ct['coach_name'] = ct['coach_name'].str.replace('†','',regex=False).str.strip()
ct['coach_name'] = ct['coach_name'].str.replace(', Jr.','',regex=False).str.strip()
ct = ct[~((ct.coach_name=='Sean Payton') & (ct.season==2012) & (ct.team=='NO'))]
sub = ct[ct.role.isin(['OC','HC'])][['coach_name','season','team']].drop_duplicates()

pts = pd.read_csv('/tmp/pfr/player_team_season.csv')
rankings = pd.read_csv('/tmp/pfr/all_rankings_tiered.csv')
rankings = rankings[rankings.position.isin(['QB','RB','WR','TE'])].copy()
def base_tier(t):
    return t[:-1] if isinstance(t,str) and t.endswith('*') else t
rankings['tier_base'] = rankings['tier'].apply(base_tier)
rankings['is_superstar'] = rankings['tier_base'].isin(['Superstar','League Winner'])

players_teams = rankings.merge(pts, on=['player_id','season'], how='left')

# join: for each coach-season-team row, which skill players were on that team that season
joined = sub.merge(players_teams, on=['season','team'], how='inner')

rows = []
for coach, g in joined.groupby('coach_name'):
    per_player = g.groupby('player_id')['is_superstar'].max()  # ever superstar+ under this coach
    n_players = len(per_player)
    n_superstar = per_player.sum()
    rows.append({'coach_name': coach, 'n_distinct_players': n_players, 'n_superstar_players': n_superstar,
                 'superstar_rate': n_superstar/n_players if n_players else None})

ss = pd.DataFrame(rows)
ss.to_csv('coach_superstar_rate_combined.csv', index=False)
print(ss[ss.n_distinct_players>=15].sort_values('superstar_rate', ascending=False).head(20).round(3).to_string(index=False))
print('n coaches with >=15 distinct players:', (ss.n_distinct_players>=15).sum())

# league-wide base rate for comparison
all_players = players_teams.drop_duplicates('player_id')
print()
print('league-wide superstar-ever rate (any distinct skill player, any coach):',
      round(rankings.groupby('player_id')['is_superstar'].max().mean(), 4))
