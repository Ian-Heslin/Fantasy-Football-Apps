import csv, collections, json
from scipy.stats import fisher_exact

# ============ Reload breakout data with position tagged ============
breakout_rows = json.load(open('/tmp/pfr/coach_effects/breakout_rows.json'))

coach_tbl = collections.defaultdict(list)
with open('/tmp/pfr/coach_effects/coach_table.csv') as f:
    for row in csv.DictReader(f):
        coach_tbl[(int(row['season']), row['team'], row['role'])].append(row['coach_name'])

POS_ROLE = {'QB': 'QB', 'RB': 'RB', 'WR': 'WR', 'TE': 'TE'}

base_rate = collections.defaultdict(lambda: [0, 0])
for r in breakout_rows:
    base_rate[r['position']][1] += 1
    if r['broke_out']:
        base_rate[r['position']][0] += 1

def credit_with_position(role_key_builder):
    # name -> position -> [breakouts, total]
    stats_by_coach = collections.defaultdict(lambda: collections.defaultdict(lambda: [0, 0]))
    for r in breakout_rows:
        season, team, pos = r['season_breakout'], r['next_team'], r['position']
        role = role_key_builder(pos)
        names = coach_tbl.get((season, team, role), [])
        for name in names:
            stats_by_coach[name][pos][1] += 1
            if r['broke_out']:
                stats_by_coach[name][pos][0] += 1
    return stats_by_coach

def report(stats_by_coach, filename, min_n=10, pool_positions=False):
    """If pool_positions, aggregate across positions per coach and compare vs pooled base rate
    weighted by that coach's position mix. Otherwise report per (coach, position)."""
    rows_out = []
    for name, pos_dict in stats_by_coach.items():
        if pool_positions:
            total = sum(v[1] for v in pos_dict.values())
            breakouts = sum(v[0] for v in pos_dict.values())
            if total < min_n:
                continue
            # expected breakouts under position-specific base rates (weighted)
            expected = sum(base_rate[p][0] / base_rate[p][1] * v[1] for p, v in pos_dict.items())
            expected_rate = expected / total
            rate = breakouts / total
            # fisher exact vs pooled 2x2 using expected rate as "population" rate
            # build a pseudo-population count scaled to same n for a valid fisher test
            pop_successes = round(expected_rate * 100000)
            pop_total = 100000
            table = [[breakouts, total - breakouts], [pop_successes, pop_total - pop_successes]]
            try:
                _, p = fisher_exact(table)
            except Exception:
                p = float('nan')
            rows_out.append((name, total, breakouts, rate, expected_rate, p))
        else:
            for pos, (breakouts, total) in pos_dict.items():
                if total < min_n:
                    continue
                base_b, base_t = base_rate[pos]
                table = [[breakouts, total - breakouts], [base_b - breakouts, (base_t - total) - (base_b - breakouts)]]
                try:
                    _, p = fisher_exact(table)
                except Exception:
                    p = float('nan')
                rate = breakouts / total
                base = base_b / base_t
                rows_out.append((name, pos, total, breakouts, rate, base, p))
    if pool_positions:
        rows_out.sort(key=lambda x: (x[5] if x[5] == x[5] else 1))  # by p-value
        with open(filename, 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(['coach_name', 'n_candidates', 'n_breakouts', 'breakout_rate', 'expected_rate_weighted', 'p_value'])
            for row in rows_out:
                w.writerow(row)
    else:
        rows_out.sort(key=lambda x: (x[6] if x[6] == x[6] else 1))
        with open(filename, 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(['coach_name', 'position', 'n_candidates', 'n_breakouts', 'breakout_rate', 'league_base_rate', 'p_value'])
            for row in rows_out:
                w.writerow(row)
    return rows_out

pos_stats = credit_with_position(lambda pos: POS_ROLE[pos])
oc_stats = credit_with_position(lambda pos: 'OC')
hc_stats = credit_with_position(lambda pos: 'HC')

pos_out = report(pos_stats, '/tmp/pfr/coach_effects/position_coach_breakout_stats.csv', min_n=10, pool_positions=False)
oc_out = report(oc_stats, '/tmp/pfr/coach_effects/oc_breakout_stats.csv', min_n=15, pool_positions=True)
hc_out = report(hc_stats, '/tmp/pfr/coach_effects/hc_breakout_stats.csv', min_n=15, pool_positions=True)

print('Position coaches tested:', len(pos_out))
sig = [r for r in pos_out if r[6] == r[6] and r[6] < 0.05]
print('Position coaches p<0.05:', len(sig))
for r in sig[:20]:
    print(r)

print('\nOCs tested:', len(oc_out))
sig_oc = [r for r in oc_out if r[5]==r[5] and r[5] < 0.05]
print('OCs p<0.05:', len(sig_oc))
for r in sig_oc[:20]:
    print(r)

print('\nHCs tested:', len(hc_out))
sig_hc = [r for r in hc_out if r[5]==r[5] and r[5] < 0.05]
print('HCs p<0.05:', len(sig_hc))
for r in sig_hc[:20]:
    print(r)
