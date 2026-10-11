#!/usr/bin/env python3
"""Render maps with the per-tile GBC color engine's palettes, from source data.

Usage: tools/colormap.py OUTDIR   (run `make` first so the .2bpp files exist)

Writes:
  OUTDIR/world.png        every map connected to Pallet Town, stitched
  OUTDIR/maps/NAME.png    every map on its own
  OUTDIR/tiles/NAME.png   each tileset's tiles: raw shades, then colored
  OUTDIR/index.html       pan/zoom viewer for the world and the tile inventory
  OUTDIR/data.json        map rectangles, tile palettes and tile usage counts

Colors follow color/loadpalettes.asm at BGP $E4: the tileset's palette set from
MapPaletteSets, tiles mapped through MapPaletteAssignments, and the town roof
colors in palette 6 for the outdoor tilesets. Sprites and animated tiles
(water, flowers) are not drawn; animated tiles show their tileset frame.
"""

import json
import os
import re
import sys
from collections import Counter, deque

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TILESET_SIZE = 0x60
NUM_PALS = 8


def src(path):
    with open(os.path.join(ROOT, path)) as f:
        return f.read()


def strip(line):
    return line.split(';', 1)[0].strip()


def const_list(path):
    """Names from a const_def block, in value order."""
    names = []
    for line in src(path).splitlines():
        m = re.match(r'(?:const|const_export)\s+(\w+)', strip(line))
        if m:
            names.append(m.group(1))
        elif strip(line).startswith('const_skip'):
            names.append(None)
    return names


def label_blocks(text, line_re):
    """Map each label to the first matching line at or after it.
    Consecutive labels share data, as in the asm."""
    out, pending = {}, []
    for line in text.splitlines():
        s = strip(line)
        m = re.match(r'(\w+)::?\s*(.*)$', s)
        if m and not s.startswith(('db', 'dw', 'RGB', 'tilepal', 'INC')):
            pending.append(m.group(1))
            s = m.group(2)
        if not s:
            continue
        m = re.match(line_re, s)
        if m and pending:
            for name in pending:
                out[name] = m.group(1)
            pending = []
    return out


def rgb_triplets(text):
    vals = [int(v) for line in text.splitlines() if strip(line).startswith('RGB')
            for v in re.findall(r'\d+', strip(line)[3:])]
    return [tuple(vals[i:i + 3]) for i in range(0, len(vals), 3)]


def load():
    d = {}
    # Maps: id, size, blocks, tileset, connections.
    d['map_ids'], d['map_size'] = {}, {}
    for line in src('constants/map_constants.asm').splitlines():
        m = re.match(r'map_const\s+(\w+),\s*(\d+),\s*(\d+)', strip(line))
        if m:
            d['map_ids'][m.group(1)] = len(d['map_ids'])
            d['map_size'][m.group(1)] = (int(m.group(2)), int(m.group(3)))
    blk = dict(re.findall(r'(\w+)_Blocks:\s*INCBIN\s*"([^"]+)"', src('maps.asm')))
    d['maps'] = {}
    hdir = os.path.join(ROOT, 'data/maps/headers')
    for fn in sorted(os.listdir(hdir)):
        text = src('data/maps/headers/' + fn)
        m = re.search(r'map_header\s+(\w+),\s*(\w+),\s*(\w+)', text)
        if not m or m.group(1) not in blk:
            continue
        label, const, tileset = m.groups()
        conns = [(c[0], c[2], int(c[3])) for c in
                 re.findall(r'connection\s+(\w+),\s*(\w+),\s*(\w+),\s*(-?\d+)', text)]
        w, h = d['map_size'][const]
        d['maps'][const] = dict(label=label, tileset=tileset, w=w, h=h,
                                blk=blk[label], conns=conns)

    # Tilesets: graphics, blocks, palette map, palette set, in tileset id order.
    tileset_consts = const_list('constants/tileset_constants.asm')
    names = re.findall(r'^\s*tileset\s+(\w+)', src('data/tilesets/tileset_headers.asm'), re.M)
    gfx_text = src('gfx/tilesets.asm')
    gfx = label_blocks(gfx_text, r'INCBIN\s*"([^"]+)"')
    palmap_files = label_blocks(src('color/data/map_palette_assignments.asm'),
                                r'INCLUDE\s*"([^"]+)"')
    palmap_order = re.findall(r'dw\s+(\w+)', src('color/data/map_palette_assignments.asm'))

    pal_consts = {n: i for i, n in enumerate(const_list('color/data/map_palette_constants.asm')) if n}
    # PAL_BG_* are their own const_def blocks: 0-7, then the priority variants.
    bg_names = re.findall(r'const\s+PAL_BG_(\w+)', src('color/data/map_palette_constants.asm'))
    bg_pal = {n: i % 8 for i, n in enumerate(bg_names)}

    set_text = src('color/data/map_palette_sets.asm')
    set_order = re.findall(r'dw\s+(\w+)', set_text)
    sets, pending, cur = {}, [], None
    for line in set_text.splitlines():
        s = strip(line)
        m = re.match(r'(\w+):$', s)
        if m:
            if cur is not None and len(sets[cur]) == NUM_PALS:
                cur = None
            pending.append(m.group(1))
            continue
        m = re.match(r'db\s+(\w+)', s)
        if m:
            if pending:
                cur = pending[0]
                sets[cur] = []
                for p in pending[1:]:
                    sets[p] = sets[cur]
                pending = []
            if cur is not None:
                sets[cur].append(pal_consts[m.group(1)])
    d['map_palettes'] = rgb_triplets(src('color/data/map_palettes.asm'))

    roof_text = src('color/data/roofpalettes.asm')
    roof_order = re.findall(r'dw\s+(\w+)', roof_text.split('PalletRoof:')[0])
    roof_cols = {}
    for name in set(roof_order):
        body = roof_text.split(name + ':', 1)[1]
        roof_cols[name] = rgb_triplets(body)[:2]
    d['roofs'] = [roof_cols[n] for n in roof_order]

    d['tilesets'] = {}
    for i, name in enumerate(names):
        const = tileset_consts[i]
        palmap = []
        for line in src(palmap_files[palmap_order[i]]).splitlines():
            m = re.match(r'tilepal\s+(\d+),\s*(.*)', strip(line))
            if m:
                palmap += [bg_pal[p.strip()] & 7 for p in m.group(2).split(',')]
        palmap = (palmap + [7] * 256)[:TILESET_SIZE] + [7] * (256 - TILESET_SIZE)
        d['tilesets'][const] = dict(
            name=name, id=i,
            gfx=open(os.path.join(ROOT, gfx[name + '_GFX']), 'rb').read(),
            blocks=open(os.path.join(ROOT, gfx[name + '_Block']), 'rb').read(),
            palmap=palmap,
            palset=sets[set_order[i]])
    return d


def to888(c):
    return tuple(v * 255 // 31 for v in c)


def map_palettes(d, const):
    """The 8 BG palettes the engine builds for this map (RGB888)."""
    m = d['maps'][const]
    ts = d['tilesets'][m['tileset']]
    pals = [list(d['map_palettes'][p * 4:p * 4 + 4]) for p in ts['palset']]
    mid = d['map_ids'][const]
    if m['tileset'] in ('OVERWORLD', 'PLATEAU') and mid < len(d['roofs']):
        pals[6][1:3] = d['roofs'][mid]
    return [[to888(c) for c in p] for p in pals]


def tile_pixels(gfx, n):
    raw = gfx[n * 16:n * 16 + 16]
    if len(raw) < 16:
        return None
    return [[((raw[r * 2 + 1] >> (7 - x)) & 1) << 1 | ((raw[r * 2] >> (7 - x)) & 1)
             for x in range(8)] for r in range(8)]


def render_map(d, const, usage=None):
    m = d['maps'][const]
    ts = d['tilesets'][m['tileset']]
    pals = map_palettes(d, const)
    blocks = open(os.path.join(ROOT, m['blk']), 'rb').read()
    # UndergroundPathNorthSouth.blk is shorter than its header says.
    blocks = blocks.ljust(m['w'] * m['h'], b'\0')
    img = Image.new('RGB', (m['w'] * 32, m['h'] * 32))
    px = img.load()
    cache = {}
    for by in range(m['h']):
        for bx in range(m['w']):
            b = blocks[by * m['w'] + bx]
            for t in range(16):
                tile = ts['blocks'][b * 16 + t]
                if usage is not None:
                    usage[(m['tileset'], tile)] += 1
                if tile not in cache:
                    pix = tile_pixels(ts['gfx'], tile) if tile < TILESET_SIZE else None
                    pal = pals[ts['palmap'][tile]]
                    cache[tile] = [[pal[c] for c in row] for row in pix] if pix else None
                rows = cache[tile]
                ox, oy = bx * 32 + (t % 4) * 8, by * 32 + (t // 4) * 8
                for y in range(8):
                    for x in range(8):
                        px[ox + x, oy + y] = rows[y][x] if rows else (255, 0, 255)
    return img


def place_world(d, start='PALLET_TOWN'):
    """Block coordinates of every map reachable through connections."""
    pos, q = {start: (0, 0)}, deque([start])
    while q:
        cur = q.popleft()
        cx, cy = pos[cur]
        cw, ch = d['maps'][cur]['w'], d['maps'][cur]['h']
        for side, tgt, off in d['maps'][cur]['conns']:
            if tgt in pos or tgt not in d['maps']:
                continue
            tw, th = d['maps'][tgt]['w'], d['maps'][tgt]['h']
            pos[tgt] = {'north': (cx + off, cy - th), 'south': (cx + off, cy + ch),
                        'west': (cx - tw, cy + off), 'east': (cx + cw, cy + off)}[side]
            q.append(tgt)
    return pos


def tile_sheet(d, const):
    """Per tileset: 16 tiles per row, each cell raw shades on the left, colored on the right."""
    ts = d['tilesets'][const]
    used = [k for k, m in d['maps'].items() if m['tileset'] == const]
    sample = min(used, key=d['map_ids'].get) if used else None
    pals = map_palettes(d, sample) if sample else [[(255, 0, 255)] * 4] * 8
    gray = [(255, 255, 255), (170, 170, 170), (85, 85, 85), (0, 0, 0)]
    n = min(TILESET_SIZE, len(ts['gfx']) // 16)
    img = Image.new('RGB', (16 * 18, ((n + 15) // 16) * 9), (128, 128, 128))
    px = img.load()
    for t in range(n):
        pix = tile_pixels(ts['gfx'], t)
        ox, oy = (t % 16) * 18, (t // 16) * 9
        pal = pals[ts['palmap'][t]]
        for y in range(8):
            for x in range(8):
                px[ox + x, oy + y] = gray[pix[y][x]]
                px[ox + 9 + x, oy + y] = pal[pix[y][x]]
    return img, n, sample


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'colormap')
    os.makedirs(os.path.join(out, 'maps'), exist_ok=True)
    os.makedirs(os.path.join(out, 'tiles'), exist_ok=True)
    d = load()
    usage = Counter()
    renders = {}
    for const in d['maps']:
        renders[const] = render_map(d, const, usage)
        renders[const].save(os.path.join(out, 'maps', d['maps'][const]['label'] + '.png'))

    pos = place_world(d)
    minx = min(x for x, y in pos.values())
    miny = min(y for x, y in pos.values())
    maxx = max(x + d['maps'][k]['w'] for k, (x, y) in pos.items())
    maxy = max(y + d['maps'][k]['h'] for k, (x, y) in pos.items())
    world = Image.new('RGB', ((maxx - minx) * 32, (maxy - miny) * 32), (24, 24, 32))
    rects = []
    for const, (x, y) in pos.items():
        m = d['maps'][const]
        world.paste(renders[const], ((x - minx) * 32, (y - miny) * 32))
        rects.append(dict(name=m['label'], x=(x - minx) * 32, y=(y - miny) * 32,
                          w=m['w'] * 32, h=m['h'] * 32))
    world.save(os.path.join(out, 'world.png'))

    pal_names = {i: n for i, n in enumerate(const_list('color/data/map_palette_constants.asm')) if n}
    tilesets = []
    for const, ts in d['tilesets'].items():
        img, n, sample = tile_sheet(d, const)
        img.save(os.path.join(out, 'tiles', ts['name'] + '.png'))
        tilesets.append(dict(
            name=ts['name'], const=const, count=n, sample_map=sample,
            palset=[pal_names[p] for p in ts['palset']],
            tiles=[dict(id=t, pal=ts['palmap'][t], uses=usage[(const, t)]) for t in range(n)]))
    data = json.dumps(dict(world=dict(w=world.width, h=world.height), maps=rects,
                           tilesets=tilesets,
                           all_maps=sorted(m['label'] for m in d['maps'].values())))
    with open(os.path.join(out, 'data.json'), 'w') as f:
        f.write(data)
    # Inline the data so the page also works when opened straight from disk.
    with open(os.path.join(out, 'index.html'), 'w') as f:
        f.write(VIEWER.replace('/*DATA*/null', data))
    print(f'{len(d["maps"])} maps, {len(pos)} in the world view ({world.width}x{world.height}), '
          f'{len(tilesets)} tilesets -> {out}')


VIEWER = r'''<!doctype html>
<meta charset="utf-8">
<title>Yellow Color Map</title>
<style>
:root { --bg:#f4f4f2; --fg:#1b1b1f; --mut:#6b6b74; --line:#d6d6d0; --acc:#c03a2b; --panel:#fff }
@media (prefers-color-scheme: dark) { :root { --bg:#16161a; --fg:#e8e8ea; --mut:#9a9aa4; --line:#2e2e36; --acc:#ff7a5c; --panel:#1f1f25 } }
* { box-sizing:border-box }
body { margin:0; font:14px system-ui,sans-serif; background:var(--bg); color:var(--fg) }
nav { display:flex; gap:8px; padding:8px 12px; border-bottom:1px solid var(--line); align-items:center; flex-wrap:wrap }
nav button { font:inherit; padding:4px 10px; border:1px solid var(--line); background:var(--panel); color:var(--fg); border-radius:6px; cursor:pointer }
nav button[aria-pressed=true] { border-color:var(--acc); color:var(--acc) }
#hint { color:var(--mut); margin-left:auto }
#world { position:relative; height:calc(100vh - 45px); overflow:hidden; cursor:grab; background:#18181f; touch-action:none; user-select:none }
#world img { position:absolute; left:0; top:0; transform-origin:0 0; image-rendering:pixelated; -webkit-user-drag:none; pointer-events:none }
#label { position:absolute; pointer-events:none; background:rgba(0,0,0,.75); color:#fff; padding:2px 6px; border-radius:4px; font-size:12px; display:none }
#tiles { display:none; padding:12px }
.ts { margin:0 0 24px }
.ts h2 { font-size:15px; margin:0 0 4px }
.ts p { margin:0 0 8px; color:var(--mut) }
.grid { display:flex; flex-wrap:wrap; gap:6px }
.cell { width:84px; text-align:center; font:11px ui-monospace,monospace; color:var(--mut) }
.cell div { width:72px; height:32px; margin:0 auto; image-rendering:pixelated; background-size:1152px auto; border:1px solid var(--line) }
.cell.unused { opacity:.45 }
</style>
<nav>
  <button id="bw" aria-pressed="true">World</button>
  <button id="bt" aria-pressed="false">Tile inventory</button>
  <span id="hint">drag to pan, wheel to zoom</span>
</nav>
<div id="world"><img id="wimg" src="world.png" alt="Overworld" draggable="false"><div id="label"></div></div>
<div id="tiles"></div>
<script>
const W = document.getElementById('world'), I = document.getElementById('wimg'), L = document.getElementById('label');
let s = 2, x = 0, y = 0, drag = null, data = null;
const apply = () => I.style.transform = `translate(${x}px,${y}px) scale(${s})`;
W.addEventListener('wheel', e => { e.preventDefault();
  const r = W.getBoundingClientRect(), mx = e.clientX - r.left, my = e.clientY - r.top;
  const n = Math.min(16, Math.max(0.25, s * (e.deltaY < 0 ? 1.25 : 0.8)));
  x = mx - (mx - x) * n / s; y = my - (my - y) * n / s; s = n; apply(); }, { passive:false });
W.addEventListener('pointerdown', e => { e.preventDefault(); drag = [e.clientX - x, e.clientY - y];
  W.setPointerCapture(e.pointerId); W.style.cursor = 'grabbing'; });
const stop = () => { drag = null; W.style.cursor = ''; };
W.addEventListener('pointerup', stop);
W.addEventListener('pointercancel', stop);
W.addEventListener('pointermove', e => {
  if (drag) { x = e.clientX - drag[0]; y = e.clientY - drag[1]; apply(); }
  if (!data) return;
  const r = W.getBoundingClientRect(), wx = (e.clientX - r.left - x) / s, wy = (e.clientY - r.top - y) / s;
  const m = data.maps.find(m => wx >= m.x && wx < m.x + m.w && wy >= m.y && wy < m.y + m.h);
  L.style.display = m ? 'block' : 'none';
  if (m) { L.textContent = `${m.name}  block ${Math.floor((wx - m.x) / 32)},${Math.floor((wy - m.y) / 32)}`;
    L.style.left = (e.clientX - r.left + 12) + 'px'; L.style.top = (e.clientY - r.top + 12) + 'px'; }
});
const home = () => { const p = data && data.maps.find(m => m.name === 'PalletTown');
  s = 3; x = W.clientWidth / 2 - (p ? p.x + p.w / 2 : 0) * s; y = W.clientHeight / 2 - (p ? p.y + p.h / 2 : 0) * s; apply(); };
const tab = t => { W.style.display = t ? 'none' : 'block'; document.getElementById('tiles').style.display = t ? 'block' : 'none';
  document.getElementById('bw').setAttribute('aria-pressed', !t); document.getElementById('bt').setAttribute('aria-pressed', !!t);
  document.getElementById('hint').style.visibility = t ? 'hidden' : 'visible'; };
document.getElementById('bw').onclick = () => tab(0);
document.getElementById('bt').onclick = () => tab(1);
Promise.resolve(/*DATA*/null).then(d => { data = d; home();
  const T = document.getElementById('tiles');
  for (const ts of d.tilesets) {
    const sec = document.createElement('section'); sec.className = 'ts';
    sec.innerHTML = `<h2>${ts.name}</h2><p>palettes 0-7: ${ts.palset.join(', ')} &middot; colors shown for ${ts.sample_map || 'no map'} &middot; left raw, right colored &middot; faded = unused in any map</p>`;
    const g = document.createElement('div'); g.className = 'grid';
    for (const t of ts.tiles) {
      const c = document.createElement('div'); c.className = 'cell' + (t.uses ? '' : ' unused');
      const sw = document.createElement('div');
      sw.style.backgroundImage = `url("tiles/${ts.name}.png")`;
      sw.style.backgroundPosition = `-${(t.id % 16) * 72}px -${Math.floor(t.id / 16) * 36}px`;
      c.append(sw, `$${t.id.toString(16).padStart(2, '0')} p${t.pal} ×${t.uses}`);
      g.append(c);
    }
    sec.append(g); T.append(sec);
  }
});
</script>
'''

if __name__ == '__main__':
    main()
