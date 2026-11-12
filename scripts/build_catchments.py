"""Walking catchments: everything within 300 m and 500 m of any carriageway in data/stretch.geojson.

The area within r of the loop is star-shaped around the loop's centre, so its outline is found by
marching out along 360 bearings to where the distance to the nearest carriageway reaches r.

Usage: python3 scripts/build_catchments.py
"""
import json, math, os

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, '..', 'data')
RINGS = [(300, 4), (500, 7)]                 # metres, minutes at ~4.5 km/h

s = json.load(open(os.path.join(DATA, 'stretch.geojson')))
lines = [f['geometry']['coordinates'] for f in s['features'] if f['properties']['kind'] == 'carriageway']
allpts = [c for l in lines for c in l]
lon0 = sum(c[0] for c in allpts) / len(allpts); lat0 = sum(c[1] for c in allpts) / len(allpts)
R = 6371008.8
kx, ky = math.radians(1) * R * math.cos(math.radians(lat0)), math.radians(1) * R
P = lambda c: ((c[0] - lon0) * kx, (c[1] - lat0) * ky)
U = lambda p: [round(lon0 + p[0] / kx, 6), round(lat0 + p[1] / ky, 6)]
segs = [(P(l[i]), P(l[i + 1])) for l in lines for i in range(len(l) - 1)]

def dist(p):
    best = 1e18
    for a, b in segs:
        dx, dy = b[0] - a[0], b[1] - a[1]; L2 = dx * dx + dy * dy
        t = max(0, min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2)) if L2 else 0
        best = min(best, math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy))
    return best

feats = []
for r, mins in RINGS:
    ring = []
    for k in range(360):
        th = math.radians(k); lo, hi = 0.0, r + 3000
        for _ in range(40):
            m = (lo + hi) / 2
            if dist((m * math.cos(th), m * math.sin(th))) <= r: lo = m
            else: hi = m
        ring.append(U((lo * math.cos(th), lo * math.sin(th))))
    ring.append(ring[0])
    err = max(abs(dist(P(c)) - r) for c in ring)
    print(f'{r} m ring: max deviation {err:.2f} m')
    feats.append({"type": "Feature", "properties": {"radius_m": r, "walk_min": mins, "label": f"{r} m · ~{mins} min walk"},
                  "geometry": {"type": "Polygon", "coordinates": [ring]}})
json.dump({"type": "FeatureCollection", "features": feats}, open(os.path.join(DATA, 'catchments.geojson'), 'w'))
xs = [c[0] for f in feats for c in f['geometry']['coordinates'][0]]; ys = [c[1] for f in feats for c in f['geometry']['coordinates'][0]]
print(f'500 m bbox (lat/lon): {min(ys):.5f},{min(xs):.5f},{max(ys):.5f},{max(xs):.5f}')
