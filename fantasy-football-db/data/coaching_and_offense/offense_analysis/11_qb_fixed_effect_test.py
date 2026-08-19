import pandas as pd
import numpy as np
from scipy import stats

panel = pd.read_csv('qb_career_panel.csv')

# Only keep QBs who have enough career seasons in the panel to have a real "elsewhere" comparison
qb_counts = panel.groupby('primary_qb_id').size()
multi_season_qbs = qb_counts[qb_counts>=2].index
panel = panel[panel.primary_qb_id.isin(multi_season_qbs)]

pair_rows = []
for (qb_id, coach), g in panel.groupby(['primary_qb_id','coach']):
    qb_name = panel[panel.primary_qb_id==qb_id]['primary_qb_name'].iloc[0]
    with_coach = g['epa_per_play_pctile']
    elsewhere = panel[(panel.primary_qb_id==qb_id) & (panel.coach!=coach)]['epa_per_play_pctile']
    if len(elsewhere) == 0:
        continue  # no true control data for this QB
    pair_rows.append({
        'coach': coach, 'qb_id': qb_id, 'qb_name': qb_name,
        'n_seasons_with_coach': len(with_coach), 'avg_pctile_with_coach': with_coach.mean(),
        'n_seasons_elsewhere': len(elsewhere), 'avg_pctile_elsewhere': elsewhere.mean(),
        'delta': with_coach.mean() - elsewhere.mean(),
    })

pairs = pd.DataFrame(pair_rows)
pairs.to_csv('qb_coach_paired_deltas.csv', index=False)
print('total qb-coach pairs with a real control:', len(pairs))

# Coach-level aggregation: require >=2 distinct QBs (each with their own elsewhere-control) to make
# a real "does this coach elevate whichever QB he has" claim, and require the coach's own with-coach
# seasons to be at least 1 (already true by construction)
agg = pairs.groupby('coach').agg(
    n_qbs=('qb_id','nunique'),
    avg_delta=('delta','mean'),
    avg_pctile_with=('avg_pctile_with_coach','mean'),
    avg_pctile_elsewhere=('avg_pctile_elsewhere','mean'),
).reset_index()
agg = agg[agg.n_qbs>=2].sort_values('avg_delta', ascending=False)

# paired t-test per coach where n_qbs>=3 (small n caveat noted for 2)
def coach_ttest(coach):
    d = pairs[pairs.coach==coach]['delta']
    if len(d) < 2:
        return None, None
    t,p = stats.ttest_1samp(d, 0)
    return t, p

agg['t_stat'], agg['p_value'] = zip(*agg['coach'].apply(coach_ttest))
agg.to_csv('coach_qb_elevation_leaderboard.csv', index=False)
pd.set_option('display.width', 200)
print(agg.round(3).head(30).to_string(index=False))
