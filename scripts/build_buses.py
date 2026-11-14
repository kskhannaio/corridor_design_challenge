"""Bus stops, routes and frequencies around the Madiwala loop.

Sources
  - BMTC GTFS (unofficial, built from the Namma BMTC 2.0 app) by Vonter - ODbL.
    https://github.com/Vonter/bmtc-gtfs  (download gtfs/bmtc.zip and unzip it)
    Timetables in the app are known to be imperfect: treat counts as indicative.
  - KGIS/KSRSAC BMTC bus stop layer, republished by OpenCity ("bengaluru bus stops and routes",
    bmtc_bus_stops.kml) - used to confirm stop positions and to add stops the GTFS lacks.

Writes
  data/bus_stops.geojson   stops within 500 m: buses per weekday, 8-9 am buses, route numbers, sources
  data/bus_routes.geojson  simplified route paths inside the study area, one line per distinct path
  data/bus_summary.json    buses per weekday along each side of the loop, per direction

Usage: python3 scripts/build_buses.py <gtfs folder> <bmtc_bus_stops.kml>
"""
import collections, csv, json, math, os, sys, xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, '..', 'data')
GTFS, KGIS = sys.argv[1], sys.argv[2]
MAX_DIST = 500            # stops within this distance of the loop
ON_LOOP = 60              # a stop this close to a carriageway serves the loop road itself
SNAP = 35                 # m: a route path this close to a carriageway, going the same way, runs along it
PEAK = ('08:00:00', '09:00:00')
KML = '{http://www.opengis.net/kml/2.2}'

# ---- geometry helpers --------------------------------------------------------------------------
S = json.load(open(os.path.join(DATA, 'stretch.geojson')))['features']
carriageways = [f for f in S if f['properties']['kind'] == 'carriageway']
K = json.load(open(os.path.join(DATA, 'catchments.geojson')))['features']
ring = next(f for f in K if f['properties']['radius_m'] == 500)['geometry']['coordinates'][0]
lon_min, lon_max = min(c[0] for c in ring), max(c[0] for c in ring)
lat_min, lat_max = min(c[1] for c in ring), max(c[1] for c in ring)
R = 6371008.8
kx, ky = math.radians(1) * R * math.cos(math.radians(12.927)), math.radians(1) * R
P = lambda c: (c[0] * kx, c[1] * ky)
in_box = lambda lon, lat, m=0.002: lon_min - m <= lon <= lon_max + m and lat_min - m <= lat <= lat_max + m

def seg_dist(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]; L2 = dx * dx + dy * dy
    t = max(0, min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2)) if L2 else 0
    return math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy), (dx, dy)

cw_segs = [(f['properties']['side'], f['properties']['from'], f['properties']['to'], P(a), P(b))
           for f in carriageways for a, b in zip(f['geometry']['coordinates'], f['geometry']['coordinates'][1:])]

def nearest_side(c):
    p, best = P(c), (1e18, None)
    for side, _, _, a, b in cw_segs:
        d, _ = seg_dist(p, a, b)
        if d < best[0]: best = (d, side)
    return best

def point_in_ring(lon, lat):
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        if (y1 > lat) != (y2 > lat) and lon < (x2 - x1) * (lat - y1) / (y2 - y1) + x1: inside = not inside
    return inside

def simplify(pts, tol):
    """Douglas-Peucker on projected points; returns kept indices."""
    if len(pts) < 3: return list(range(len(pts)))
    keep, stack = {0, len(pts) - 1}, [(0, len(pts) - 1)]
    while stack:
        i, j = stack.pop(); best, idx = 0, None
        for k in range(i + 1, j):
            d, _ = seg_dist(pts[k], pts[i], pts[j])
            if d > best: best, idx = d, k
        if idx is not None and best > tol: keep.add(idx); stack += [(i, idx), (idx, j)]
    return sorted(keep)

# ---- GTFS: weekday trips, stops near the loop ------------------------------------------------------
cal = {r['service_id']: r for r in csv.DictReader(open(os.path.join(GTFS, 'calendar.txt')))}
routes = {r['route_id']: r for r in csv.DictReader(open(os.path.join(GTFS, 'routes.txt')))}
trips = {r['trip_id']: r for r in csv.DictReader(open(os.path.join(GTFS, 'trips.txt')))
         if cal[r['service_id']]['monday'] == '1'}                      # a typical weekday
stops = {}
for r in csv.DictReader(open(os.path.join(GTFS, 'stops.txt'))):
    lon, lat = float(r['stop_lon']), float(r['stop_lat'])
    if not in_box(lon, lat, 0): continue
    d, side = nearest_side([lon, lat])
    if d <= MAX_DIST and point_in_ring(lon, lat):
        stops[r['stop_id']] = dict(name=r['stop_name'], c=[lon, lat], dist=d, side=side)

per_day, per_peak, stop_routes = collections.Counter(), collections.Counter(), collections.defaultdict(set)
trip_hits_area = set()
for r in csv.DictReader(open(os.path.join(GTFS, 'stop_times.txt'))):
    if r['stop_id'] in stops and r['trip_id'] in trips:
        per_day[r['stop_id']] += 1
        if PEAK[0] <= r['arrival_time'] < PEAK[1]: per_peak[r['stop_id']] += 1
        stop_routes[r['stop_id']].add(routes[trips[r['trip_id']]['route_id']]['route_short_name'])
        trip_hits_area.add(r['trip_id'])

# ---- KGIS stops: confirm positions, add stops without a timetable -------------------------------
kgis = []
for pm in ET.parse(KGIS).getroot().iter(KML + 'Placemark'):
    d = {sd.get('name'): sd.text for sd in pm.iter(KML + 'SimpleData')}
    lon, lat = map(float, pm.find(f'.//{KML}coordinates').text.strip().split(',')[:2])
    if in_box(lon, lat, 0) and point_in_ring(lon, lat) and nearest_side([lon, lat])[0] <= MAX_DIST:
        kgis.append(dict(name=d.get('kgisbmtcbusstopname'), c=[lon, lat], id=d.get('kgisbmtcbusstopid')))

feats = []
for sid, s in stops.items():
    confirmed = any(math.dist(P(s['c']), P(k['c'])) < 60 for k in kgis)
    rts = sorted(stop_routes[sid], key=lambda x: (len(x), x))
    feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(v, 6) for v in s['c']]},
                  "properties": {"name": s['name'], "buses_day": per_day[sid], "buses_peak": per_peak[sid],
                                 "n_routes": len(rts), "routes": rts, "dist_m": round(s['dist']), "side": s['side'],
                                 "on_loop": s['dist'] <= ON_LOOP, "timetabled": per_day[sid] > 0,
                                 "confirmed": confirmed, "source": "BMTC GTFS" + (" + KGIS" if confirmed else "")}})
for k in kgis:
    if any(math.dist(P(k['c']), P(s['c'])) < 60 for s in stops.values()): continue
    d, side = nearest_side(k['c'])
    feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(v, 6) for v in k['c']]},
                  "properties": {"name": k['name'], "buses_day": 0, "buses_peak": 0, "n_routes": 0, "routes": [],
                                 "dist_m": round(d), "side": side, "on_loop": d <= ON_LOOP, "timetabled": False,
                                 "confirmed": True, "source": "KGIS only (no timetable)"}})
# OpenStreetMap often maps each side of the road as its own stop. Keep the ones that aren't already
# here (usually the platform on the other side), so the map shows people waiting on both sides.
for f in json.load(open(os.path.join(DATA, 'poi_osm.geojson')))['features']:
    p, c = f['properties'], f['geometry']['coordinates']
    if p['category'] != 'Transit' or p['dist_m'] > MAX_DIST: continue
    if any(math.dist(P(c), P(g['geometry']['coordinates'])) < 50 for g in feats): continue
    d, side = nearest_side(c)
    feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(v, 6) for v in c]},
                  "properties": {"name": p['name'], "buses_day": 0, "buses_peak": 0, "n_routes": 0, "routes": [],
                                 "dist_m": round(d), "side": side, "on_loop": d <= ON_LOOP, "timetabled": False,
                                 "confirmed": False, "source": "OpenStreetMap (no timetable)", "osm": p.get('osm')}})
feats.sort(key=lambda f: -f['properties']['buses_day'])
json.dump({"type": "FeatureCollection", "features": feats}, open(os.path.join(DATA, 'bus_stops.geojson'), 'w'), separators=(',', ':'))

# ---- route paths through the area -----------------------------------------------------------------
# every weekday trip counts, including buses that pass through without stopping in the area
shape_trips = collections.Counter(t['shape_id'] for t in trips.values())
shape_routes = collections.defaultdict(set)
for t in trips.values():
    shape_routes[t['shape_id']].add(routes[t['route_id']]['route_short_name'])
shape_pts, touches = collections.defaultdict(list), set()
for r in csv.DictReader(open(os.path.join(GTFS, 'shapes.txt'))):
    if r['shape_id'] not in shape_trips: continue
    lon, lat = float(r['shape_pt_lon']), float(r['shape_pt_lat'])
    if in_box(lon, lat):
        shape_pts[r['shape_id']].append((int(r['shape_pt_sequence']), lon, lat))
        if not in_box(lon, lat, 0) or point_in_ring(lon, lat): touches.add(r['shape_id'])
shape_pts = {k: v for k, v in shape_pts.items() if k in touches}

side_day = collections.Counter()            # (side, from, to) -> buses per weekday running along it
lines = collections.defaultdict(lambda: {"trips": 0, "routes": set()})
for shp, pts in shape_pts.items():
    pts = [(lon, lat) for _, lon, lat in sorted(pts)]
    # which loop carriageways does this path run along (same direction, within SNAP m, for 120 m or more)?
    along = collections.Counter()
    for a, b in zip(pts, pts[1:]):
        if not in_box(*a): continue
        pa, pb = P(a), P(b); seg = (pb[0] - pa[0], pb[1] - pa[1]); L = math.hypot(*seg)
        if L == 0: continue
        best = None
        for side, fr, to, ca, cb in cw_segs:
            d, cdir = seg_dist(((pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2), ca, cb)
            if d <= SNAP and (seg[0] * cdir[0] + seg[1] * cdir[1]) > 0 and (best is None or d < best[0]): best = (d, (side, fr, to))
        if best: along[best[1]] += L
    for key, L in along.items():
        if L >= 120: side_day[key] += shape_trips[shp]
    # clip to the 500 m area, simplify, and merge identical paths (several routes share a path)
    run = []
    def flush():
        if len(run) >= 2:
            xy = [P(c) for c in run]
            keep = simplify(xy, 4.0)
            key = tuple((round(run[i][0], 5), round(run[i][1], 5)) for i in keep)
            lines[key]["trips"] += shape_trips[shp]; lines[key]["routes"] |= shape_routes[shp]
    prev = None
    for c in pts:
        if point_in_ring(*c) and (prev is None or math.dist(P(prev), P(c)) < 400): run.append(c)
        else:
            flush(); run = [c] if point_in_ring(*c) else []
        prev = c
    flush()

route_feats = [{"type": "Feature", "geometry": {"type": "LineString", "coordinates": [list(c) for c in key]},
                "properties": {"buses_day": v["trips"], "routes": sorted(v["routes"], key=lambda x: (len(x), x))[:40],
                               "n_routes": len(v["routes"])}}
               for key, v in lines.items()]
route_feats.sort(key=lambda f: f['properties']['buses_day'])           # busiest drawn last (on top)
json.dump({"type": "FeatureCollection", "features": route_feats}, open(os.path.join(DATA, 'bus_routes.geojson'), 'w'), separators=(',', ':'))

summary = {"source": "BMTC GTFS (Vonter, from the Namma BMTC 2.0 app; ODbL) and KGIS bus stops via OpenCity",
           "weekday": "Monday", "peak": f"{PEAK[0][:5]}-{PEAK[1][:5]}",
           "sides": {f"{s}:{fr}>{to}": n for (s, fr, to), n in sorted(side_day.items())},
           "stops_on_loop": sum(1 for f in feats if f['properties']['on_loop'] and f['properties']['timetabled']),
           "buses_day_at_loop_stops": sum(f['properties']['buses_day'] for f in feats if f['properties']['on_loop']),
           "buses_peak_at_loop_stops": sum(f['properties']['buses_peak'] for f in feats if f['properties']['on_loop']),
           "routes_at_loop_stops": len(set().union(*[set(f['properties']['routes']) for f in feats if f['properties']['on_loop']]))}
json.dump(summary, open(os.path.join(DATA, 'bus_summary.json'), 'w'), indent=1)

print(f"stops: {len(feats)} ({sum(1 for f in feats if f['properties']['timetabled'])} timetabled, "
      f"{sum(1 for f in feats if f['properties']['source'].startswith('KGIS'))} KGIS-only)")
print(f"route paths: {len(route_feats)} from {len(shape_pts)} GTFS shapes")
print(json.dumps(summary, indent=1))
print('sizes:', {f: os.path.getsize(os.path.join(DATA, f)) for f in ('bus_stops.geojson', 'bus_routes.geojson')})
