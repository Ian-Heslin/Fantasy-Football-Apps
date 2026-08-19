import pandas as pd
import numpy as np

ranked = pd.read_csv('team_offense_ranked.csv')[['season','team','epa_per_play_pctile']]
qb = pd.read_csv('team_primary_qb_id.csv')
seg = pd.read_csv('all_coach_tenure_segments.csv')

panel = qb.merge(ranked, on=['season','team'], how='left').dropna(subset=['epa_per_play_pctile'])

# map each (team, season) to the coach in charge (from segments) -- build an interval lookup
def find_coach(team, season):
    hits = seg[(seg.team==team) & (seg.start<=season) & (seg.end>=season)]
    if len(hits)==0:
        return None
    return hits.iloc[0]['coach']

panel['coach'] = panel.apply(lambda r: find_coach(r['team'], r['season']), axis=1)
panel = panel.dropna(subset=['coach'])
panel.to_csv('qb_career_panel.csv', index=False)
print('panel rows:', len(panel))
print(panel.head())
