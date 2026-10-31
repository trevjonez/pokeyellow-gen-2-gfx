"""Map-load regression check: record warps on one ROM, compare against another.

  python3 tools/maploadtest.py record OUTDIR [ROM]   # ROM defaults to pokeyellow.gbc
  python3 tools/maploadtest.py compare OLDDIR NEWDIR

Each scenario captures every frame of the transition (count of all-white frames:
the LCD being off shows white on the GBC) and, once settled, the tiles, both BG
maps with their attributes, and the BG/OBJ palettes. compare reports white frames per scenario and any
difference in the settled VRAM or palettes. NPCs wander, so screenshots are
written for eyeballing but not compared.
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import battlepreview as bp
from PIL import Image

A, B, START, RIGHT, LEFT, UP, DOWN = 1, 2, 8, 16, 32, 64, 128
VERMILION, VERMILION_POKECENTER, REDS_HOUSE_1F = 0x05, 0x59, 0x25


def white_fraction(im):
    px = im.tobytes()
    return sum(1 for i in range(0, len(px), 3) if min(px[i:i + 3]) > 235) / (len(px) // 3)


class Recorder:
    def __init__(self, outdir, rom):
        self.out = os.path.abspath(outdir)
        os.makedirs(self.out, exist_ok=True)
        bp.ROM_PATH = os.path.abspath(rom)
        self.g = bp.Game()
        self.h = bp.Harness()
        names = ('wCurMap', 'wWarpEntries', 'wEventFlags', 'wPlayerID', 'wPlayerName', 'wPartyMon1OTID',
                 'wPartyMonOT', 'wLastMap', 'wIsInBattle', 'wCurOpponent', 'wCurEnemyLevel',
                 'wYCoord', 'wXCoord', 'wJoyIgnore')
        self.s = {n: bp.sym(n) for n in names}
        self.results = {}

    def walk_to(self, y, x, yfirst=False, settle=12):
        """Step toward (y, x), holding each direction until the step lands."""
        h = self.h
        for _ in range(40):
            cy, cx = self.peek('wYCoord'), self.peek('wXCoord')
            if (cy, cx) == (y, x):
                h.send(f'frames {settle}')
                return True
            if yfirst and cy != y or cx == x:
                btn = DOWN if cy < y else UP
            else:
                btn = RIGHT if cx < x else LEFT
            h.send(f'buttons {btn}')
            for _ in range(60):
                h.send('frames 1')
                if (self.peek('wYCoord'), self.peek('wXCoord')) != (cy, cx):
                    break
            h.send('buttons 0', 'frames 12')
        return False

    def peek(self, name):
        return self.h.peek(self.s[name])

    def shot(self, path):
        self.h.send(f'shot {path}.ppm')
        self.h.peek(0)
        im = Image.open(path + '.ppm').convert('RGB')
        os.remove(path + '.ppm')
        return im

    def frames(self, name, n, until):
        """Run frames until `until()`, then n more, saving each; returns per frame
        (fraction of white pixels, whether the screen is one flat color).
        The held button is let go as soon as `until()` holds, so load timing can't
        change where the player ends up."""
        d = os.path.join(self.out, name)
        os.makedirs(d, exist_ok=True)
        white, f, extra = [], 0, None
        while True:
            self.h.send('frames 1')
            im = self.shot(os.path.join(d, f'{f:03d}'))
            im.save(os.path.join(d, f'{f:03d}.png'))
            white.append((round(white_fraction(im), 3), im.getcolors(1) is not None))
            f += 1
            if extra is None and until():
                self.h.send('buttons 0')
                extra = f + n
            assert extra is not None or f < 600, f'{name}: never got there'
            if extra is not None and f >= extra:
                return white

    def settle(self, name, white):
        h = self.h
        h.send('frames 90')
        self.shot(os.path.join(self.out, name)).save(os.path.join(self.out, name + '.png'))
        # Read through the emulator, not the bus: the PPU locks VRAM and palette
        # RAM in mode 3, wherever the frame happens to stop.
        tiles = h.reply('tiles', 'tiles')[1]
        bgmaps = [h.reply(f'bgmap {m}', 'bgmap')[2:] for m in (0, 1)]
        pals = h.reply('cgbpal', 'cgbpal')[1]
        blank = sum(flat for _, flat in white)   # frames of a blank (one-color) screen
        self.results[name] = {'map': self.peek('wCurMap'), 'white_frames': sum(w > 0.97 for w, _ in white),
                              'blank_frames': blank,
                              'white': white, 'tiles': tiles,
                              'map9800': bgmaps[0][0], 'attr9800': bgmaps[0][1],
                              'map9c00': bgmaps[1][0], 'attr9c00': bgmaps[1][1],
                              'bgpal': pals[:256], 'objpal': pals[256:],
                              'scroll': [h.peek(0xff42), h.peek(0xff43)], 'wy': h.peek(0xff4a),
                              'pos': [self.peek('wYCoord'), self.peek('wXCoord')]}
        print(f"{name}: map={self.results[name]['map']:02x} white_frames={self.results[name]['white_frames']} "
              f"blank_frames={blank}")
        with open(os.path.join(self.out, 'results.json'), 'w') as f:
            json.dump(self.results, f)

    def run(self):
        g, h = self.g, self.h
        g.boot(h)
        h.send('frames 30')
        self.settle('boot', [])
        h.send('save')

        # Red's room stairs down to the first floor: indoor to indoor.
        for (y, x), yfirst in [((6, 5), False), ((1, 5), True), ((1, 6), False)]:
            assert self.walk_to(y, x, yfirst), (y, x)
        h.send(f'buttons {RIGHT}')
        white = self.frames('stairs', 150, lambda: self.peek('wCurMap') == REDS_HOUSE_1F)
        self.settle('stairs', white)

        # The stairs sent to the Vermilion Pokemon Center instead, with a starter
        # Pikachu (follows, knows Thunderbolt) and all badges.
        h.send('load')
        g.set_party(h, g.mons.index('PIKACHU'), g.moves.index('THUNDERBOLT'))
        for i in range(2):
            h.send(f"poke {self.s['wPartyMon1OTID'] + i} {h.peek(self.s['wPlayerID'] + i)}")
        for i in range(11):
            h.send(f"poke {self.s['wPartyMonOT'] + i} {h.peek(self.s['wPlayerName'] + i)}")
        h.send(f"poke {self.s['wEventFlags']} {self.peek('wEventFlags') | 1}")
        h.send(f"poke {self.s['wWarpEntries'] + 2} 0", f"poke {self.s['wWarpEntries'] + 3} {VERMILION_POKECENTER}")
        for (y, x), yfirst in [((6, 5), False), ((1, 5), True), ((1, 6), False)]:
            assert self.walk_to(y, x, yfirst), (y, x)
        h.send(f'buttons {RIGHT}')
        white = self.frames('to_pokecenter', 150, lambda: self.peek('wCurMap') == VERMILION_POKECENTER)
        h.send('buttons 0')
        h.send(f"poke {self.s['wLastMap']} {VERMILION}")
        self.settle('to_pokecenter', white)

        # Out the door: indoor to outdoor.
        # Up and around, so the follower Pikachu ends up behind, not on the door mat.
        for (y, x), yfirst in [((5, 3), True), ((5, 4), False), ((6, 4), True)]:
            assert self.walk_to(y, x, yfirst), (y, x)
        h.send('frames 30', f'buttons {DOWN}')
        white = self.frames('pokecenter_exit', 150, lambda: self.peek('wCurMap') == VERMILION)
        self.settle('pokecenter_exit', white)

        # Back in: outdoor to indoor.
        h.send(f'buttons {UP}')
        white = self.frames('pokecenter_enter', 150, lambda: self.peek('wCurMap') == VERMILION_POKECENTER)
        self.settle('pokecenter_enter', white)

        # A wild battle, won in one hit, then back to the map.
        h.send(f"poke {self.s['wCurEnemyLevel']} 2", f"poke {self.s['wCurOpponent']} {g.mons.index('RATTATA')}")
        h.reply(f"wait {self.s['wIsInBattle']} 1 600", 'wait')
        for _ in range(120):
            h.tap(A, 6)
            if self.peek('wIsInBattle') == 0:
                break
        assert self.peek('wIsInBattle') == 0, 'battle did not end'
        white = self.frames('battle_return', 200, lambda: True)
        self.settle('battle_return', white)

        # The start menu right after a map load: the window shows vBGMap1, which a
        # map load with the LCD on leaves holding stale rows.
        h.send(f'buttons {START}', 'frames 4', 'buttons 0', 'frames 40')
        self.settle('start_menu', [])
        h.close()

        self.run_cable_club()

    def run_cable_club(self):
        """Two linked games trade, then both cancel: ReturnToCableClubRoom reloads the room."""
        g = self.g
        self.h = h = bp.Harness()
        g.boot(h)
        cable = bp.LinkCable(g, h, os.path.join(self.out, 'link'), 'x')
        os.makedirs(cable.outdir, exist_ok=True)
        # LinkCable.to_receptionist, but Red's room is walked waiting on the coordinates:
        # its fixed-length presses can take two steps there, onto the stairs too soon.
        # The rest stays as LinkCable times it, which the link steps after depend on.
        h.send(f"poke {cable.a['wEventFlags'] + 4} {h.peek(cable.a['wEventFlags'] + 4) | 0x20}")
        h.send(f"poke {cable.a['wWarpEntries'] + 2} 0", f"poke {cable.a['wWarpEntries'] + 3} {0x29}")
        for (y, x), yfirst in [((6, 5), False), ((1, 5), True), ((1, 6), False)]:
            assert self.walk_to(y, x, yfirst), (y, x)
        h.send(f'buttons {RIGHT}', 'frames 16', 'buttons 0', 'frames 120')
        assert self.peek('wCurMap') == 0x29, 'did not reach the Pokemon Center'
        for y, x in ((6, 3), (5, 3), (5, 11), (4, 11)):
            assert cable.walk_to(y, x), (y, x)
        h.send(f'buttons {UP}', 'frames 4', 'buttons 0', 'frames 10')
        cable.connect(('PIKACHU', 'CHARMANDER'))
        cable.enter_club(0)
        h.send('use 0')
        self.settle('cable_club_room', [])
        # LinkCable.trade after enter_club: a trade, and back to the party lists.
        cable.press(A, wait=60)
        cable.press(A, wait=300)
        cable.press(A, wait=60)
        cable.press(RIGHT, hold=6, wait=30)
        for _ in range(8):
            cable.press(A, wait=40)
        cable.wait_still(6000)
        for _ in range(2):   # down past the one Pokemon to CANCEL, on both sides
            cable.press(DOWN, hold=8, wait=20)
        h.peek(0)   # the shots LinkCable took are written; drop them
        for p in (pp for pair in cable.frames for pp in pair):
            os.remove(p)
        presses = iter(range(10 ** 6))

        def cancelled():
            # A on both sides every 20 frames until they agree: GBPalWhiteOut starts the return.
            if next(presses) % 20 == 0:
                h.send('use 1', f'buttons {A}', 'frames 4', 'buttons 0', 'use 0', f'buttons {A}')
            return h.peek(0xff47) == 0
        h.send('use 0')
        try:
            white = self.frames('cable_club_return', 200, cancelled)
        except AssertionError:
            # The link steps are timed by frame counts and don't always line up.
            print('cable_club_return: skipped, the trade lists never came up')
        else:
            self.settle('cable_club_return', white)
        h.close()

def diff_ranges(a, b, base):
    a, b = bytes.fromhex(a), bytes.fromhex(b)
    out, start = [], None
    for i in range(len(a) + 1):
        d = i < len(a) and a[i] != b[i]
        if d and start is None:
            start = i
        elif not d and start is not None:
            out.append(f'${base + start:04x}-${base + i - 1:04x}')
            start = None
    return out


def diff_tiles(a, b):
    """Differing tiles as VRAM addresses (bank:addr); the texture is 32 tiles wide."""
    tiles = sorted({(i // 256 // 8) * 32 + (i % 256) // 8 for i in range(len(a)) if a[i] != b[i]})
    return [f'{t // 384}:${0x8000 + t % 384 * 16:04x}' for t in tiles]


def visible(hexmap, scroll):
    """The cells of a 32x32 BG map that show at this scroll (SCY, SCX), as hex."""
    m = bytes.fromhex(hexmap)
    top, left = scroll[0] // 8, scroll[1] // 8
    rows, cols = 18 + (scroll[0] % 8 > 0), 20 + (scroll[1] % 8 > 0)
    return bytes(m[(top + r) % 32 * 32 + (left + c) % 32] for r in range(rows) for c in range(cols)).hex()


# Water and flower tiles animate; their phase depends on how long the load took.
ANIMATED_TILES = {'0:$9140', '0:$9030'}


def compare(old, new):
    """Fail on anything that differs on screen once settled. The window map and
    animated tiles are reported but allowed to differ."""
    o = json.load(open(os.path.join(old, 'results.json')))
    n = json.load(open(os.path.join(new, 'results.json')))
    ok = True
    for d, r in ((old, o), (new, n)):
        # The room after ReturnToCableClubRoom should look as it did on the way in.
        if 'cable_club_return' in r:
            # (Sprite tiles nothing shows can differ: the trade screens loaded others.)
            before, after = r['cable_club_room'], r['cable_club_return']
            shots = [Image.open(os.path.join(d, f'{k}.png')).tobytes() for k in ('cable_club_room', 'cable_club_return')]
            same = shots[0] == shots[1] and all(before[k] == after[k] for k in ('bgpal', 'objpal', 'scroll')) and all(
                visible(before[k], before['scroll']) == visible(after[k], before['scroll']) for k in ('map9800', 'attr9800'))
            ok &= same
            print(f"{os.path.basename(d)}: cable club room after the return {'matches the way in' if same else 'FAILS: differs from the way in'}")
    for name in o:
        if name not in n:
            print(f'{name}: missing in new'); ok = False; continue
        if name == 'cable_club_return':
            continue   # whether the link run reached it depends on timing; checked above
        a, b = o[name], n[name]
        bad, info = [], []
        if a['map'] != b['map']:
            bad.append(f"map {a['map']:02x} -> {b['map']:02x}")
        moved = a['pos'] != b['pos']
        if moved:   # input timing; the camera follows the player, so the map can't be compared
            info.append(f"player at {a['pos']} -> {b['pos']}, map not compared")
        elif a['scroll'] != b['scroll']:
            bad.append(f"scroll {a['scroll']} -> {b['scroll']}")
        tiles = diff_tiles(a['tiles'], b['tiles'])
        (bad if set(tiles) - ANIMATED_TILES else info).extend(f'tile {t}' for t in tiles)
        for key in ('map9800', 'attr9800'):
            if not moved and visible(a[key], a['scroll']) != visible(b[key], a['scroll']):
                bad.append(f'{key} differs on screen')
        if a['wy'] != b['wy']:
            bad.append(f"window y {a['wy']} -> {b['wy']}")
        for key in ('map9c00', 'attr9c00'):
            if a['wy'] < 144 and visible(a[key], [0, 0]) != visible(b[key], [0, 0]):
                bad.append(f'{key} (window, showing) differs')
            elif a[key] != b[key]:
                info.append(f'{key} (window, hidden) differs')
        for key in ('bgpal', 'objpal'):
            if a[key] != b[key]:
                bad.append(f'{key} differs')
        ok &= not bad
        print(f"{name}: white frames {a['white_frames']} -> {b['white_frames']}; "
              f"blank screen {a['blank_frames']} -> {b['blank_frames']} frames; "
              f"{'FAIL ' + '; '.join(bad) if bad else 'same on screen'}"
              f"{' (also: ' + '; '.join(info) + ')' if info else ''}")
    return ok


if __name__ == '__main__':
    if sys.argv[1] == 'record':
        Recorder(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else os.path.join(bp.ROOT, 'pokeyellow.gbc')).run()
    else:
        sys.exit(0 if compare(sys.argv[2], sys.argv[3]) else 1)
