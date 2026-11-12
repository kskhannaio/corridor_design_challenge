"""Map features from the B-SMILE elevated-corridor contract (see data/contract.json).

Reads the centreline (with chainage from Junction A) in data/crossings.geojson and writes
data/contract.geojson:
  re_wall  - polygon of the existing reinforced-earth flyover approach, drawn to its 8.5 m width
  zone     - centreline segments: junction area / blocked by RE wall / mid-block crossing feasible
  survey   - surveyed widths every 100 m (Schedule A inventory), with footpath flags vs IRC 103

Contract chainage is taken as equal to ours (both start at the Sarjapura Road junction; the contract
puts Madivala junction at 458 m, our centreline measures 460 m).

Usage: python3 scripts/build_contract.py
"""
import json, math, os

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, '..', 'data')
JUNCTION_ZONE = 20

C = json.load(open(os.path.join(DATA, 'contract.json')))
X = json.load(open(os.path.join(DATA, 'crossings.geojson')))
# the contract's survey covers side A-B (100 Ft Road) only
line = next(f for f in X['features'] if f['properties']['kind'] == 'centreline' and f['properties'].get('side') == 'AB')['geometry']['coordinates']

lat0 = 12.926
R = 6371008.8
kx, ky = math.radians(1) * R * math.cos(math.radians(lat0)), math.radians(1) * R
P = lambda c: (c[0] * kx, c[1] * ky)
U = lambda p: [round(p[0] / kx, 7), round(p[1] / ky, 7)]
pts = [P(c) for c in line]
chain = [0.0]
for a, b in zip(pts, pts[1:]): chain.append(chain[-1] + math.dist(a, b))
TOTAL = chain[-1]

def at(ch):
    ch = max(0, min(TOTAL, ch))
    for i in range(len(chain) - 1):
        if chain[i] <= ch <= chain[i + 1]:
            t = (ch - chain[i]) / ((chain[i + 1] - chain[i]) or 1)
            a, b = pts[i], pts[i + 1]
            d = math.dist(a, b) or 1
            return (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])), ((b[0] - a[0]) / d, (b[1] - a[1]) / d)
    return pts[-1], (1, 0)

def segment(a, b, step=3):
    n = max(2, int((b - a) / step) + 1)
    return [at(a + (b - a) * i / (n - 1))[0] for i in range(n)]

def band(a, b, width):
    """polygon of the centreline between chainages a and b, offset +/- width/2."""
    left, right = [], []
    for ch in [a + (b - a) * i / 40 for i in range(41)]:
        p, (dx, dy) = at(ch)
        nx, ny = -dy, dx
        left.append((p[0] + nx * width / 2, p[1] + ny * width / 2))
        right.append((p[0] - nx * width / 2, p[1] - ny * width / 2))
    ring = left + right[::-1] + [left[0]]
    return [[U(p) for p in ring]]

feats = []
F = lambda geom, **props: feats.append({"type": "Feature", "properties": {**props, 'side': 'AB'}, "geometry": geom})

w = C['re_wall']
F({"type": "Polygon", "coordinates": band(w['from'], w['to'], w['width'])}, kind='re_wall',
  name='Ejipura flyover RE wall (existing)', from_m=w['from'], to_m=w['to'], width_m=w['width'], note=w['note'], ref=w['ref'])

zones = [
    (0, JUNCTION_ZONE, 'junction', 'Junction A area', 'Crossing belongs to the junction design'),
    (JUNCTION_ZONE, w['from'], 'junction', 'Junction A approach', 'Ramp landing and junction approach; ties into the junction crossing'),
    (w['from'], w['to'], 'blocked', 'Blocked by the RE wall', 'An 8.5 m earth-filled wall runs down the middle - no at-grade crossing is possible'),
    (w['to'], TOTAL - JUNCTION_ZONE, 'feasible', 'Mid-block crossing feasible', 'Open median (0.6-0.7 m) - an at-grade crossing with a refuge is possible'),
    (TOTAL - JUNCTION_ZONE, TOTAL, 'junction', 'Junction B area', 'Crossing belongs to the junction design'),
]
for a, b, status, name, why in zones:
    F({"type": "LineString", "coordinates": [U(p) for p in segment(a, b)]}, kind='zone', status=status,
      name=name, why=why, from_m=round(a), to_m=round(b), length_m=round(b - a))

std = C['footpath_standard']
def fp_flag(v):
    if v is None: return 'unknown'
    if v == 0: return 'none'
    if v < std['residential_min']: return 'below-1.8'
    if v < std['commercial_min']: return 'below-2.5'
    return 'ok'
order = ['none', 'below-1.8', 'below-2.5', 'ok', 'unknown']
for r in C['inventory']['rows']:
    p, _ = at(r['ch'])
    worst = min((fp_flag(r['fp_lhs']), fp_flag(r['fp_rhs'])), key=order.index)
    cw = (f"{r['cw_lhs']} + {r['median']} + {r['cw_rhs']} m" if r['cw_lhs'] is not None else f"{r['cw_total']} m (undivided)")
    F({"type": "Point", "coordinates": U(p)}, kind='survey', chainage_m=r['ch'], row_m=r['row'],
      cw=cw, cw_total=r['cw_total'], median=r['median'], fp_lhs=r['fp_lhs'], fp_rhs=r['fp_rhs'],
      fp_flag=worst, note=r.get('note', ''),
      label=f"{r['ch']} m · FP {r['fp_lhs']:g} / {r['fp_rhs']:g} m")

    # one dot per side of the road so footpath widths read where they are (LHS = left looking A->B = SE side)
    q, (dx, dy) = at(r['ch'])
    for side, sign, v in (('SE', 1, r['fp_lhs']), ('NW', -1, r['fp_rhs'])):
        off = (r['row'] / 2 - 1.5) * sign
        F({"type": "Point", "coordinates": U((q[0] - dy * off, q[1] + dx * off))}, kind='fp', side=side,
          chainage_m=r['ch'], fp_m=v, fp_flag=fp_flag(v), row_m=r['row'], cw=cw)

json.dump({"type": "FeatureCollection", "features": feats}, open(os.path.join(DATA, 'contract.geojson'), 'w'))
print(f'centreline {TOTAL:.0f} m;', len(feats), 'features')
for f in feats:
    p = f['properties']
    print(' ', p['kind'], {k: v for k, v in p.items() if k in ('status', 'name', 'from_m', 'to_m', 'chainage_m', 'fp_flag', 'label')})
