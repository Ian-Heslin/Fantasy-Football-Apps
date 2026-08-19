import pandas as pd
import numpy as np

seg = pd.read_csv('all_coach_tenure_segments.csv')
ranked = pd.read_csv('team_offense_ranked.csv').set_index(['season','team'])
qb = pd.read_csv('team_primary_qb_id.csv').set_index(['season','team'])

rows = []
for _, s in seg.iterrows():
    coach, team, start, end = s['coach'], s['team'], int(s['start']), int(s['end'])
    seasons = list(range(start, end+1))
    pctiles, qbs = [], []
    for yr in seasons:
        key = (yr, team)
        if key in ranked.index:
            pctiles.append(ranked.loc[key, 'epa_per_play_pctile'])
        if key in qb.index:
            row = qb.loc[key]
            qbs.append((row['primary_qb_id'], row['primary_qb_name']))
    distinct_qbs = sorted(set(qbs))
    rows.append({
        'coach': coach, 'team': team, 'start': start, 'end': end, 'n_seasons': len(seasons),
        'avg_off_pctile': np.mean(pctiles) if pctiles else None,
        'n_distinct_qbs': len(distinct_qbs),
        'qb_list': '; '.join(f'{n} ({sum(1 for q in qbs if q[0]==i)}yr)' for i,n in distinct_qbs),
    })

detail = pd.DataFrame(rows)
detail.to_csv('coach_qb_variety_detail.csv', index=False)

# Filter: real multi-QB test = >=2 distinct QBs, >=4 seasons, decent per-QB sample (skip 1-year afterthought QBs)
candidates = detail[(detail.n_distinct_qbs>=2) & (detail.n_seasons>=4)].sort_values('avg_off_pctile', ascending=False)
pd.set_option('display.width',220); pd.set_option('display.max_colwidth',80)
print(candidates[['coach','team','start','end','n_seasons','n_distinct_qbs','avg_off_pctile','qb_list']].head(30).to_string(index=False))
