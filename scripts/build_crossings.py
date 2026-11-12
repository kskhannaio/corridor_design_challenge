"""Crossings & gaps analysis for the study stretch.

Builds, from an Overpass response of scripts/crossings_query.overpassql:
  data/crossings.geojson    - centreline with chainage, existing crossings, gap segments,
                              chainage ticks, crossing generators (+ desire lines to the road)
  data/construction.geojson - Ejipura flyover works (for the site scorecard)

Standards (GIZ/MoHUA Tactical Urbanism Guidebook, after IRC 103 / UTTIPEC):
  mid-block crossings every 80-150 m in commercial/mixed-use areas, 80-250 m in residential.

Usage:
  curl -s --data-urlencode data@scripts/crossings_query.overpassql \
       https://overpass-api.de/api/interpreter > /tmp/xing_raw.json
  python3 scripts/build_crossings.py /tmp/xing_raw.json
"""
import json, math, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, '..', 'data')
SB, NB = 111814614, 133763768          # southbound (A->B) and northbound (B->A) carriageways
MIXED_USE_MAX, RESIDENTIAL_MAX = 150, 250
GENERATOR_REACH = 80                    # m from the road for a destination to count as a crossing generator
JUNCTION_ZONE = 20                      # m from either end treated as part of the junction

E = json.load(open(sys.argv[1]))['elements']
ways = {e['id']: e for e in E if e['type'] == 'way'}
nodes = {e['id']: e for e in E if e['type'] == 'node'}
for n in nodes.values():
    n.setdefault('tags', {})
for w in ways.values():
    for nid, g in zip(w['nodes'], w['geometry']):
        nodes.setdefault(nid, {'id': nid, 'lat': g['lat'], 'lon': g['lon'], 'tags': {}})

lat0 = 12.926
R = 6371008.8
kx, ky = math.radians(1) * R * math.cos(math.radians(lat0)), math.radians(1) * R
P = lambda lon, lat: (lon * kx, lat * ky)
U = lambda x, y: [round(x / kx, 7), round(y / ky, 7)]

def line_xy(w): return [P(g['lon'], g['lat']) for g in w['geometry']]

def resample(pts, step):
    out, carry = [pts[0]], 0.0
    for a, b in zip(pts, pts[1:]):
        L = math.dist(a, b); d = step - carry
        while d <= L:
            t = d / L; out.append((a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))); d += step
        carry = (carry + L) % step
    if out[-1] != pts[-1]: out.append(pts[-1])
    return out

def nearest_on(pts, p):
    best = (1e18, None)
    for a, b in zip(pts, pts[1:]):
        dx, dy = b[0] - a[0], b[1] - a[1]; L2 = dx * dx + dy * dy
        t = max(0, min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2)) if L2 else 0
        q = (a[0] + t * dx, a[1] + t * dy); d = math.dist(p, q)
        if d < best[0]: best = (d, q)
    return best

# --- centreline: midpoint between the two carriageways, sampled every 2 m from A to B
sb, nb = line_xy(ways[SB]), line_xy(ways[NB])
centre, sep = [], []
for p in resample(sb, 2.0):
    d, q = nearest_on(nb, p)
    centre.append(((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)); sep.append(d)
chain = [0.0]
for a, b in zip(centre, centre[1:]): chain.append(chain[-1] + math.dist(a, b))
TOTAL = chain[-1]

def project(p):
    """chainage (m from A), offset (m), side of the road for a point p (xy)."""
    best = (1e18, 0, 0)
    for i, (a, b) in enumerate(zip(centre, centre[1:])):
        dx, dy = b[0] - a[0], b[1] - a[1]; L2 = dx * dx + dy * dy
        t = max(0, min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2)) if L2 else 0
        q = (a[0] + t * dx, a[1] + t * dy); d = math.dist(p, q)
        if d < best[0]:
            cross = dx * (p[1] - a[1]) - dy * (p[0] - a[0])
            best = (d, chain[i] + t * math.sqrt(L2), cross, q)
    d, ch, cross, q = best
    # walking A->B the road heads south-west: left = south-east side, right = north-west side
    return ch, d, ('SE side' if cross > 0 else 'NW side'), q

def at_chain(ch):
    for i in range(len(chain) - 1):
        if chain[i] <= ch <= chain[i + 1]:
            t = (ch - chain[i]) / (chain[i + 1] - chain[i] or 1)
            return (centre[i][0] + t * (centre[i + 1][0] - centre[i][0]), centre[i][1] + t * (centre[i + 1][1] - centre[i][1])), i
    return centre[-1], len(centre) - 1

feats = []
F = lambda geom, **props: feats.append({"type": "Feature", "properties": props, "geometry": geom})
pt = lambda xy: {"type": "Point", "coordinates": U(*xy)}

F({"type": "LineString", "coordinates": [U(*c) for c in centre[::3]] + [U(*centre[-1])]},
  kind='centreline', length_m=round(TOTAL))

# --- existing crossings: crossing nodes on the road, footway=crossing ways touching it,
#     and the signalised junctions at the two ends
road_nodes = set(ways[SB]['nodes']) | set(ways[NB]['nodes'])
crossings = []
for w in ways.values():
    if w['tags'].get('footway') == 'crossing' and road_nodes & set(w['nodes']):
        n = nodes[(road_nodes & set(w['nodes'])).pop()]
        crossings.append(dict(xy=P(n['lon'], n['lat']), name='Zebra crossing at Junction A',
                              type=f"Marked crossing ({w['tags'].get('crossing', 'unknown')}, no own signal)",
                              status='Mapped in OSM', osm=f"way/{w['id']}"))
signals = [n for n in nodes.values() if n['tags'].get('highway') == 'traffic_signals']
for label, end in (('A', 0), ('B', TOTAL)):
    (ex, ey), _ = at_chain(end)
    near = [n for n in signals if math.dist(P(n['lon'], n['lat']), (ex, ey)) < 60]
    have = any(abs(project(c['xy'])[0] - end) < 40 for c in crossings)
    if near and not have:
        crossings.append(dict(xy=(ex, ey), name=f'Junction {label} (signalised)',
                              type='Traffic signals - no marked pedestrian crossing in OSM',
                              status='Unverified - check on the walk', osm=f"node/{near[0]['id']}"))
for c in crossings:
    ch, _, _, _ = project(c['xy']); c['ch'] = ch
crossings.sort(key=lambda c: c['ch'])
for c in crossings:
    F(pt(c['xy']), kind='crossing', name=c['name'], type=c['type'], status=c['status'], osm=c['osm'],
      chainage_m=round(c['ch']), verified=c['status'].startswith('Mapped'))

# --- gaps between consecutive crossings along the centreline
stops = [0.0] + [c['ch'] for c in crossings] + [TOTAL]
stops = sorted(set(round(s, 1) for s in stops))
gaps = []
for a, b in zip(stops, stops[1:]):
    L = b - a
    if L < 15: continue
    cls = 'ok' if L <= MIXED_USE_MAX else 'residential-only' if L <= RESIDENTIAL_MAX else 'too-long'
    needed = max(0, math.ceil(L / MIXED_USE_MAX) - 1)
    seg = [U(*at_chain(a)[0])] + [U(*centre[i]) for i in range(len(chain)) if a < chain[i] < b] + [U(*at_chain(b)[0])]
    F({"type": "LineString", "coordinates": seg}, kind='gap', from_m=round(a), to_m=round(b), length_m=round(L),
      status=cls, crossings_needed=needed,
      label=f"{round(L)} m without a crossing" + (f" · needs {needed} more" if needed else ""))
    gaps.append((a, b, L, cls, needed))

# --- chainage ticks every 50 m (surveyed widths at each 100 m come from the contract; see build_contract.py)
for ch in range(0, int(TOTAL) + 1, 50):
    F(pt(at_chain(ch)[0]), kind='tick', chainage_m=ch, major=(ch % 100 == 0))

# --- crossing generators: bus stops, side streets / gates meeting the road, key destinations
gens = []
for n in nodes.values():
    t = n['tags']
    if t.get('highway') == 'bus_stop' or t.get('public_transport') == 'platform':
        gens.append((P(n['lon'], n['lat']), t.get('name', 'Bus stop'), 'Bus stop', f"node/{n['id']}"))
for w in ways.values():
    if w['id'] in (SB, NB) or w['tags'].get('footway') in ('crossing', 'sidewalk'): continue
    hw = w['tags'].get('highway', '')
    if hw not in ('residential', 'service', 'footway', 'living_street', 'tertiary'): continue
    for nid in road_nodes & set(w['nodes']):
        n = nodes[nid]; nm = w['tags'].get('name')
        gens.append((P(n['lon'], n['lat']), f"Side street: {nm}" if nm else ('Footpath / lane' if hw == 'footway' else 'Side road / gate access'),
                     'Side street', f"way/{w['id']}"))
poi = json.load(open(os.path.join(DATA, 'poi.geojson')))
for f in poi['features']:
    p = f['properties']
    if p['category'] == 'Commercial' or p['dist_m'] > GENERATOR_REACH: continue
    gens.append((P(*f['geometry']['coordinates']), p['name'], 'Bus stop' if p['category'] == 'Transit' else p['category'], p['osm']))

kept = []
for xy, name, gtype, osm in gens:
    ch, off, side, q = project(xy)
    # places within the junction zones at either end are served by the junction crossings
    if off > GENERATOR_REACH + 10 or ch < JUNCTION_ZONE or ch > TOTAL - JUNCTION_ZONE: continue
    if any(k['type'] == gtype and math.dist(k['xy'], xy) < 15 for k in kept): continue
    kept.append(dict(xy=xy, name=name, type=gtype, osm=osm, ch=ch, off=off, side=side, q=q))
kept.sort(key=lambda k: k['ch'])
for k in kept:
    F(pt(k['xy']), kind='generator', name=k['name'], type=k['type'], osm=k['osm'],
      chainage_m=round(k['ch']), side=k['side'], offset_m=round(k['off']))
    F({"type": "LineString", "coordinates": [U(*k['xy']), U(*k['q'])]}, kind='desire', name=k['name'])

json.dump({"type": "FeatureCollection", "features": feats}, open(os.path.join(DATA, 'crossings.geojson'), 'w'))

# --- construction (Ejipura flyover works) for the scorecard
cons = [{"type": "Feature", "properties": {"name": w['tags'].get('name', 'Construction'), "elevated": w['tags'].get('bridge') == 'yes',
         "osm": f"way/{w['id']}"},
         "geometry": {"type": "LineString", "coordinates": [[round(g['lon'], 7), round(g['lat'], 7)] for g in w['geometry']]}}
        for w in ways.values() if w['tags'].get('highway') == 'construction' or 'construction' in w['tags']]
json.dump({"type": "FeatureCollection", "features": cons}, open(os.path.join(DATA, 'construction.geojson'), 'w'))

# --- report
print(f"centreline {TOTAL:.0f} m")
for c in crossings: print(f"crossing @ {c['ch']:5.0f} m  {c['name']}  [{c['status']}]")
for a, b, L, cls, need in gaps: print(f"gap {a:4.0f}-{b:4.0f} m = {L:4.0f} m  {cls}  needs {need}")
for k in kept: print(f"gen @ {k['ch']:4.0f} m {k['side']:8} {k['off']:3.0f} m off  {k['type']:16} {k['name']}")
print('construction ways', len(cons))
