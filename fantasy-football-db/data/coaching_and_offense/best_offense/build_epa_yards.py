import pandas as pd
import glob, re

results = []
for year in range(2000, 2026):
    fn = f'/tmp/pfr/play_by_play_{year}.csv.gz'
    cols = ['season','season_type','week','posteam','play_type','epa','yards_gained','play','pass','rush','penalty']
    df = pd.read_csv(fn, low_memory=False, usecols=lambda c: c in cols)
    df = df[df['season_type']=='REG']
    # offensive scrimmage plays: pass or rush attempts (exclude penalties/no-plays/kneel/spike handled by pass/rush flags)
    off = df[(df['pass']==1) | (df['rush']==1)]
    off = off.dropna(subset=['posteam'])
    g = off.groupby('posteam').agg(
        plays=('epa','count'),
        total_epa=('epa','sum'),
        mean_epa=('epa','mean'),
        total_yards=('yards_gained','sum'),
    ).reset_index()
    # games played per team that season, from games.csv would be more accurate; approximate via distinct weeks
    weeks = off.groupby('posteam')['week'].nunique().reset_index().rename(columns={'week':'games_est'})
    g = g.merge(weeks, on='posteam')
    g['season'] = year
    results.append(g)
    print(year, 'done', len(g))

allg = pd.concat(results, ignore_index=True)
allg = allg.rename(columns={'posteam':'team'})
allg.to_csv('team_epa_yards_by_season.csv', index=False)
print(allg.shape)
