import pandas as pd

ct = pd.read_csv('/tmp/pfr/coach_effects/coach_table.csv')
ct['coach_name'] = ct['coach_name'].str.replace('†','',regex=False).str.strip()
ranked = pd.read_csv('team_offense_ranked.csv')
qb = pd.read_csv('team_primary_qb.csv')

ranked_idx = ranked.set_index(['season','team'])
qb_idx = qb.set_index(['season','team'])['primary_qb']

NAMED_COACHES = ['Kyle Shanahan','Matt LaFleur','Sean McVay','Ben Johnson','Andy Reid','Sean Payton']

# Payton was suspended the entire 2012 season (Bounty scandal) -- exclude that season from his
# "coaching" credit even though nominally still HC of record on paper.
EXCLUDE = {('Sean Payton', 2012, 'NO')}

def get_team_row(team, season):
    key = (season, team)
    if key in ranked_idx.index:
        row = ranked_idx.loc[key]
        if isinstance(row, pd.DataFrame):
            row = row.iloc[0]
        return row
    return None

def get_qb(team, season):
    key = (season, team)
    return qb_idx.get(key, None)

segments = []
for name in NAMED_COACHES:
    sub = ct[(ct.coach_name==name) & (ct.role.isin(['OC','HC']))].copy()
    sub = sub[~sub.apply(lambda r: (name, r['season'], r['team']) in EXCLUDE, axis=1)]
    sub = sub.sort_values(['team','season'])
    for team, g in sub.groupby('team'):
        seasons = sorted(g['season'].unique())
        # break into contiguous runs
        run = [seasons[0]]
        runs = []
        for s in seasons[1:]:
            if s == run[-1] + 1:
                run.append(s)
            else:
                runs.append(run)
                run = [s]
        runs.append(run)
        for run in runs:
            role_here = g[g.season.isin(run)]['role'].iloc[-1]
            segments.append({'coach': name, 'team': team, 'start': run[0], 'end': run[-1], 'role_at_end': role_here})

seg_df = pd.DataFrame(segments)
print(seg_df.to_string(index=False))
seg_df.to_csv('coach_tenure_segments.csv', index=False)
