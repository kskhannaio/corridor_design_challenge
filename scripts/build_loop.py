"""Assemble the study loop A -> B -> C -> A from OpenStreetMap and write data/stretch.geojson.

Each side is two one-way carriageways (one per direction). They are found by a shortest-path search
over the side's named road, following one-way rules and staying at street level (underpasses and
flyovers are skipped, because people walk beside the surface road).

Usage:
  curl -s --data-urlencode data@scripts/loop_query.overpassql https://overpass-api.de/api/interpreter > /tmp/loop_raw.json
  python3 scripts/build_loop.py /tmp/loop_raw.json
"""
import heapq, json, math, os, sys, collections

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, '..', 'data')

JUNCTIONS = {
    'A': {'name': 'Koramangala Water Tank Junction', 'lonlat': [77.620965, 12.927461],
          'note': 'Sarjapura Rd · 100 Ft Rd · Ejipura flyover landing (u/c)'},
    'B': {'name': 'Madiwala Underpass Junction', 'lonlat': [77.618093, 12.924584],
          'note': 'Hosur Rd · Madiwala underpass · 100 Ft Rd'},
    'C': {'name': "St John's Junction", 'lonlat': [77.614971, 12.929885],
          'note': "Hosur Rd · Sarjapura Rd · Tavarekere Main Rd · St John's Hospital bus stand"},
}
# side id: (from, to, display name, OSM names allowed, extra highway types allowed unnamed)
SIDES = {
    'AB': ('A', 'B', '100 Feet Road (Mahayogi Vemana Road)', {'Mahayogi Vemana Road'}, set()),
    'BC': ('B', 'C', 'Hosur Road', {'Hosur Road'}, {'primary_link', 'trunk_link'}),
    'CA': ('C', 'A', 'Sarjapura Road', {'Sarjapura Road', 'Sarjapur Road'}, set()),
}
ROAD_TYPES = {'primary', 'primary_link', 'trunk', 'trunk_link', 'secondary', 'secondary_link'}

E = json.load(open(sys.argv[1]))['elements']
ways = [e for e in E if e['type'] == 'way' and e.get('tags', {}).get('highway') in ROAD_TYPES]
coord = {}
for w in ways:
    for nid, g in zip(w['nodes'], w['geometry']):
        coord[nid] = (g['lon'], g['lat'])

R = 6371008.8
kx, ky = math.radians(1) * R * math.cos(math.radians(12.927)), math.radians(1) * R
dist = lambda a, b: math.hypot((a[0] - b[0]) * kx, (a[1] - b[1]) * ky)

def street_level(w):
    t = w['tags']
    try: layer = float(t.get('layer', 0))
    except ValueError: layer = 0
    return layer == 0 and t.get('bridge') in (None, 'no') and t.get('tunnel') in (None, 'no')

def graph_for(names, unnamed_types):
    g = collections.defaultdict(list)
    for w in ways:
        t = w['tags']
        if not street_level(w): continue
        if t.get('name') not in names and not (t.get('name') is None and t['highway'] in unnamed_types): continue
        ow = t.get('oneway', 'no')
        ns = w['nodes'] if ow != '-1' else w['nodes'][::-1]
        for a, b in zip(ns, ns[1:]):
            d = dist(coord[a], coord[b])
            g[a].append((b, d, w['id']))
            if ow not in ('yes', '-1', 'true', '1'): g[b].append((a, d, w['id']))
    return g

def route(g, start, end, reach=70, snap=4.0):
    """Shortest one-way-respecting path from near `start` to near `end` (lon/lat).
    Distance to the junction point is weighted by `snap`, so the path runs right up to each junction."""
    pq, best, prev = [], {}, {}
    for n in g:
        d = dist(coord[n], start)
        if d <= reach: best[n] = d * snap; heapq.heappush(pq, (d * snap, n))
    goal, goal_cost = None, float('inf')
    while pq:
        c, n = heapq.heappop(pq)
        if c > best.get(n, float('inf')) or c >= goal_cost: continue
        te = dist(coord[n], end) * snap
        if te <= reach * snap and c + te < goal_cost: goal, goal_cost = n, c + te
        for m, d, wid in g[n]:
            if c + d < best.get(m, float('inf')):
                best[m] = c + d; prev[m] = (n, wid); heapq.heappush(pq, (c + d, m))
    if goal is None: raise SystemExit(f'no route found near {start} -> {end}')
    path, wids, n = [goal], [], goal
    while n in prev:
        n, wid = prev[n]; path.append(n); wids.append(wid)
    path.reverse()
    return path, list(dict.fromkeys(reversed(wids)))

lanes_of = {w['id']: w['tags'].get('lanes') for w in ways}
feats = []
for sid, (a, b, label, names, extra) in SIDES.items():
    g = graph_for(names, extra)
    for frm, to in ((a, b), (b, a)):
        path, wids = route(g, JUNCTIONS[frm]['lonlat'], JUNCTIONS[to]['lonlat'])
        pts = [coord[n] for n in path]
        length = sum(dist(p, q) for p, q in zip(pts, pts[1:]))
        lanes = collections.Counter(lanes_of[w] for w in wids if lanes_of[w]).most_common(1)
        feats.append({"type": "Feature", "properties": {
            "kind": "carriageway", "side": sid, "name": label,
            "direction": f"Towards {JUNCTIONS[to]['name']} ({to})", "from": frm, "to": to,
            "lanes": int(lanes[0][0]) if lanes else None, "oneway": True, "length_m": round(length),
            "osm_ways": [f"way/{w}" for w in wids]},
            "geometry": {"type": "LineString", "coordinates": [[round(x, 7), round(y, 7)] for x, y in pts]}})
        print(f"{sid} {frm}->{to}: {length:5.0f} m  lanes {lanes[0][0] if lanes else '?'}  ways {wids}")

for jid, j in JUNCTIONS.items():
    feats.append({"type": "Feature", "properties": {"kind": "junction", "id": jid, "name": j['name'], "note": j['note']},
                  "geometry": {"type": "Point", "coordinates": j['lonlat']}})
json.dump({"type": "FeatureCollection", "features": feats}, open(os.path.join(DATA, 'stretch.geojson'), 'w'), indent=1)
