#!/usr/bin/env python3
"""Render maps with the per-tile GBC color engine's palettes, from source data.

Usage: tools/colormap.py OUTDIR   (run `make` first so the .2bpp files exist)

Writes:
  OUTDIR/world.png        every map connected to Pallet Town, stitched
  OUTDIR/maps/NAME.png    every map on its own
  OUTDIR/tiles/NAME.png   each tileset's tiles: raw shades, then colored
  OUTDIR/index.html       pan/zoom viewer; click a warp to follow it, plus the tile inventory
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

from PIL import Image, ImageDraw

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
    blk = {k[:-len('_Blocks')]: v for k, v in
           label_blocks(src('maps.asm'), r'INCBIN\s*"([^"]+)"').items() if k.endswith('_Blocks')}
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
        obj = os.path.join(ROOT, 'data/maps/objects', label + '.asm')
        otext = open(obj).read() if os.path.exists(obj) else ''
        warps = [(int(x), int(y), dest, int(n)) for x, y, dest, n in
                 re.findall(r'warp_event\s+(\d+),\s*(\d+),\s*(\w+),\s*(\d+)', otext)]
        # object_event x, y, sprite, movement, facing, text[, item | trainer class, number]
        objects = []
        for line in otext.splitlines():
            m2 = re.match(r'object_event\s+(.*)', strip(line))
            if m2:
                a = [v.strip() for v in m2.group(1).split(',')]
                objects.append(dict(x=int(a[0]), y=int(a[1]), sprite=a[2], move=a[3], facing=a[4],
                                    item=a[6] if len(a) == 7 else None,
                                    trainer=' '.join(a[6:8]) if len(a) >= 8 else None))
        d['maps'][const] = dict(label=label, tileset=tileset, w=w, h=h,
                                blk=blk[label], conns=conns, warps=warps, objects=objects)

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

    d['hidden_items'] = {}
    for mp, x, y in re.findall(r'hidden_item\s+(\w+),\s*(\d+),\s*(\d+)',
                               src('data/events/hidden_item_coords.asm')):
        d['hidden_items'].setdefault(mp, []).append((int(x), int(y)))

    # Overworld sprites: graphics, standing frames, and their CGB palette (color/sprites.asm).
    sprite_ids = {n: i for i, n in enumerate(const_list('constants/sprite_constants.asm')) if n}
    sheets = re.findall(r'overworld_sprite\s+(\w+),\s*(\d+)', src('data/sprites/sprites.asm'))
    sgfx = label_blocks(src('gfx/sprites.asm'), r'INCBIN\s*"([^"]+)"')
    spr_pal = {n: int(v) for n, v in re.findall(r'DEF (SPR_PAL_\w+)\s+EQU\s+(\d+)', src('color/sprites.asm'))}
    assign = re.findall(r'db\s+(SPR_PAL_\w+)', src('color/sprites.asm').split('SpritePaletteAssignments:')[1])
    pal_text = src('color/data/spritepalettes.asm')
    d['sprite_palettes'] = {}
    for name in ('SpritePalettes', 'SpritePalettesNite', 'SpritePalettesPokecenter'):
        body = pal_text.split(name + ':', 1)[1]
        cols = rgb_triplets(body)[:32]
        d['sprite_palettes'][name] = [cols[i:i + 4] for i in range(0, 32, 4)]
    d['sprites'] = {}
    for i, (label, ntiles) in enumerate(sheets):
        path = os.path.join(ROOT, sgfx[label].replace('.2bpp', '.png'))
        d['sprites'][i + 1] = dict(png=path, tiles=int(ntiles),
                                   pal=spr_pal[assign[i]] if i < len(assign) else 0)
    d['sprite_ids'] = sprite_ids

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


LAB_FLOOR_TILES = (0x11, 0x0b, 0x0c, 0x1b, 0x1c, 0x20, 0x21, 0x30, 0x31, 0x36, 0x37,
                   0x48, 0x49, 0x4a, 0x4b, 0x55, 0x5b, 0x5c, 0x5d, 0x5e, 0x5f)  # LabFloorTiles

# Per-map tile palette patches that color/loadpalettes.asm applies at runtime.
RUNTIME_PALMAP = {
    'CELADON_MART_ROOF': {t: 3 for t in range(0x4b, 0x50)},             # PAL_BG_WATER
    'CELADON_MART_1F': {t: 4 for t in (0x07, 0x08, 0x17, 0x18)},        # PAL_BG_YELLOW
    'CERULEAN_GYM': {t: 5 for t in (0x01, 0x11, 0x09, 0x0a, 0x19, 0x1a)},  # PAL_BG_BROWN
    'LORELEIS_ROOM': {t: 5 for t in (0x01, 0x11, 0x09, 0x0a, 0x19, 0x1a)},
    'OAKS_LAB': {t: 4 for t in LAB_FLOOR_TILES},                        # DojoPalSet LAB_FLOOR
    'LANCES_ROOM': {t: 4 for t in LAB_FLOOR_TILES},
    'FIGHTING_DOJO': {0x11: 2},                                         # DojoPalSet DOJO_FLOOR
}


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
    palmap = list(ts['palmap'])
    for t, p in RUNTIME_PALMAP.get(const, {}).items():
        palmap[t] = p
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
                    pal = pals[palmap[tile]]
                    cache[tile] = [[pal[c] for c in row] for row in pix] if pix else None
                rows = cache[tile]
                ox, oy = bx * 32 + (t % 4) * 8, by * 32 + (t // 4) * 8
                for y in range(8):
                    for x in range(8):
                        px[ox + x, oy + y] = rows[y][x] if rows else (255, 0, 255)
    return img


def sprite_palettes(d, const):
    """OBJ palettes the engine loads for this map (LoadOverworldSpritePalettes)."""
    ts = d['maps'][const]['tileset']
    name = ('SpritePalettesNite' if ts == 'CAVERN' else
            'SpritePalettesPokecenter' if ts == 'POKECENTER' or const == 'INDIGO_PLATEAU_LOBBY' else
            'SpritePalettes')
    return [[to888(c) for c in p] for p in d['sprite_palettes'][name]]


_sheet_cache = {}


def sprite_frame(d, sid, facing):
    """16x16 shade grid of a sprite's standing frame; None if the sprite has no graphics."""
    spr = d['sprites'].get(sid)
    if not spr or not os.path.exists(spr['png']):
        return None
    if spr['png'] not in _sheet_cache:
        _sheet_cache[spr['png']] = Image.open(spr['png']).convert('L')
    sheet = _sheet_cache[spr['png']]
    # Standing frames are down, up, left; right is the left frame mirrored.
    frame = {'UP': 1, 'LEFT': 2, 'RIGHT': 2}.get(facing, 0) if spr['tiles'] >= 12 else 0
    box = sheet.crop((0, frame * 16, 16, frame * 16 + 16))
    if facing == 'RIGHT' and spr['tiles'] >= 12:
        box = box.transpose(Image.FLIP_LEFT_RIGHT)
    shade = {255: 0, 170: 1, 85: 2, 0: 3}
    return [[shade.get(box.getpixel((x, y)), 3) for x in range(16)] for y in range(16)]


def object_layers(d, const):
    """Transparent overlays of a map's NPCs, item balls and hidden items, plus hover info."""
    m = d['maps'][const]
    size = (m['w'] * 32, m['h'] * 32)
    layers = {k: Image.new('RGBA', size, (0, 0, 0, 0)) for k in ('npcs', 'items', 'hidden')}
    pals = sprite_palettes(d, const)
    info = []
    for n, o in enumerate(m['objects'], 1):
        kind = 'items' if o['item'] else 'npcs'
        sid = d['sprite_ids'].get(o['sprite'])
        grid = sprite_frame(d, sid, o['facing'])
        p = d['sprites'].get(sid, {}).get('pal', 0)
        if p == 8:   # SPR_PAL_RANDOM: the engine picks by sprite slot; Bill is brown
            p = 3 if const == 'BILLS_HOUSE' else n & 3
        pal = pals[p if p < 8 else 0]
        ox, oy = o['x'] * 16, o['y'] * 16 - 4      # sprites sit 4px higher than their square
        if grid:
            px = layers[kind].load()
            for y in range(16):
                for x in range(16):
                    v = grid[y][x]
                    if v and 0 <= ox + x < size[0] and 0 <= oy + y < size[1]:
                        px[ox + x, oy + y] = pal[v] + (255,)
        label = o['sprite'].replace('SPRITE_', '').lower()
        if o['item']:
            label += ': ' + o['item']
        elif o['trainer']:
            label += ': trainer ' + o['trainer']
        info.append(dict(x=o['x'] * 16, y=o['y'] * 16, layer=kind, text=label))
    dr = ImageDraw.Draw(layers['hidden'])
    for x, y in d['hidden_items'].get(const, []):
        cx, cy = x * 16 + 8, y * 16 + 8
        dr.ellipse((cx - 6, cy - 6, cx + 6, cy + 6), outline=(255, 0, 200, 255), width=2)
        dr.ellipse((cx - 1, cy - 1, cx + 1, cy + 1), fill=(255, 0, 200, 255))
        info.append(dict(x=x * 16, y=y * 16, layer='hidden', text='hidden item'))
    return layers, info


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


def resolve_warps(d):
    """Each warp's destination as (map const, x, y) in map squares (16px).
    LAST_MAP returns to whichever map warped in, so list every such map."""
    into = {}
    for const, m in d['maps'].items():
        for x, y, dest, n in m['warps']:
            into.setdefault(dest, []).append(const)
    out = {}
    for const, m in d['maps'].items():
        res = []
        for x, y, dest, n in m['warps']:
            targets = []
            for t in (sorted(set(into.get(const, []))) if dest == 'LAST_MAP' else [dest]):
                tw = d['maps'].get(t, {}).get('warps', [])
                # A LAST_MAP exit lands on the warp in the previous map that led here.
                if 0 < n <= len(tw) and (dest != 'LAST_MAP' or tw[n - 1][2] == const):
                    targets.append((t, tw[n - 1][0], tw[n - 1][1]))
            # Doors lead outside more often than upstairs; list outdoor maps first.
            targets.sort(key=lambda t: d['maps'][t[0]]['tileset'] not in ('OVERWORLD', 'PLATEAU'))
            res.append((x, y, targets))
        out[const] = res
    return out


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
    layers, objinfo = {}, {}
    for const in d['maps']:
        label = d['maps'][const]['label']
        renders[const] = render_map(d, const, usage)
        renders[const].save(os.path.join(out, 'maps', label + '.png'))
        layers[const], objinfo[const] = object_layers(d, const)
        for k, im in layers[const].items():
            im.save(os.path.join(out, 'maps', f'{label}.{k}.png'))

    pos = place_world(d)
    minx = min(x for x, y in pos.values())
    miny = min(y for x, y in pos.values())
    maxx = max(x + d['maps'][k]['w'] for k, (x, y) in pos.items())
    maxy = max(y + d['maps'][k]['h'] for k, (x, y) in pos.items())
    world = Image.new('RGB', ((maxx - minx) * 32, (maxy - miny) * 32), (24, 24, 32))
    wlayers = {k: Image.new('RGBA', world.size, (0, 0, 0, 0)) for k in ('npcs', 'items', 'hidden')}
    for const, (x, y) in pos.items():
        at = ((x - minx) * 32, (y - miny) * 32)
        world.paste(renders[const], at)
        for k, im in layers[const].items():
            wlayers[k].alpha_composite(im, at)
    world.save(os.path.join(out, 'world.png'))
    for k, im in wlayers.items():
        im.save(os.path.join(out, f'world.{k}.png'))

    warps = resolve_warps(d)
    label = {k: m['label'] for k, m in d['maps'].items()}
    maps = {}
    for const, m in d['maps'].items():
        wpos = pos.get(const)
        maps[m['label']] = dict(
            w=m['w'] * 32, h=m['h'] * 32,
            world=[(wpos[0] - minx) * 32, (wpos[1] - miny) * 32] if wpos else None,
            warps=[dict(x=x * 16, y=y * 16,
                        to=[dict(map=label[t], x=tx * 16, y=ty * 16) for t, tx, ty in targets])
                   for x, y, targets in warps[const]],
            objects=objinfo[const])

    pal_names = {i: n for i, n in enumerate(const_list('color/data/map_palette_constants.asm')) if n}
    tilesets = []
    for const, ts in d['tilesets'].items():
        img, n, sample = tile_sheet(d, const)
        img.save(os.path.join(out, 'tiles', ts['name'] + '.png'))
        tilesets.append(dict(
            name=ts['name'], const=const, count=n, sample_map=sample,
            palset=[pal_names[p] for p in ts['palset']],
            tiles=[dict(id=t, pal=ts['palmap'][t], uses=usage[(const, t)]) for t in range(n)]))
    data = json.dumps(dict(world=dict(w=world.width, h=world.height), maps=maps,
                           tilesets=tilesets))
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
nav { display:flex; gap:8px; padding:8px 12px; border-bottom:1px solid var(--line); align-items:center; flex-wrap:wrap; height:45px }
nav button, nav select { font:inherit; padding:4px 10px; border:1px solid var(--line); background:var(--panel); color:var(--fg); border-radius:6px; cursor:pointer }
nav button[aria-pressed=true] { border-color:var(--acc); color:var(--acc) }
#where { font-weight:600 }
#hint { color:var(--mut); margin-left:auto }
#view { position:relative; height:calc(100vh - 45px); overflow:hidden; cursor:grab; background:#18181f; touch-action:none; user-select:none }
#stage { position:absolute; left:0; top:0; transform-origin:0 0 }
#stage img { display:block; image-rendering:pixelated; -webkit-user-drag:none; pointer-events:none }
#stage img.layer { position:absolute; left:0; top:0 }
body.no-npcs #lnpcs, body.no-items #litems, body.no-hidden #lhidden { display:none }
#marks { position:absolute; inset:0; pointer-events:none }
.warp { position:absolute; width:16px; height:16px; outline:1px solid rgba(255,214,0,.9); background:rgba(255,214,0,.18) }
.warp.dead { outline-color:rgba(255,80,80,.9); background:rgba(255,80,80,.18) }
body.nowarps .warp { display:none }
.here { position:absolute; width:16px; height:16px; outline:2px solid #00e5ff; box-shadow:0 0 0 3px rgba(0,229,255,.35); animation:pulse 1s ease-in-out 3 }
@keyframes pulse { 50% { box-shadow:0 0 0 7px rgba(0,229,255,0) } }
#label { position:absolute; pointer-events:none; background:rgba(0,0,0,.8); color:#fff; padding:3px 7px; border-radius:4px; font-size:12px; display:none; white-space:pre }
#tiles { display:none; padding:12px; height:calc(100vh - 45px); overflow:auto }
.ts { margin:0 0 24px }
.ts h2 { font-size:15px; margin:0 0 4px }
.ts p { margin:0 0 8px; color:var(--mut) }
.grid { display:flex; flex-wrap:wrap; gap:6px }
.cell { width:84px; text-align:center; font:11px ui-monospace,monospace; color:var(--mut) }
.cell div { width:72px; height:32px; margin:0 auto; image-rendering:pixelated; background-size:1152px auto; border:1px solid var(--line) }
.cell.unused { opacity:.45 }
</style>
<nav>
  <button id="bw">World</button>
  <select id="pick" aria-label="Open a map"></select>
  <button id="bwarps" aria-pressed="true">Warps</button>
  <button class="lay" data-layer="npcs" aria-pressed="true">NPCs</button>
  <button class="lay" data-layer="items" aria-pressed="true">Items</button>
  <button class="lay" data-layer="hidden" aria-pressed="true">Hidden items</button>
  <button id="bt">Tile inventory</button>
  <span id="where"></span>
  <span id="hint">drag to pan, wheel to zoom, click a yellow warp to follow it, Back to return</span>
</nav>
<div id="view"><div id="stage"><img id="vimg" alt="" draggable="false"><img id="lnpcs" class="layer" alt="" draggable="false"><img id="litems" class="layer" alt="" draggable="false"><img id="lhidden" class="layer" alt="" draggable="false"><div id="marks"></div></div><div id="label"></div></div>
<div id="tiles"></div>
<script>
const data = /*DATA*/null;
const V = document.getElementById('view'), S = document.getElementById('stage'), I = document.getElementById('vimg'),
      M = document.getElementById('marks'), L = document.getElementById('label'), T = document.getElementById('tiles');
let s = 3, x = 0, y = 0, drag = null, cur = null, warps = [], rects = [], objs = [];
const LAYERS = ['npcs', 'items', 'hidden'];
const apply = () => S.style.transform = `translate(${x}px,${y}px) scale(${s})`;
const worldMaps = Object.entries(data.maps).filter(([, m]) => m.world);

// Where a warp target lands: in the world view when the map is outdoors.
const link = t => { const m = data.maps[t.map];
  return m.world ? `#world@${m.world[0] + t.x},${m.world[1] + t.y}` : `#map/${t.map}@${t.x},${t.y}`; };

function show(hash) {
  const [route, at] = (hash.replace(/^#/, '') || 'world').split('@');
  const tiles = route === 'tiles';
  V.style.display = tiles ? 'none' : 'block'; T.style.display = tiles ? 'block' : 'none';
  document.getElementById('bt').setAttribute('aria-pressed', tiles);
  document.getElementById('bw').setAttribute('aria-pressed', route === 'world');
  document.getElementById('hint').style.visibility = tiles ? 'hidden' : 'visible';
  if (tiles) { document.getElementById('where').textContent = ''; return; }
  let w, h;
  if (route.startsWith('map/') && data.maps[route.slice(4)]) {
    const name = route.slice(4), m = data.maps[name];
    cur = name; I.src = `maps/${name}.png`; w = m.w; h = m.h; rects = [[name, 0, 0, m.w, m.h]];
    warps = m.warps.map(wp => ({ ...wp, from: name }));
    objs = m.objects;
    for (const l of LAYERS) document.getElementById('l' + l).src = `maps/${name}.${l}.png`;
  } else {
    cur = null; I.src = 'world.png'; w = data.world.w; h = data.world.h;
    rects = worldMaps.map(([n, m]) => [n, m.world[0], m.world[1], m.w, m.h]);
    warps = worldMaps.flatMap(([n, m]) => m.warps.map(wp => ({ ...wp, from: n, x: wp.x + m.world[0], y: wp.y + m.world[1] })));
    objs = worldMaps.flatMap(([n, m]) => m.objects.map(o => ({ ...o, x: o.x + m.world[0], y: o.y + m.world[1] })));
    for (const l of LAYERS) document.getElementById('l' + l).src = `world.${l}.png`;
  }
  S.style.width = w + 'px'; S.style.height = h + 'px';
  document.getElementById('where').textContent = cur || 'Overworld';
  document.getElementById('pick').value = cur || '';
  M.replaceChildren(...warps.map(wp => { const e = document.createElement('div');
    e.className = 'warp' + (wp.to.length ? '' : ' dead'); e.style.left = wp.x + 'px'; e.style.top = wp.y + 'px'; return e; }));
  let fx = w / 2, fy = h / 2;
  if (at) { [fx, fy] = at.split(',').map(Number); const e = document.createElement('div');
    e.className = 'here'; e.style.left = fx + 'px'; e.style.top = fy + 'px'; M.append(e); fx += 8; fy += 8; }
  else if (!cur) { const p = data.maps.PalletTown; fx = p.world[0] + p.w / 2; fy = p.world[1] + p.h / 2; }
  s = cur && !at ? Math.max(1, Math.min(6, Math.floor(Math.min(V.clientWidth / w, V.clientHeight / h)))) : 3;
  x = V.clientWidth / 2 - fx * s; y = V.clientHeight / 2 - fy * s; apply(); L.style.display = 'none';
}

const at = e => { const r = V.getBoundingClientRect(); return [(e.clientX - r.left - x) / s, (e.clientY - r.top - y) / s, e.clientX - r.left, e.clientY - r.top]; };
const hit = (wx, wy) => warps.find(w => wx >= w.x && wx < w.x + 16 && wy >= w.y && wy < w.y + 16);
V.addEventListener('wheel', e => { e.preventDefault();
  const r = V.getBoundingClientRect(), mx = e.clientX - r.left, my = e.clientY - r.top;
  const n = Math.min(16, Math.max(0.25, s * (e.deltaY < 0 ? 1.25 : 0.8)));
  x = mx - (mx - x) * n / s; y = my - (my - y) * n / s; s = n; apply(); }, { passive:false });
V.addEventListener('pointerdown', e => { e.preventDefault(); drag = { sx:e.clientX, sy:e.clientY, ox:e.clientX - x, oy:e.clientY - y, moved:false };
  V.setPointerCapture(e.pointerId); V.style.cursor = 'grabbing'; });
V.addEventListener('pointerup', e => {
  const d = drag; drag = null; V.style.cursor = '';
  if (!d || d.moved) return;
  const [wx, wy] = at(e), w = hit(wx, wy);
  if (w && w.to.length) location.hash = link(w.to[0]);
});
V.addEventListener('pointercancel', () => { drag = null; V.style.cursor = ''; });
V.addEventListener('pointermove', e => {
  if (drag) { if (Math.abs(e.clientX - drag.sx) + Math.abs(e.clientY - drag.sy) > 4) drag.moved = true;
    if (drag.moved) { x = e.clientX - drag.ox; y = e.clientY - drag.oy; apply(); } }
  const [wx, wy, mx, my] = at(e), r = rects.find(r => wx >= r[1] && wx < r[1] + r[3] && wy >= r[2] && wy < r[2] + r[4]);
  const w = hit(wx, wy);
  if (!drag) V.style.cursor = w && w.to.length ? 'pointer' : '';  // warps stay clickable when hidden
  if (!r) { L.style.display = 'none'; return; }
  let t = `${r[0]}  (${Math.floor((wx - r[1]) / 16)}, ${Math.floor((wy - r[2]) / 16)})`;
  if (w) t += w.to.length ? `\n→ ${w.to.map(t => t.map).join('\n   or ')}` : '\n→ set by a script';
  for (const o of objs) if (wx >= o.x && wx < o.x + 16 && wy >= o.y && wy < o.y + 16 && !document.body.classList.contains('no-' + o.layer)) t += `\n${o.text}`;
  L.textContent = t; L.style.display = 'block'; L.style.left = (mx + 14) + 'px'; L.style.top = (my + 14) + 'px';
});

const pick = document.getElementById('pick');
pick.append(new Option('Open a map…', ''), ...Object.keys(data.maps).sort().map(n => new Option(n, n)));
pick.onchange = () => { if (pick.value) location.hash = '#map/' + pick.value; };
document.getElementById('bw').onclick = () => location.hash = '#world';
document.getElementById('bt').onclick = () => location.hash = '#tiles';
const BW = document.getElementById('bwarps');
const setWarps = on => { document.body.classList.toggle('nowarps', !on); BW.setAttribute('aria-pressed', on);
  try { localStorage.setItem('warps', on ? '1' : '0'); } catch (e) {} };
BW.onclick = () => setWarps(document.body.classList.contains('nowarps'));
try { setWarps(localStorage.getItem('warps') !== '0'); } catch (e) {}
const setLayer = (l, on) => { document.body.classList.toggle('no-' + l, !on);
  document.querySelector(`.lay[data-layer="${l}"]`).setAttribute('aria-pressed', on);
  try { localStorage.setItem('layer-' + l, on ? '1' : '0'); } catch (e) {} };
for (const b of document.querySelectorAll('.lay')) {
  const l = b.dataset.layer;
  b.onclick = () => setLayer(l, document.body.classList.contains('no-' + l));
  try { setLayer(l, localStorage.getItem('layer-' + l) !== '0'); } catch (e) { setLayer(l, true); }
}
window.addEventListener('hashchange', () => show(location.hash));

for (const ts of data.tilesets) {
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
show(location.hash);
</script>
'''

if __name__ == '__main__':
    main()
