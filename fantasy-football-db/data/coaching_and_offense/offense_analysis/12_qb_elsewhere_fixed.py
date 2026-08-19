import pandas as pd
import numpy as np
from scipy import stats

seg = pd.read_csv('all_coach_tenure_segments.csv')          # coach, team, start, end, n_seasons
qbdat = pd.read_csv('team_primary_qb_id.csv')                # season, team, primary_qb_id, primary_qb_name
ranked = pd.read_csv('team_offense_ranked.csv')[['season','team','epa_per_play_pctile']]
qbdat = qbdat.merge(ranked, on=['season','team'], how='left').dropna(subset=['epa_per_play_pctile'])

# expand segments to (coach, team, season) rows
seg_rows = []
for _, s in seg.iterrows():
    for yr in range(int(s['start']), int(s['end'])+1):
        seg_rows.append({'coach': s['coach'], 'team': s['team'], 'season': yr})
seg_long = pd.DataFrame(seg_rows)

# join: for every (coach, team, season) tenure-row, find that team-season's primary QB + pctile
with_coach = seg_long.merge(qbdat, on=['team','season'], how='inner')

results = []
for coach, g in with_coach.groupby('coach'):
    # distinct QBs this coach had (as primary starter) during his OC/HC tenure(s)
    qb_seasons_with = g[['primary_qb_id','primary_qb_name','season','team','epa_per_play_pctile']].drop_duplicates()
    per_qb = []
    for qb_id, gg in qb_seasons_with.groupby('primary_qb_id'):
        qb_name = gg['primary_qb_name'].iloc[0]
        with_pctile = gg['epa_per_play_pctile'].mean()
        n_with = len(gg)
        # elsewhere = this QB's OTHER primary-starter seasons, ANY team, NOT overlapping this coach's own tenure rows
        own_ty = set(zip(g['team'], g['season']))
        other = qbdat[(qbdat.primary_qb_id==qb_id) & (~qbdat.apply(lambda r:(r['team'],r['season']) in own_ty, axis=1))]
        if len(other)==0:
            continue
        per_qb.append({'coach':coach,'qb_id':qb_id,'qb_name':qb_name,
                        'n_seasons_with':n_with,'pctile_with':with_pctile,
                        'n_seasons_elsewhere':len(other),'pctile_elsewhere':other['epa_per_play_pctile'].mean(),
                        'delta': with_pctile - other['epa_per_play_pctile'].mean()})
    results.extend(per_qb)

pairs = pd.DataFrame(results)
pairs.to_csv('qb_coach_paired_deltas_v2.csv', index=False)
print('total qb-coach pairs w/ real control:', len(pairs))

agg = pairs.groupby('coach').agg(n_qbs=('qb_id','nunique'), avg_delta=('delta','mean'),
                                  avg_pctile_with=('pctile_with','mean'), avg_pctile_elsewhere=('pctile_elsewhere','mean')).reset_index()
agg = agg[agg.n_qbs>=2].sort_values('avg_delta', ascending=False)
def coach_ttest(coach):
    d = pairs[pairs.coach==coach]['delta']
    if len(d)<2: return None,None
    return stats.ttest_1samp(d,0)
agg['t_stat'], agg['p_value'] = zip(*agg['coach'].apply(coach_ttest))
agg.to_csv('coach_qb_elevation_leaderboard_v2.csv', index=False)
pd.set_option('display.width',200)
print(agg.round(3).head(30).to_string(index=False))
