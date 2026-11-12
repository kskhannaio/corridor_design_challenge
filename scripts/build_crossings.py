"""Crossings & gaps analysis for each side of the study loop A -> B -> C -> A.

Reads data/stretch.geojson (built by build_loop.py) and an Overpass response of
scripts/loop_query.overpassql, and writes:
  data/crossings.geojson    - per side: centreline with distances from the side's first junction,
                              existing crossings, gap segments, 50 m ticks, places people cross to reach
                              (+ desire lines to the road)
  data/construction.geojson - flyover works mapped as construction in OSM

Standards (GIZ/MoHUA Tactical Urbanism Guidebook, after IRC 103 / UTTIPEC):
  mid-block crossings every 80-150 m in commercial/mixed-use areas, 80-250 m in residential.

Usage:
  curl -s --data-urlencode data@scripts/loop_query.overpassql https://overpass-api.de/api/interpreter > /tmp/loop_raw.json
  python3 scripts/build_crossings.py /tmp/loop_raw.json
"""
import json, math, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, '..', 'data')
MIXED_USE_MAX, RESIDENTIAL_MAX = 150, 250
GENERATOR_REACH = 80                    # m from the road for a destination to count as a reason to cross
JUNCTION_ZONE = 20                      # m from either end treated as part of the junction (for reasons to cross)
JUNCTION_REACH = 80                     # signals/crossings this close to a side's end belong to that junction (C is large)
SIDES = ['AB', 'BC', 'CA']

E = json.load(open(sys.argv[1]))['elements']
ways = {e['id']: e for e in E if e['type'] == 'way'}
nodes = {e['id']: e for e in E if e['type'] == 'node'}
for n in nodes.values(): n.setdefault('tags', {})
for w in ways.values():
    w.setdefault('tags', {})
    for nid, g in zip(w['nodes'], w['geometry']):
        nodes.setdefault(nid, {'id': nid, 'lat': g['lat'], 'lon': g['lon'], 'tags': {}})

lat0 = 12.927
R = 6371008.8
kx, ky = math.radians(1) * R * math.cos(math.radians(lat0)), math.radians(1) * R
P = lambda lon, lat: (lon * kx, lat * ky)
U = lambda x, y: [round(x / kx, 7), round(y / ky, 7)]
NP = lambda n: P(n['lon'], n['lat'])

stretch = json.load(open(os.path.join(DATA, 'stretch.geojson')))['features']
junction = {f['properties']['id']: P(*f['geometry']['coordinates']) for f in stretch if f['properties']['kind'] == 'junction'}
loop_centre = tuple(sum(v[i] for v in junction.values()) / 3 for i in (0, 1))

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

class Side:
    """Centreline of one side (midway between its two carriageways), measured from its first junction."""
    def __init__(self, sid):
        cw = [f for f in stretch if f['properties'].get('side') == sid]
        fwd = next(f for f in cw if f['properties']['from'] == sid[0])
        rev = next(f for f in cw if f['properties']['from'] == sid[1])
        a = [P(*c) for c in fwd['geometry']['coordinates']]
        b = [P(*c) for c in rev['geometry']['coordinates']]
        self.id, self.name = sid, fwd['properties']['name']
        self.centre = []
        for p in resample(a, 2.0):
            _, q = nearest_on(b, p)
            self.centre.append(((p[0] + q[0]) / 2, (p[1] + q[1]) / 2))
        self.chain = [0.0]
        for p, q in zip(self.centre, self.centre[1:]): self.chain.append(self.chain[-1] + math.dist(p, q))
        self.length = self.chain[-1]
        self.road_nodes = {n for f in cw for w in f['properties']['osm_ways'] for n in ways[int(w.split('/')[1])]['nodes']}

    def project(self, p):
        """distance along (m), offset from centreline (m), 'inside'/'outside' the loop, foot point."""
        best = (1e18, 0, 0, None)
        for i, (a, b) in enumerate(zip(self.centre, self.centre[1:])):
            dx, dy = b[0] - a[0], b[1] - a[1]; L2 = dx * dx + dy * dy
            t = max(0, min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2)) if L2 else 0
            q = (a[0] + t * dx, a[1] + t * dy); d = math.dist(p, q)
            if d < best[0]:
                cross = dx * (p[1] - a[1]) - dy * (p[0] - a[0])
                inner = dx * (loop_centre[1] - a[1]) - dy * (loop_centre[0] - a[0])
                best = (d, self.chain[i] + t * math.sqrt(L2), 'inside' if (cross > 0) == (inner > 0) else 'outside', q)
        d, ch, where, q = best
        return ch, d, where, q

    def at(self, ch):
        for i in range(len(self.chain) - 1):
            if self.chain[i] <= ch <= self.chain[i + 1]:
                t = (ch - self.chain[i]) / (self.chain[i + 1] - self.chain[i] or 1)
                a, b = self.centre[i], self.centre[i + 1]
                return (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
        return self.centre[-1]

sides = {sid: Side(sid) for sid in SIDES}
feats = []
F = lambda geom, **props: feats.append({"type": "Feature", "properties": props, "geometry": geom})
pt = lambda xy: {"type": "Point", "coordinates": U(*xy)}
signals = [n for n in nodes.values() if n['tags'].get('highway') == 'traffic_signals']
JNAME = {f['properties']['id']: f['properties']['name'] for f in stretch if f['properties']['kind'] == 'junction'}

# places (OSM only, so the analysis rests on mapped, stable data) and bus stops, side streets
poi = json.load(open(os.path.join(DATA, 'poi_osm.geojson')))['features']
candidates = []
for n in nodes.values():
    t = n['tags']
    if t.get('highway') == 'bus_stop' or t.get('public_transport') == 'platform':
        candidates.append((NP(n), t.get('name', 'Bus stop'), 'Bus stop', f"node/{n['id']}", None))
for f in poi:
    p = f['properties']
    if p['category'] == 'Commercial' or p['dist_m'] > GENERATOR_REACH + 20: continue
    candidates.append((P(*f['geometry']['coordinates']), p['name'], 'Bus stop' if p['category'] == 'Transit' else p['category'], p['osm'], None))

report = []
for sid, S in sides.items():
    F({"type": "LineString", "coordinates": [U(*c) for c in S.centre[::3]] + [U(*S.centre[-1])]},
      kind='centreline', side=sid, length_m=round(S.length))

    # existing crossings on this side: crossing nodes on the road, and footway=crossing ways touching it
    found = []
    for nid in S.road_nodes:
        n = nodes[nid]
        if n['tags'].get('highway') == 'crossing' or 'crossing' in n['tags']:
            found.append(dict(xy=NP(n), kind=n['tags'].get('crossing', 'unknown'), osm=f"node/{nid}"))
    for w in ways.values():
        if w['tags'].get('footway') == 'crossing' and S.road_nodes & set(w['nodes']):
            n = nodes[next(iter(S.road_nodes & set(w['nodes'])))]
            found.append(dict(xy=NP(n), kind=w['tags'].get('crossing', 'unknown'), osm=f"way/{w['id']}"))
    crossings = []
    for c in found:
        ch, off, _, _ = S.project(c['xy'])
        if off > 30 or any(math.dist(c['xy'], k['xy']) < 15 for k in crossings): continue
        at_end = ch < JUNCTION_REACH or ch > S.length - JUNCTION_REACH
        crossings.append(dict(xy=c['xy'], ch=ch, osm=c['osm'], verified=True,
                              name=f"Crossing at junction {sid[0] if ch < JUNCTION_REACH else sid[1]}" if at_end else 'Mid-block crossing',
                              type=f"Marked crossing ({c['kind']})"))
    # signals partway along the side (not at its junctions): people can cross on red, but no crossing is mapped
    for n in signals:
        if n['id'] not in S.road_nodes: continue
        ch, off, _, _ = S.project(NP(n))
        if ch < JUNCTION_REACH or ch > S.length - JUNCTION_REACH or any(abs(ch - k['ch']) < 30 for k in crossings): continue
        crossings.append(dict(xy=S.at(ch), ch=ch, osm=f"node/{n['id']}", verified=False,
                              name='Traffic signals mid-way', type='Traffic signals - no marked pedestrian crossing in OSM'))
    # the two junctions at the ends
    for jid, end in ((sid[0], 0.0), (sid[1], S.length)):
        if any(abs(k['ch'] - end) < JUNCTION_REACH for k in crossings): continue
        near = [n for n in signals if math.dist(NP(n), S.at(end)) < 60]
        crossings.append(dict(xy=S.at(end), ch=end, osm=f"node/{near[0]['id']}" if near else '', verified=False,
                              name=f"Junction {jid} ({JNAME[jid]})",
                              type='Traffic signals - no marked pedestrian crossing in OSM' if near else 'No signals or crossing mapped'))
    crossings.sort(key=lambda c: c['ch'])
    for c in crossings:
        F(pt(c['xy']), kind='crossing', side=sid, name=c['name'], type=c['type'], osm=c['osm'],
          chainage_m=round(c['ch']), verified=c['verified'],
          status='Mapped in OSM' if c['verified'] else 'Unverified - check on the walk')

    # gaps between consecutive crossing points
    stops = sorted({0.0, S.length, *[c['ch'] for c in crossings]})
    gaps = []
    for a, b in zip(stops, stops[1:]):
        L = b - a
        if L < 25: continue   # slivers next to a junction crossing aren't real gaps
        cls = 'ok' if L <= MIXED_USE_MAX else 'residential-only' if L <= RESIDENTIAL_MAX else 'too-long'
        need = max(0, math.ceil(L / MIXED_USE_MAX) - 1)
        seg = [S.at(a)] + [S.centre[i] for i in range(len(S.chain)) if a < S.chain[i] < b] + [S.at(b)]
        F({"type": "LineString", "coordinates": [U(*p) for p in seg]}, kind='gap', side=sid,
          from_m=round(a), to_m=round(b), length_m=round(L), status=cls, crossings_needed=need)
        gaps.append((round(a), round(b), round(L), cls, need))

    for ch in range(0, int(S.length) + 1, 50):
        F(pt(S.at(ch)), kind='tick', side=sid, chainage_m=ch, major=(ch % 100 == 0))
    report.append((sid, S, crossings, gaps))

# places people cross to reach: assign each to the nearest side, skip the junction zones
side_streets = []
for w in ways.values():
    hw = w['tags'].get('highway', '')
    if hw not in ('residential', 'service', 'footway', 'living_street', 'tertiary', 'unclassified', 'secondary') or \
       w['tags'].get('footway') in ('crossing', 'sidewalk'): continue
    for sid, S in sides.items():
        for nid in S.road_nodes & set(w['nodes']):
            nm = w['tags'].get('name')
            candidates.append((NP(nodes[nid]), f"Side street: {nm}" if nm else ('Footpath / lane' if hw == 'footway' else 'Side road / gate access'),
                               'Side street', f"way/{w['id']}", sid))
kept = []
for xy, name, gtype, osm, only in candidates:
    best = min(((S.project(xy), sid) for sid, S in sides.items() if only in (None, sid)), key=lambda r: r[0][1])
    (ch, off, where, q), sid = best
    S = sides[sid]
    if off > GENERATOR_REACH + 10 or ch < JUNCTION_ZONE or ch > S.length - JUNCTION_ZONE: continue
    if any(k['type'] == gtype and math.dist(k['xy'], xy) < 15 for k in kept): continue
    kept.append(dict(xy=xy, name=name, type=gtype, osm=osm, side=sid, ch=ch, off=off, where=where, q=q))
kept.sort(key=lambda k: (SIDES.index(k['side']), k['ch']))
for k in kept:
    F(pt(k['xy']), kind='generator', side=k['side'], name=k['name'], type=k['type'], osm=k['osm'],
      chainage_m=round(k['ch']), road_side=k['where'], offset_m=round(k['off']))
    F({"type": "LineString", "coordinates": [U(*k['xy']), U(*k['q'])]}, kind='desire', side=k['side'], name=k['name'])

json.dump({"type": "FeatureCollection", "features": feats}, open(os.path.join(DATA, 'crossings.geojson'), 'w'))

cons = [{"type": "Feature", "properties": {"name": w['tags'].get('name', 'Construction'), "elevated": w['tags'].get('bridge') == 'yes',
         "osm": f"way/{w['id']}"},
         "geometry": {"type": "LineString", "coordinates": [[round(g['lon'], 7), round(g['lat'], 7)] for g in w['geometry']]}}
        # road/flyover works only - not buildings under construction
        for w in ways.values() if w['tags'].get('highway') == 'construction'
        and (w['tags'].get('construction') in ('motorway', 'trunk', 'primary', 'secondary', 'tertiary', 'primary_link', 'trunk_link', 'secondary_link')
             or 'flyover' in w['tags'].get('name', '').lower())]
json.dump({"type": "FeatureCollection", "features": cons}, open(os.path.join(DATA, 'construction.geojson'), 'w'))

for sid, S, crossings, gaps in report:
    print(f"\n== {sid} {S.name}: {S.length:.0f} m")
    for c in crossings: print(f"   crossing @ {c['ch']:4.0f} m  {c['name']:45} {'mapped' if c['verified'] else 'unverified'}  {c['osm']}")
    for g in gaps: print(f"   gap {g[0]:4}-{g[1]:4} m = {g[2]:4} m  {g[3]:16} needs {g[4]}")
    ks = [k for k in kept if k['side'] == sid]
    print(f"   reasons to cross: {len(ks)} ->", ' | '.join(f"{round(k['ch'])}m {k['where'][:3]} {k['name']}" for k in ks))
print('\nconstruction ways', len(cons))
