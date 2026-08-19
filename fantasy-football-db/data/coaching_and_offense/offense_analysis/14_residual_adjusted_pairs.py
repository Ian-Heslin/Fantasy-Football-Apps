import pandas as pd
import numpy as np
from scipy import stats

seg = pd.read_csv('all_coach_tenure_segments.csv')
qbres = pd.read_csv('qb_panel_with_residual.csv')  # season, team, primary_qb_id, primary_qb_name, residual_pctile, epa_per_play_pctile

seg_rows = []
for _, s in seg.iterrows():
    for yr in range(int(s['start']), int(s['end'])+1):
        seg_rows.append({'coach': s['coach'], 'team': s['team'], 'season': yr})
seg_long = pd.DataFrame(seg_rows)

with_coach = seg_long.merge(qbres, on=['team','season'], how='inner')

results = []
for coach, g in with_coach.groupby('coach'):
    qb_seasons_with = g[['primary_qb_id','primary_qb_name','season','team','epa_per_play_pctile','residual_pctile']].drop_duplicates()
    for qb_id, gg in qb_seasons_with.groupby('primary_qb_id'):
        qb_name = gg['primary_qb_name'].iloc[0]
        raw_with = gg['epa_per_play_pctile'].mean()
        resid_with = gg['residual_pctile'].mean()
        n_with = len(gg)
        own_ty = set(zip(g['team'], g['season']))
        other = qbres[(qbres.primary_qb_id==qb_id) & (~qbres.apply(lambda r:(r['team'],r['season']) in own_ty, axis=1))]
        if len(other)==0:
            continue
        results.append({'coach':coach,'qb_id':qb_id,'qb_name':qb_name,
                         'n_with':n_with,'raw_with':raw_with,'resid_with':resid_with,
                         'n_elsewhere':len(other),'raw_elsewhere':other['epa_per_play_pctile'].mean(),
                         'resid_elsewhere':other['residual_pctile'].mean(),
                         'raw_delta': raw_with - other['epa_per_play_pctile'].mean(),
                         'resid_delta': resid_with - other['residual_pctile'].mean()})

pairs = pd.DataFrame(results)
pairs.to_csv('qb_coach_paired_deltas_residual.csv', index=False)
print('pairs:', len(pairs))
print('Pooled leaguewide baseline check (residual-adjusted):')
print('  mean raw_delta   :', pairs.raw_delta.mean().round(4), ' share positive:', (pairs.raw_delta>0).mean().round(3))
print('  mean resid_delta :', pairs.resid_delta.mean().round(4), ' share positive:', (pairs.resid_delta>0).mean().round(3))

agg = pairs.groupby('coach').agg(n_qbs=('qb_id','nunique'),
        avg_raw_delta=('raw_delta','mean'), avg_resid_delta=('resid_delta','mean')).reset_index()
agg = agg[agg.n_qbs>=2].sort_values('avg_resid_delta', ascending=False)
def ttest(coach, col):
    d = pairs[pairs.coach==coach][col]
    if len(d)<2: return None,None
    return stats.ttest_1samp(d,0)
agg['t_resid'], agg['p_resid'] = zip(*agg['coach'].apply(lambda c: ttest(c,'resid_delta')))
agg.to_csv('coach_qb_elevation_leaderboard_residual.csv', index=False)
pd.set_option('display.width',200)
print(agg.round(3).head(25).to_string(index=False))
