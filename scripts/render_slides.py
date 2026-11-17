"""Slide images of the "What's planned" layers: one group per image, every image the same size and framing.

  python3 scripts/render_slides.py [out_folder]          (default: ../../slides, outside the repo)

For each framing (the loop close up; the whole corridor the drawings cover) and each base map (street map, satellite),
draws: the loop alone, then flyover decks, metro, road tunnel, land, and everything together. Colours are the
website's (PLAN_COLORS in index.html), with darker outlines. 1920 x 1080 px (16:9), so the images drop straight onto
slides at full width. Base maps: Esri World Street Map (softened so the plans stand out) and Esri World Imagery, cached in
~/design_challenge/cache/tiles_*; each image carries its credit.
"""
import json, math, os, sys, urllib.request
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Patch, Polygon as MPoly
from matplotlib.lines import Line2D
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, '..', 'data')
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.abspath(os.path.join(HERE, '..', '..', '..', 'slides'))
os.makedirs(OUT, exist_ok=True)
CACHE = os.path.expanduser('~/design_challenge/cache')

# the website's colours (index.html, PLAN_COLORS); groups as in its Layers panel
COLORS = {'proposed_deck': '#1971c2', 'proposed_deck_level2': '#0b3a75', 'existing_flyover': '#495057', 'ejipura_flyover': '#0c8599',
          'underpass': '#212529', 'metro': '#862e9c', 'metro_station': '#5f3dc4', 'metro_station_land': '#7950f2', 'metro_line': '#5f3dc4',
          'metro_structure': '#7048e8', 'metro_tunnel': '#c2255c', 'tunnel_ramp': '#c2255c', 'tunnel_strip': '#e64980', 'tunnel_tube': '#a61e4d',
          'tunnel_portal': '#a61e4d', 'subway': '#2b8a3e', 'land_acquisition': '#f59f00', 'bmrcl_land': '#099268', 'tunnel_land': '#8c5a2b'}
FILL = {'tunnel': 0.32, 'land': 0.45, 'metro_station_land': 0.4, 'subway': 0.6, 'metro': 0.6, 'roads': 0.5}
NAMES = {'proposed_deck': 'Proposed flyover deck', 'proposed_deck_level2': 'Proposed deck, second level', 'existing_flyover': 'Existing flyovers',
         'ejipura_flyover': 'Ejipura flyover (under construction)', 'underpass': 'Underpass (existing)', 'metro': 'Metro line and stations',
         'metro_station': 'Metro Phase-3A stations', 'metro_station_land': "Land for St John's Hospital station", 'metro_line': 'Metro Phase-3A line',
         'metro_structure': 'Metro structure at junction A', 'metro_tunnel': 'Entry Ramp 08 (into the tunnel)', 'tunnel_ramp': 'Tunnel ramps, incl. Exit Ramp 01',
         'tunnel_strip': 'Tunnel approach to the Audgodi loop', 'tunnel_tube': 'Road tunnel tubes (underground)', 'tunnel_portal': 'TBM shaft',
         'subway': 'Pedestrian subway', 'land_acquisition': 'Land to be acquired', 'bmrcl_land': 'BMRCL (metro) land', 'tunnel_land': 'Land for the road tunnel'}
GROUPS = {'roads': ['proposed_deck', 'proposed_deck_level2', 'existing_flyover', 'ejipura_flyover', 'underpass'],
          'metro': ['metro', 'metro_station', 'metro_line', 'metro_structure', 'metro_station_land', 'subway'],
          'tunnel': ['metro_tunnel', 'tunnel_ramp', 'tunnel_strip', 'tunnel_tube', 'tunnel_portal'],
          'land': ['land_acquisition', 'bmrcl_land', 'tunnel_land']}
GROUP_OF = {l: g for g, ls in GROUPS.items() for l in ls}
SLIDES = [('01_loop', 'The Madiwala loop', []), ('02_flyover', 'Flyover decks and existing flyovers', ['roads']),
          ('03_metro', 'Metro Phase-3A', ['metro']), ('04_tunnel', 'Road tunnel and its ramps', ['tunnel']),
          ('05_land', 'Land to be acquired', ['land']), ('06_all', "Everything planned", ['land', 'roads', 'metro', 'tunnel'])]
FRAMES = {'loop': (77.6118, 12.9222, 77.6245, 12.9318), 'corridor': (77.6075, 12.9050, 77.6385, 12.9345)}
ESRI = 'https://server.arcgisonline.com/ArcGIS/rest/services/{}/MapServer/tile/{{z}}/{{y}}/{{x}}'
BASES = {'street': ([ESRI.format('World_Street_Map')], 'Map: Esri, HERE, Garmin, © OpenStreetMap contributors', 256),
         'satellite': ([ESRI.format('World_Imagery')], 'Imagery: Esri World Imagery', 256)}
W, H, DPI = 1920, 1080, 100

def edge(c, k=0.55): return '#' + ''.join(f'{round(int(c[i:i + 2], 16) * k):02x}' for i in (1, 3, 5))

def merc(lon, lat, z):
    n = 2 ** z
    return (lon + 180) / 360 * n, (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n

def basemap(ax, box, base):
    """tiles covering box, cropped and drawn in lon/lat (Web Mercator stretch is negligible at this size)."""
    urls, credit, ts = BASES[base]
    k = math.cos(math.radians((box[1] + box[3]) / 2))
    z = 17 if box[2] - box[0] < 0.02 else 16
    x0, y1 = merc(box[0], box[1], z); x1, y0 = merc(box[2], box[3], z)
    tx0, ty0, tx1, ty1 = int(x0), int(y0), int(x1), int(y1)
    im = Image.new('RGB', ((tx1 - tx0 + 1) * ts, (ty1 - ty0 + 1) * ts))
    d = os.path.join(CACHE, f'tiles_{base}'); os.makedirs(d, exist_ok=True)
    for tx in range(tx0, tx1 + 1):
        for ty in range(ty0, ty1 + 1):
            tile = None
            for li, url in enumerate(urls):                          # base, then any overlay (place names) on top
                f = os.path.join(d, f'{li}_{z}_{tx}_{ty}.img')
                if not os.path.exists(f):
                    req = urllib.request.Request(url.format(z=z, x=tx, y=ty), headers={'User-Agent': 'madiwala-loop-study-slides/1.0'})
                    open(f, 'wb').write(urllib.request.urlopen(req, timeout=30).read())
                layer = Image.open(f).convert('RGBA').resize((ts, ts))
                tile = layer if tile is None else Image.alpha_composite(tile, layer)
            im.paste(tile.convert('RGB'), ((tx - tx0) * ts, (ty - ty0) * ts))
    im = im.crop((int((x0 - tx0) * ts), int((y0 - ty0) * ts), int((x1 - tx0) * ts), int((y1 - ty0) * ts)))
    if base == 'street': im = Image.blend(im, Image.new('RGB', im.size, (255, 255, 255)), 0.35)   # soften, so the plans stand out
    ax.imshow(im, extent=(box[0], box[2], box[1], box[3]), aspect=1 / k, interpolation='lanczos', zorder=0)
    return credit

def fit(box):
    """widen the shorter side so the box is exactly 16:9 on the ground."""
    k = math.cos(math.radians((box[1] + box[3]) / 2))
    w, h = (box[2] - box[0]) * k, box[3] - box[1]
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    if w / h < 16 / 9: w = h * 16 / 9
    else: h = w * 9 / 16
    return (cx - w / k / 2, cy - h / 2, cx + w / k / 2, cy + h / 2)

plans = [f for f in json.load(open(os.path.join(DATA, 'plans.geojson')))['features'] if f['properties']['kind'] == 'structure']
stretch = json.load(open(os.path.join(DATA, 'stretch.geojson')))['features']
order = ['land', 'roads', 'metro', 'tunnel']                     # drawing order, bottom to top

def rings(g):
    return [g['coordinates'][0]] if g['type'] == 'Polygon' else [p[0] for p in g['coordinates']]

made = []
for fname, fbox in FRAMES.items():
    box = fit(fbox)
    for base in BASES:
        for code, title, groups in SLIDES:
            fig = plt.figure(figsize=(W / DPI, H / DPI), dpi=DPI); ax = fig.add_axes([0, 0, 1, 1]); ax.axis('off')
            credit = basemap(ax, box, base)
            ax.set_xlim(box[0], box[2]); ax.set_ylim(box[1], box[3])
            sat = base == 'satellite'
            used = []
            for g in [g for g in order if g in groups]:
                for f in plans:
                    lay = f['properties']['layer']
                    if GROUP_OF.get(lay) != g: continue
                    c = COLORS[lay]; a = FILL.get(lay, FILL[g])
                    for r in rings(f['geometry']):
                        ax.add_patch(MPoly(r, closed=True, facecolor=c, alpha=min(1, a + (0.15 if sat else 0)), edgecolor='none', zorder=2))
                        ax.add_patch(MPoly(r, closed=True, facecolor='none', edgecolor='white' if sat and g == 'tunnel' else edge(c),
                                           linewidth=1.6, linestyle=(0, (5, 3)) if g == 'tunnel' else '-', zorder=3))
                    if lay not in used: used.append(lay)
            # the loop: strong on its own slide, faded under the plans
            loop_alpha = 1 if not groups else 0.45
            for f in stretch:
                if f['properties'].get('kind') == 'carriageway':
                    xs, ys = zip(*f['geometry']['coordinates'])
                    ax.plot(xs, ys, color='#e4572e', lw=3.2 if not groups else 2.2, alpha=loop_alpha, solid_capstyle='round', zorder=4)
                elif f['properties'].get('kind') == 'junction':
                    x, y = f['geometry']['coordinates']
                    ax.plot(x, y, 'o', ms=22, mfc='#1d1d1b', mec='white', mew=2.2, zorder=6)
                    ax.text(x, y, f['properties']['id'], color='white', fontsize=12, fontweight='bold', ha='center', va='center', zorder=7)
            # legend: what is on this image, in the drawing's order
            handles = [Line2D([], [], color='#e4572e', lw=3, alpha=loop_alpha, label='The loop (A–B–C)')]
            for lay in sorted(used, key=lambda l: list(COLORS).index(l)):
                g = GROUP_OF[lay]
                handles.append(Patch(facecolor=COLORS[lay], alpha=min(1, FILL.get(lay, FILL[g]) + 0.15), edgecolor=edge(COLORS[lay]),
                                     linestyle='--' if g == 'tunnel' else '-', linewidth=1.4, label=NAMES[lay]))
            leg = ax.legend(handles=handles, loc='lower left', fontsize=13, frameon=True, framealpha=0.92, borderpad=0.8,
                            title=title, title_fontproperties={'weight': 'bold', 'size': 15})
            leg.get_frame().set_edgecolor('#bbbbbb')
            ax.text(0.995, 0.006, credit + ' · Plans traced from project drawings; positions approximate', transform=ax.transAxes,
                    ha='right', va='bottom', fontsize=10, color='white' if sat else '#333333',
                    bbox=dict(fc=(0, 0, 0, 0.45) if sat else (1, 1, 1, 0.75), ec='none', pad=2))
            path = os.path.join(OUT, f'{fname}_{base}_{code}.png')
            fig.savefig(path, dpi=DPI); plt.close(fig); made.append(path)
            print('wrote', os.path.basename(path))
print(f'{len(made)} images ({W} x {H}) in {OUT}')
