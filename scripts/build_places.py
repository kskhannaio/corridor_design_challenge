"""Merge places from OpenStreetMap, Overture Maps and Foursquare Open Source Places into data/poi.geojson.

OSM (data/poi_osm.geojson, from build_poi.py) is the base and the only source of bus stops. Overture and
Foursquare add businesses and institutions OSM is missing. Every place keeps its sources; places that only
come from Overture/Foursquare are marked `listed: true` (business listings, not verified on the ground).

Inputs (fetch into any scratch folder, then pass the paths):
  Overture places for the area (CDLA-Permissive-2.0; needs `pip install overturemaps`):
    overturemaps download --bbox=77.60933,12.91907,77.62660,12.93537 -f geojson --type=place -o overture.geojson
  Foursquare OS Places (Apache 2.0; accept the terms at huggingface.co/datasets/foursquare/fsq-os-places,
  then query just this area with DuckDB using your Hugging Face token):
    SELECT fsq_place_id AS id, name, latitude AS lat, longitude AS lon, date_refreshed AS refreshed,
           date_closed AS closed, fsq_category_labels AS cats, unresolved_flags AS flags
    FROM read_parquet('hf://datasets/foursquare/fsq-os-places/release/dt=<latest>/places/parquet/*.parquet')
    WHERE latitude BETWEEN 12.91907 AND 12.93537 AND longitude BETWEEN 77.60933 AND 77.62660
    -> save the rows as a JSON list (fsq.json)

Hand-entered details such as opening hours live in data/place_extras.json and are applied on every build.

Usage: python3 scripts/build_places.py overture.geojson fsq.json
"""
import json, math, os, re, sys, collections
from difflib import SequenceMatcher

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, '..', 'data')
MAX_DIST = 500
OVERTURE_MIN_CONF = 0.5                 # below this, keep only schools, health and places of worship
ALWAYS_KEEP = {'Institutional', 'Healthcare', 'Religious'}
FSQ_REFRESHED_SINCE = '2024'            # Foursquare listings older than this are mostly stale

# --- geometry: distance from the study road -------------------------------------------------------
s = json.load(open(os.path.join(DATA, 'stretch.geojson')))
lines = [f['geometry']['coordinates'] for f in s['features'] if f['properties']['kind'] == 'carriageway']
R = 6371008.8
kx, ky = math.radians(1) * R * math.cos(math.radians(12.926)), math.radians(1) * R
P = lambda c: (c[0] * kx, c[1] * ky)
segs = [(P(l[i]), P(l[i + 1])) for l in lines for i in range(len(l) - 1)]
def road_dist(c):
    p, best = P(c), 1e18
    for a, b in segs:
        dx, dy = b[0] - a[0], b[1] - a[1]; L2 = dx * dx + dy * dy
        t = max(0, min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2)) if L2 else 0
        best = min(best, math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy))
    return best
metres = lambda a, b: math.hypot((a[0] - b[0]) * kx, (a[1] - b[1]) * ky)

# --- categories (same seven as the GIZ guidebook mapping used for OSM) -----------------------------
# Rules match whole words in the category text (underscores and '>' turned into spaces), so that
# "sport" doesn't fire inside "transportation" or "park" inside "parking".
RULES = [
    ('Transit',          r'\bbus (?:station|stop|stand|terminal|depot)s?\b|\bmetro\b|\btrain station\b|\btransit station\b|\blight rail\b|\btaxi stand\b'),
    ('Public amenities', r'\bveterinar\w*|\bgovernment\b|\bpost office\b|\bpolice\b|\bfire station\b|\blibrar\w*|\bcommunity (?:center|centre)\b|\bpublic toilet\b|\btown ?hall\b|\bcourt ?house\b|\bcivic\b|\bpublic service\b'),
    ('Healthcare',       r'\bhospitals?\b|\bclinics?\b|\bdoctors?\b|\bdentist\w*|\bdental\b|\bdentistry\b|\bpharmac\w*|\bmedical\b|\bmedicine\b|\bdiagnostic\w*|\bphysio\w*|\bhealth\b|\bchemist\b|\boutpatient\b|\bsurgery\b'),
    ('Religious',        r'\bplace of worship\b|\btemples?\b|\bmosques?\b|\bmasjid\b|\bchurch\w*|\breligio\w*|\bgurudwara\b|\bshrine\b'),
    ('Institutional',    r'\bschools?\b|\bcolleges?\b|\buniversit\w*|\bresearch\b|\bkindergarten\b|\bpreschool\b|\bprimary\b|\bsecondary\b'),
    ('Recreational',     r'\bparks?\b|\bplaygrounds?\b|\bsports?\b|\bstadium\b|\bgym\b|\bfitness\b|\byoga\b|\bcinemas?\b|\btheat(?:er|re)s?\b|\bmuseums?\b|\bauditorium\b|\brecreation\b|\barts cent(?:er|re)\b|\bswimming\b|\bcricket\b|\bdance studio\b|\bbilliards\b|\bsnooker\b'),
]
NOT_INSTITUTIONAL = r'\btutor\w*|\bcoaching\b|\bdriving\b|\bmusic school\b|\bdance\b|\btraining cent\w*|\bcomputer\b'
ALWAYS_COMMERCIAL = r'\bcafeteria\b|\bcanteen\b|\bparking\b|\bgas station\b|\bfuel\b|\bautomotive\b|\btravel (?:agent|service|agency)\b'
BUS_NAME = r'\bbus (?:stand|stop|station|depot)\b'
def categorise(key, name=''):
    k = re.sub(r'[_>]+', ' ', key.lower())
    if re.search(BUS_NAME, (name or '').lower()): return 'Transit'
    if re.search(ALWAYS_COMMERCIAL, k): return 'Commercial'
    for cat, rx in RULES:
        if re.search(rx, k):
            if cat == 'Institutional' and re.search(NOT_INSTITUTIONAL, k): continue
            return cat
    return 'Commercial'
human = lambda v: (v or 'Place').replace('_', ' ').strip().capitalize()

# --- name matching ----------------------------------------------------------------------------------
GENERIC = r'\b(the|pvt|private|ltd|limited|llp|bangalore|bengaluru|koramangala|madiwala|madivala|btm|layout|branch|' \
          r'block|road|main|cross|stage|india|and|of|in|at)\b'
def norm(n):
    n = re.sub(r'&', ' and ', (n or '').lower())
    n = re.sub(GENERIC, ' ', n)
    n = re.sub(r'[^a-z0-9]+', '', n).replace('w', 'v')           # Madiwala / Madivala
    return re.sub(r'(.)\1+', r'\1', n)                             # Ayyappa / Ayyapa
def similar(a, b):
    a, b = norm(a), norm(b)
    if not a or not b: return 0.0
    if len(a) >= 5 and len(b) >= 5 and (a in b or b in a): return 1.0
    return SequenceMatcher(None, a, b).ratio()
def same_place(p, q):
    d = metres(p['c'], q['c'])
    sim = similar(p['name'], q['name'])
    return (d <= 60 and sim >= 0.82) or (d <= 150 and sim >= 0.95)   # campuses get a wider radius

# --- load sources -----------------------------------------------------------------------------------
places = []
for f in json.load(open(os.path.join(DATA, 'poi_osm.geojson')))['features']:
    p = f['properties']
    places.append(dict(name=p['name'], category=p['category'], type=p['type'], c=f['geometry']['coordinates'],
                       source='OpenStreetMap', sources=['OpenStreetMap'], listed=False, osm=p.get('osm')))

stats = collections.Counter()
ovt = []
for f in json.load(open(sys.argv[1]))['features']:
    p = f['properties']; c = f['geometry']['coordinates']
    name = (p.get('names') or {}).get('primary')
    tax = p.get('taxonomy') or {}
    key = ' '.join([tax.get('primary') or p.get('basic_category') or ''] + (tax.get('hierarchy') or []))
    if not name or road_dist(c) > MAX_DIST: continue
    cat, conf = categorise(key, name), p.get('confidence') or 0
    if conf < OVERTURE_MIN_CONF and cat not in ALWAYS_KEEP: stats['overture dropped: low confidence'] += 1; continue
    ovt.append(dict(name=name, category=cat, type=human(tax.get('primary') or p.get('basic_category')), c=c,
                    source='Overture', sources=['Overture'], listed=True, confidence=round(conf, 2), id=p.get('id') or f.get('id')))
ovt.sort(key=lambda x: -x['confidence'])

fsq = []
for r in json.load(open(sys.argv[2])):
    c = [r['lon'], r['lat']]
    if not r.get('name') or road_dist(c) > MAX_DIST: continue
    if r.get('closed') not in (None, '', 'None') or r.get('flags'): stats['foursquare dropped: closed/flagged'] += 1; continue
    if (r.get('refreshed') or '') < FSQ_REFRESHED_SINCE: stats['foursquare dropped: not updated since 2024'] += 1; continue
    labels = r.get('cats') or []
    leaf = labels[0].split('>')[-1].strip() if labels else 'Place'
    fsq.append(dict(name=r['name'], category=categorise(' '.join(l.split('>')[-1] for l in labels) if labels else '', r['name']),
                    type=leaf, c=c, source='Foursquare', sources=['Foursquare'], listed=True, id=r.get('id')))

# --- merge: OSM first, then Overture, then Foursquare; a match adds the source instead of a new place --
merged = list(places)
for incoming in (ovt, fsq):
    for p in incoming:
        hit = next((q for q in merged if same_place(p, q)), None)
        if hit:
            if p['source'] not in hit['sources']: hit['sources'].append(p['source'])
            if hit['source'] != 'OpenStreetMap' and 'confidence' in p and 'confidence' not in hit: hit['confidence'] = p['confidence']
            stats[f"{p['source'].lower()} matched an existing place"] += 1
        else:
            merged.append(p); stats[f"{p['source'].lower()} added"] += 1

# hand-entered details (opening hours etc.), keyed by OSM id or listing id
extras_path = os.path.join(DATA, 'place_extras.json')
extras = {k: v for k, v in json.load(open(extras_path)).items() if not k.startswith('_')} if os.path.exists(extras_path) else {}

feats = []
for p in merged:
    d = road_dist(p['c'])
    props = {'name': p['name'], 'category': p['category'], 'type': p['type'], 'dist_m': int(round(d / 10) * 10),
             'ring': 300 if d <= 300 else 500, 'source': p['source'], 'sources': p['sources'], 'listed': p['listed']}
    for k in ('osm', 'confidence', 'id'):
        if p.get(k) is not None: props[k] = p[k]
    for k, v in extras.get(p.get('osm') or p.get('id') or '', {}).items():
        if k != 'name': props[k] = v
    feats.append({"type": "Feature", "properties": props,
                  "geometry": {"type": "Point", "coordinates": [round(p['c'][0], 6), round(p['c'][1], 6)]}})
feats.sort(key=lambda f: f['properties']['dist_m'])
json.dump({"type": "FeatureCollection", "features": feats}, open(os.path.join(DATA, 'poi.geojson'), 'w'), separators=(',', ':'))

# --- report -------------------------------------------------------------------------------------------
for k, v in sorted(stats.items()): print(f'{k:45} {v}')
by = collections.Counter(f['properties']['source'] for f in feats)
print('\nplaces by first source:', dict(by), '| total', len(feats), '| within 300 m', sum(f['properties']['dist_m'] <= 300 for f in feats))
cats = ['Transit', 'Institutional', 'Healthcare', 'Religious', 'Recreational', 'Public amenities', 'Commercial']
print(f'\n{"category":18}{"OSM":>6}{"+Overture":>11}{"+Foursquare":>13}{"total":>7}')
for c in cats:
    n = collections.Counter(f['properties']['source'] for f in feats if f['properties']['category'] == c)
    print(f'{c:18}{n["OpenStreetMap"]:>6}{n["Overture"]:>11}{n["Foursquare"]:>13}{sum(n.values()):>7}')
