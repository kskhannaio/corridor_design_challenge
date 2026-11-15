"""Baseline results of the SUMO simulation ("today", weekday 8-9 am), for the Simulation tab.

Copies results from the SUMO repo (src/sumo_poc, after `python run.py`) into one site data file:

  data/simulation.geojson
    meta            run facts and loop-wide figures (top-level member next to "features")
    kind=road       one line per loop road: people crossing it, time to cross, extra walking to reach a crossing
    kind=crossing   junctions A, B, C and the foot over bridges (fob=true): people crossing per hour

Only the baseline scenario is copied. Usage: python3 scripts/build_simulation.py [path/to/sumo_poc]
"""
import csv, json, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, '..', 'data')
SRC = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, '..', '..', 'sumo_poc')
rows = lambda name: [r for r in csv.DictReader(open(os.path.join(SRC, 'out', 'metrics', name))) if r['scenario'] == 'baseline']
num = lambda v: round(float(v), 1)
rnd = lambda c: [rnd(x) for x in c] if isinstance(c[0], list) else [round(c[0], 6), round(c[1], 6)]

centre = {f['properties']['side']: f['geometry']['coordinates'] for f in json.load(open(os.path.join(DATA, 'crossings.geojson')))['features']
          if f['properties']['kind'] == 'centreline'}
junction = {f['properties']['id']: f['geometry']['coordinates'] for f in json.load(open(os.path.join(DATA, 'stretch.geojson')))['features']
            if f['properties']['kind'] == 'junction'}
feats = []
for r in rows('people_by_side.csv'):
    feats.append({'type': 'Feature', 'geometry': {'type': 'LineString', 'coordinates': rnd(centre[r['side']])}, 'properties': {
        'kind': 'road', 'side': r['side'], 'people': int(r['people']), 'cross_s': num(r['trip_time_mean_s']), 'cross_p85_s': num(r['trip_time_p85_s']),
        'walk_m': num(r['walk_m_mean']), 'straight_m': num(r['straight_m_mean']), 'extra_walk_m': num(r['extra_walk_m_mean']),
        'detour': num(r['detour_factor_median'])}})
fobs = [f for f in json.load(open(os.path.join(DATA, 'crossings.geojson')))['features'] if f['properties'].get('fob')]
other, bridges = 0, {}
for r in rows('crossings_use.csv'):
    if r['crossing'] in junction:
        feats.append({'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': rnd(junction[r['crossing']])},
                      'properties': {'kind': 'crossing', 'junction': r['crossing'], 'people_h': int(r['people_per_h'])}})
    elif r['crossing'].startswith('FOB '):                 # "FOB CA@415": a foot over bridge, by road and distance along it
        side, ch = r['crossing'][4:].split('@')
        near = [f for f in fobs if f['properties']['side'] == side and abs(f['properties']['chainage_m'] - int(ch)) < 40]
        if near:                                           # one bridge can span two roads (the one at junction C): add it once
            b = bridges.setdefault(near[0]['properties']['osm'], {'f': near[0], 'n': 0, 'sides': []})
            b['n'] = max(b['n'], int(r['people_per_h'])); b['sides'].append(side)
    else: other += int(r['people_per_h'])
for b in bridges.values():
    feats.append({'type': 'Feature', 'geometry': b['f']['geometry'], 'properties': {'kind': 'crossing', 'fob': True, 'sides': '+'.join(sorted(b['sides'])),
                  'chainage_m': b['f']['properties']['chainage_m'], 'side': b['f']['properties']['side'], 'people_h': b['n']}})
# vehicle speeds are not copied: with assumed volumes and signals the model's traffic jams far worse than the street
s = rows('summary.csv')[0]
cfg = json.load(open(os.path.join(SRC, 'config', 'assumptions.json')))
meta = {'scenario': 'baseline', 'hour': f"{cfg['time']['metrics_begin']}-{cfg['time']['metrics_end']}",
        'built': time.strftime('%Y-%m-%d', time.localtime(os.path.getmtime(os.path.join(SRC, 'out', 'metrics', 'summary.csv')))),
        'people': int(s['people_crossing_trips']), 'cross_s': num(s['ped_trip_time_mean_s']), 'extra_walk_m': num(s['ped_extra_walk_m_mean']),
        'detour': num(s['ped_detour_factor_median']), 'people_other_junctions_h': other,
        'vehicles_finished': int(s['vehicles_finished']), 'vehicles_not_entered': int(s['vehicles_not_inserted']),
        'signals': cfg['signals'].get('junction_type', 'static')}
out = os.path.join(DATA, 'simulation.geojson')
json.dump({'type': 'FeatureCollection', 'meta': meta, 'features': feats}, open(out, 'w'), separators=(',', ':'))
print(f"wrote {out}: {len(feats)} features, {os.path.getsize(out) // 1024} KB; meta {meta}")
