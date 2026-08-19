import pandas as pd
import numpy as np

ct = pd.read_csv('/tmp/pfr/coach_effects/coach_table.csv')
ct['coach_name'] = ct['coach_name'].str.replace('†','',regex=False).str.strip()
ct['coach_name'] = ct['coach_name'].str.replace(', Jr.','',regex=False).str.strip()
ct = ct[~((ct.coach_name=='Sean Payton') & (ct.season==2012) & (ct.team=='NO'))]
sub = ct[ct.role.isin(['OC','HC'])].copy()

ranked = pd.read_csv('team_offense_ranked.csv')[['season','team','epa_rank','epa_per_play_pctile']]
m = sub.merge(ranked, on=['season','team'], how='left').dropna(subset=['epa_rank'])
m = m.drop_duplicates(subset=['coach_name','season','team'])

agg = m.groupby('coach_name').agg(
    total_seasons=('epa_rank','size'),
    top5_seasons=('epa_rank', lambda x: (x<=5).sum()),
    top10_seasons=('epa_rank', lambda x: (x<=10).sum()),
    avg_rank=('epa_rank','mean'),
).reset_index()
agg['top5_rate'] = agg.top5_seasons/agg.total_seasons
agg['top10_rate'] = agg.top10_seasons/agg.total_seasons
agg.to_csv('coach_top_offense_consistency_all.csv', index=False)

qualified = agg[agg.total_seasons>=6].sort_values(['top10_rate','top5_rate'], ascending=False)
qualified.to_csv('coach_top_offense_consistency.csv', index=False)
pd.set_option('display.width',200)
print(qualified.head(30).round(3).to_string(index=False))
print()
print('n qualified (>=6 seasons):', len(qualified))
