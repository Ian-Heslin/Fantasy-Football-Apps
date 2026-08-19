import pandas as pd
import numpy as np

seg_df = pd.read_csv('coach_tenure_segments.csv')
ranked = pd.read_csv('team_offense_ranked.csv').set_index(['season','team'])
qb = pd.read_csv('team_primary_qb.csv').set_index(['season','team'])['primary_qb']

def metrics_for(team, season):
    key = (season, team)
    if key not in ranked.index:
        return None
    row = ranked.loc[key]
    return {'epa': row['epa_per_play'], 'epa_rank': row['epa_rank'], 'epa_pctile': row['epa_per_play_pctile'],
            'ppg': row['ppg'], 'ppg_rank': row['ppg_rank']}

def qb_for(team, season):
    return qb.get((season, team), None)

detail_rows = []
for _, seg in seg_df.iterrows():
    coach, team, start, end = seg['coach'], seg['team'], int(seg['start']), int(seg['end'])
    during_seasons = list(range(start, end+1))
    during = [metrics_for(team, s) for s in during_seasons]
    during = [d for d in during if d is not None]
    before = metrics_for(team, start-1)
    after = metrics_for(team, end+1)
    qb_before = qb_for(team, start-1)
    qb_first = qb_for(team, start)
    qb_last = qb_for(team, end)
    qb_after = qb_for(team, end+1)
    detail_rows.append({
        'coach': coach, 'team': team, 'start': start, 'end': end,
        'during_epa_rank_avg': np.mean([d['epa_rank'] for d in during]) if during else None,
        'during_epa_pctile_avg': np.mean([d['epa_pctile'] for d in during]) if during else None,
        'during_ppg_rank_avg': np.mean([d['ppg_rank'] for d in during]) if during else None,
        'before_epa_rank': before['epa_rank'] if before else None,
        'before_epa_pctile': before['epa_pctile'] if before else None,
        'after_epa_rank': after['epa_rank'] if after else None,
        'after_epa_pctile': after['epa_pctile'] if after else None,
        'qb_same_before_to_start': (qb_before is not None and qb_before == qb_first),
        'qb_same_end_to_after': (qb_last is not None and qb_last == qb_after),
        'n_seasons': len(during),
    })

detail = pd.DataFrame(detail_rows)
detail.to_csv('coach_before_during_after_detail.csv', index=False)
pd.set_option('display.width',200); pd.set_option('display.max_columns',20)
print(detail.round(3).to_string(index=False))
