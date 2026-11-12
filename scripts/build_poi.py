"""Classify OSM points of interest around the study stretch (output: data/poi_osm.geojson;
scripts/build_places.py then merges Overture and Foursquare into data/poi.geojson) into the
neighbourhood-mapping categories of the GIZ/MoHUA Tactical Urbanism
Guidebook (commercial, recreational, public amenities, healthcare,
religious, institutional, transit) and keep those within 500 m.

Usage:
  curl -s --data-urlencode data@scripts/poi_query.overpassql \
       https://overpass-api.de/api/interpreter > /tmp/poi_raw.json
  python3 scripts/build_poi.py /tmp/poi_raw.json
"""
import json, math, re, sys, collections, os

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, '..', 'data')
MAX_DIST = 500

E = json.load(open(sys.argv[1]))['elements']
s = json.load(open(os.path.join(DATA, 'stretch.geojson')))
lines = [f['geometry']['coordinates'] for f in s['features'] if f['properties']['kind'] == 'carriageway']

lat0 = 12.926
R = 6371008.8
kx = math.radians(1) * R * math.cos(math.radians(lat0))
ky = math.radians(1) * R
P = lambda c: (c[0] * kx, c[1] * ky)
segs = [(P(l[i]), P(l[i + 1])) for l in lines for i in range(len(l) - 1)]

def dist(c):
    p = P(c); best = 1e18
    for a, b in segs:
        dx, dy = b[0] - a[0], b[1] - a[1]; L2 = dx * dx + dy * dy
        t = max(0, min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2)) if L2 else 0
        best = min(best, math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy))
    return best

nice = lambda v: v.replace('_', ' ').capitalize()

def classify(t):
    a, sh, o = t.get('amenity'), t.get('shop'), t.get('office')
    le, tu, hc = t.get('leisure'), t.get('tourism'), t.get('healthcare')
    lu, b, name = t.get('landuse'), t.get('building'), t.get('name', '')
    if t.get('highway') == 'bus_stop' or t.get('public_transport') in ('platform', 'station') or t.get('railway') in ('station', 'halt'):
        return 'Transit', 'Station' if t.get('railway') or t.get('public_transport') == 'station' and t.get('bus') != 'yes' else 'Bus stop'
    if a in ('hospital', 'clinic', 'pharmacy', 'doctors', 'dentist', 'blood_bank') or hc:
        return 'Healthcare', nice(a or hc)
    if a in ('place_of_worship', 'monastery') or lu == 'religious' or b in ('temple', 'mosque', 'church'):
        rel = t.get('religion'); return 'Religious', nice(rel) if rel else 'Place of worship'
    if a in ('school', 'college', 'university', 'kindergarten', 'research_institute') or lu == 'education' or b in ('school', 'college', 'university'):
        return 'Institutional', nice(a or b or 'education')
    if le in ('park', 'garden', 'pitch', 'sports_centre', 'fitness_centre', 'track', 'common', 'playground', 'stadium') \
            or lu == 'recreation_ground' or a in ('theatre', 'cinema', 'arts_centre') or tu == 'museum':
        return 'Recreational', nice(le or a or tu or 'recreation ground')
    if a in ('toilets', 'post_office', 'police', 'fire_station', 'community_centre', 'social_facility', 'library',
             'townhall', 'veterinary', 'drinking_water') or o == 'government' or b in ('public', 'government') \
            or 'indira canteen' in name.lower():
        if 'canteen' in name.lower():
            return 'Public amenities', 'Public canteen'
        return 'Public amenities', nice(a or ('government office' if o == 'government' else b))
    if sh or a in ('restaurant', 'fast_food', 'cafe', 'bar', 'pub', 'bank', 'atm', 'fuel', 'marketplace', 'food_court') \
            or tu in ('hotel', 'hostel', 'guest_house', 'apartment') or o in ('company', 'it', 'financial', 'travel_agent', 'yes') \
            or lu in ('commercial', 'retail'):
        return 'Commercial', nice(sh or a or tu or o or lu)
    return None, None

# unnamed features are only useful for these categories (e.g. public toilets, unnamed bus stops)
KEEP_UNNAMED = {'Transit', 'Public amenities'}
# normalise spelling variants: lowercase, letters only, collapse doubled letters (Ayyappa/Ayyapa)
norm = lambda n: re.sub(r'(.)\1+', r'\1', re.sub(r'[^a-z]', '', n.lower()))

feats, seen = [], []
for e in E:
    t = e.get('tags', {})
    cat, sub = classify(t)
    if not cat:
        continue
    name = t.get('name:en') or t.get('name')
    if not name and cat not in KEEP_UNNAMED:
        continue
    c = [e['lon'], e['lat']] if e['type'] == 'node' else [e['center']['lon'], e['center']['lat']]
    d = dist(c)
    if d > MAX_DIST:
        continue
    name = name or sub
    # same place mapped twice (node + building, or a campus split in parts): same name+category nearby
    # campuses (institutes, grounds, temples complexes) get a wide merge radius; bus stops a tight one so
    # stops on opposite sides of the road stay separate; shops/clinics a small one so chain branches stay separate
    key = norm(name)
    if cat == 'Transit' or not t.get('name'):
        lim = 40
    elif cat in ('Institutional', 'Recreational', 'Religious'):
        lim = 600
    else:
        lim = 60
    if any(k2 == key and c2 == cat and math.hypot((p2[0] - c[0]) * kx, (p2[1] - c[1]) * ky) < lim for k2, c2, p2 in seen):
        continue
    seen.append((key, cat, c))
    feats.append({"type": "Feature",
                  "properties": {"name": name, "category": cat, "type": sub,
                                 "dist_m": int(round(d / 10) * 10), "ring": 300 if d <= 300 else 500,
                                 "osm": f"{e['type']}/{e['id']}"},
                  "geometry": {"type": "Point", "coordinates": [round(c[0], 6), round(c[1], 6)]}})

feats.sort(key=lambda f: f['properties']['dist_m'])
json.dump({"type": "FeatureCollection", "features": feats}, open(os.path.join(DATA, 'poi_osm.geojson'), 'w'), indent=0)

cnt = collections.Counter((f['properties']['category'], f['properties']['ring']) for f in feats)
for cat in ['Transit', 'Institutional', 'Healthcare', 'Religious', 'Recreational', 'Public amenities', 'Commercial']:
    print(f"{cat:18} <=300m:{cnt[(cat, 300)]:3}   300-500m:{cnt[(cat, 500)]:3}")
print('total', len(feats))
