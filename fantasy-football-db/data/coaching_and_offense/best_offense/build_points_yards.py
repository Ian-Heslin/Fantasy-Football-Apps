import pandas as pd

games = pd.read_csv('/tmp/pfr/games.csv', low_memory=False)
games = games[(games['season']>=2000) & (games['season']<=2025) & (games['game_type']=='REG')]

rows = []
for _, r in games.iterrows():
    rows.append({'season': r['season'], 'team': r['home_team'], 'points': r['home_score']})
    rows.append({'season': r['season'], 'team': r['away_team'], 'points': r['away_score']})
df = pd.DataFrame(rows)
df = df.dropna(subset=['points'])
agg = df.groupby(['season','team']).agg(games=('points','count'), total_points=('points','sum')).reset_index()
agg['ppg'] = agg['total_points']/agg['games']
agg.to_csv('team_points_by_season.csv', index=False)
print(agg.shape)
print(agg.head())
