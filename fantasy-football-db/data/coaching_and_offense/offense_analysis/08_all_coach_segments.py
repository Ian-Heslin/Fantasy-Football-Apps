import pandas as pd

ct = pd.read_csv('/tmp/pfr/coach_effects/coach_table.csv')
ct['coach_name'] = ct['coach_name'].str.replace('†','',regex=False).str.strip()
# Exclude Sean Payton's 2012 suspended season (verified real-world reason, see v14/v15 notes)
ct = ct[~((ct.coach_name=='Sean Payton') & (ct.season==2012) & (ct.team=='NO'))]

sub = ct[ct.role.isin(['OC','HC'])].copy()
sub = sub.sort_values(['coach_name','team','season'])

segments = []
for (name, team), g in sub.groupby(['coach_name','team']):
    seasons = sorted(g['season'].unique())
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
        segments.append({'coach': name, 'team': team, 'start': run[0], 'end': run[-1], 'n_seasons': len(run)})

seg_df = pd.DataFrame(segments)
seg_df.to_csv('all_coach_tenure_segments.csv', index=False)
print(seg_df.shape)
print(seg_df[seg_df.n_seasons>=4].sort_values('n_seasons', ascending=False).head(15))
