import pandas as pd
import numpy as np
from scipy import stats

# All QB roster-seasons (any role, including backups), from players.csv position + player_team_season
players = pd.read_csv('/tmp/pfr/players.csv')[['gsis_id','display_name','position','rookie_season']]
qbs_all = players[players.position=='QB']
pts = pd.read_csv('/tmp/pfr/player_team_season.csv')
qb_roster = pts.merge(qbs_all, left_on='player_id', right_on='gsis_id', how='inner')

seg = pd.read_csv('all_coach_tenure_segments.csv')
seg_rows = []
for _, s in seg.iterrows():
    for yr in range(int(s['start']), int(s['end'])+1):
        seg_rows.append({'coach': s['coach'], 'team': s['team'], 'season': yr})
seg_long = pd.DataFrame(seg_rows)

# any QB on a coach's roster (starter or backup) during his tenure
qb_with_coach = qb_roster.merge(seg_long, on=['team','season'], how='inner')

# their performance (as PRIMARY starter, when it happens) with residuals
qbres = pd.read_csv('qb_panel_with_residual.csv')[['season','primary_qb_id','residual_pctile','epa_per_play_pctile']]

rows = []
for (qb_id, coach), g in qb_with_coach.groupby(['player_id','coach']):
    qb_name = g['display_name'].iloc[0]
    tenure_seasons = set(g['season'])
    first, last = min(tenure_seasons), max(tenure_seasons)
    # this QB's own primary-starter seasons (any team), split relative to this coach tenure
    own = qbres[qbres.primary_qb_id==qb_id].copy()
    if len(own) == 0:
        continue
    before = own[own.season < first]
    after = own[own.season > last]
    during = own[own.season.isin(tenure_seasons)]
    if len(before)==0 and len(after)==0:
        continue
    rows.append({
        'coach': coach, 'qb_id': qb_id, 'qb_name': qb_name,
        'tenure_first': first, 'tenure_last': last, 'n_roster_seasons': len(tenure_seasons),
        'n_before': len(before), 'avg_resid_before': before['residual_pctile'].mean() if len(before) else None,
        'n_during_as_starter': len(during), 'avg_resid_during': during['residual_pctile'].mean() if len(during) else None,
        'n_after': len(after), 'avg_resid_after': after['residual_pctile'].mean() if len(after) else None,
    })

alumni = pd.DataFrame(rows)
alumni.to_csv('qb_alumni_before_after.csv', index=False)
print('total qb-coach roster relationships with before/after data:', len(alumni))

# focus: after vs before, paired, for QBs with BOTH before and after data
both = alumni.dropna(subset=['avg_resid_before','avg_resid_after'])
print('with BOTH before and after:', len(both))
both['after_minus_before'] = both['avg_resid_after'] - both['avg_resid_before']
both.to_csv('qb_alumni_before_after_paired.csv', index=False)
pd.set_option('display.width',200)
print(both[['coach','qb_name','n_before','avg_resid_before','n_after','avg_resid_after','after_minus_before']].sort_values('after_minus_before', ascending=False).round(3).to_string(index=False))
