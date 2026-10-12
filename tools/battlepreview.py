#!/usr/bin/env python3
"""Capture battle scenes from the built ROM: every Pokemon's sprites and every move's animation.

Usage: tools/battlepreview.py [OUTDIR] [--moves [NAME,...]] [--mons [NAME,...]] [--trainers [NAME,...]]
                             [--link [TRADE,BATTLE]] [--jobs N] [--rom ROM]
       (run `make` first; OUTDIR defaults to battlepreview/; no kind given = all kinds,
       a kind with no list = all of that kind)

Writes:
  OUTDIR/mons/NAME.png     the battle screen with NAME as both the enemy and your Pokemon
  OUTDIR/moves/NAME.png    contact sheet of the move's animation, every 2nd frame
  OUTDIR/moves/NAME.gif    the animation at full speed
  OUTDIR/trainers/NAME.png the trainer battle intro, every 2nd frame, and .gif at full speed
  OUTDIR/link/TRADE.gif    two linked Game Boys side by side: Cable Club, Trade Center, a full trade
  OUTDIR/link/BATTLE.gif   the same into the Colosseum and a link battle; .png sheets sample them
  OUTDIR/index.html        a page to browse them

How: tools/gbharness.c (a scripted headless runner on binjgb) is built on first use into
tools/.cache/. It boots the ROM, presses A through a New Game until the player stands in
Red's room, and snapshots the machine there. Each capture restores that snapshot, pokes a
party Pokemon and wCurOpponent into WRAM (the overworld loop starts a battle when
wCurOpponent is set), taps A through the intro, picks the first move and records frames
while wAnimationID is set. Moves that need a setup turn or fail on the first turn
(Dream Eater, Mirror Move, Counter, ...) may show only the first part or nothing.

Link captures patch binjgb with a link cable (tools/binjgb-link.patch). From the snapshot the
player warps to the Viridian Pokemon Center and walks to the Cable Club receptionist, then the
harness copies the machine into a second one on the other end of the cable. Both talk to the
receptionist and go through the menus with fixed button timings, so a build that changes how
long those screens take may need the waits adjusted.
"""

import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, 'tools', '.cache')
BINJGB_URL = 'https://github.com/binji/binjgb.git'
BINJGB_COMMIT = '1662111'
HARNESS = os.path.join(CACHE, 'gbharness')
ROM_PATH = os.path.join(ROOT, 'pokeyellow.gbc')   # --rom picks another build (same WRAM layout)

A, RIGHT, LEFT, UP, DOWN = 1, 16, 32, 64, 128
SEND_OUT_ANIM = 0xc3   # wAnimationID while your Pokemon comes out of its ball
OPP_ID_OFFSET = 200    # wCurOpponent >= this starts a battle against trainer class (id - 200)


def sym(name):
    for line in open(os.path.join(ROOT, 'pokeyellow.sym')):
        parts = line.split()
        if len(parts) == 2 and parts[1] == name:
            return int(parts[0].split(':')[1], 16)
    raise KeyError(name)


def consts(path):
    names = []
    for line in open(os.path.join(ROOT, path)):
        code = line.split(';')[0]
        m = re.match(r'\s*(?:trainer_)?const\s+(\w+)', code)
        skip = re.match(r'\s*const_skip\s*(\d*)', code)
        if m:
            names.append(m.group(1))
        elif skip:
            names += [None] * int(skip.group(1) or 1)
        elif re.match(r'\s*const_def', code) and names:
            break
    return names


def build_harness():
    src = os.path.join(ROOT, 'tools', 'gbharness.c')
    patch = os.path.join(ROOT, 'tools', 'binjgb-link.patch')   # adds a link cable
    if os.path.exists(HARNESS) and os.path.getmtime(HARNESS) > max(map(os.path.getmtime, (src, patch))):
        return
    repo = os.path.join(CACHE, 'binjgb')
    if not os.path.exists(repo):
        os.makedirs(CACHE, exist_ok=True)
        subprocess.run(['git', 'clone', '-q', BINJGB_URL, repo], check=True)
    subprocess.run(['git', '-C', repo, 'checkout', '-q', '-f', BINJGB_COMMIT], check=True)
    subprocess.run(['git', '-C', repo, 'apply', patch], check=True)
    subprocess.run(['gcc', '-O2', '-std=gnu11', '-w', '-I', os.path.join(repo, 'src'), '-o', HARNESS, src,
                    *(os.path.join(repo, 'src', f) for f in ('memory.c', 'common.c', 'emulator-debug.c')),
                    '-lm'], check=True)


class Harness:
    def __init__(self):
        self.p = subprocess.Popen([HARNESS, ROM_PATH, '-'], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  text=True, bufsize=1)

    def send(self, *lines):
        self.p.stdin.write(''.join(line + '\n' for line in lines))
        self.p.stdin.flush()

    def reply(self, line, prefix):
        self.send(line)
        while True:
            out = self.p.stdout.readline()
            if not out:
                raise RuntimeError('harness exited')
            if out.startswith(prefix):
                return out.split()

    def peek(self, addr):
        return int(self.reply(f'peek {addr}', 'peek')[2], 16)

    def peekn(self, addr, n):
        return self.reply(f'peekn {addr} {n}', 'peekn')[2]

    def tap(self, buttons, frames=5):
        self.send(f'buttons {buttons}', f'frames {frames}', 'buttons 0', f'frames {frames}')

    def close(self):
        self.p.stdin.close()
        self.p.wait()


class Game:
    def __init__(self):
        self.mons = consts('constants/pokemon_constants.asm')     # index = species id
        self.moves = consts('constants/move_constants.asm')       # index = move id
        self.moves = self.moves[:self.moves.index('STRUGGLE') + 1]   # the rest are animation-only ids
        self.trainers = consts('constants/trainer_constants.asm')   # index = trainer class
        self.dex = [n for n in consts('constants/pokedex_constants.asm') if n.startswith('DEX_')]
        self.text_box = sym('wTileMap') + 12 * 20   # rows 12-17: the battle text box
        self.addr = {n: sym(n) for n in (
            'wCurMap', 'wJoyIgnore', 'hWY', 'wOptions', 'wPartyCount', 'wPartySpecies', 'wPartyMon1Species',
            'wPartyMon1HP', 'wPartyMon1BoxLevel', 'wPartyMon1Status', 'wPartyMon1Type1', 'wPartyMon1Moves',
            'wPartyMon1PP', 'wPartyMon1Level', 'wPartyMon1MaxHP', 'wCurOpponent', 'wCurEnemyLevel',
            'wAnimationID', 'wIsInBattle', 'wTrainerNo', 'wPartyMonNicks', 'wPartyMonOT', 'wObtainedBadges', 'wEnemyMonStatus', 'wRivalName')}

    def boot(self, h):
        """New Game, press A until the player is free in Red's room, then snapshot."""
        a = self.addr
        for _ in range(2000):
            h.tap(A)
            if (h.peek(a['wCurMap']) == 0x26 and h.peek(a['wJoyIgnore']) == 0
                    and h.peek(a['hWY']) == 0x90):
                break
        else:
            raise RuntimeError('New Game did not reach the overworld')
        h.send('frames 30')
        # Battle animations on, fast text.
        h.send(f"poke {a['wOptions']} 1")
        h.send('save')

    def set_party(self, h, player, move, speed=3):
        """One level 50 Pokemon named A (OT A) knowing only `move`, and all badges."""
        a = self.addr
        pokes = {a['wPartyCount']: 1, a['wPartySpecies']: player, a['wPartySpecies'] + 1: 0xff,
                 a['wPartyMon1Species']: player, a['wPartyMon1HP']: 0, a['wPartyMon1HP'] + 1: 200,
                 a['wPartyMon1BoxLevel']: 50, a['wPartyMon1Status']: 0,
                 a['wPartyMon1Type1']: 0, a['wPartyMon1Type1'] + 1: 0,
                 a['wPartyMon1Level']: 50, a['wPartyMon1MaxHP']: 0, a['wPartyMon1MaxHP'] + 1: 200,
                 a['wCurEnemyLevel']: 50}
        for i in range(4):
            pokes[a['wPartyMon1Moves'] + i] = move if i == 0 else 0
            pokes[a['wPartyMon1PP'] + i] = 30 if i == 0 else 0
        for i in range(1, 9):   # Attack, Defense, Speed, Special: 100 each
            pokes[a['wPartyMon1MaxHP'] + 1 + i] = 100 if i % 2 == 0 else 0
        pokes[a['wPartyMon1MaxHP'] + 6] = speed   # Speed hi byte: 3 = always move first, 0 = last
        # All badges, so a level 50 Pokemon with someone else's OT still obeys.
        pokes[a['wObtainedBadges']] = 0xff
        name = [0x80, 0x50]     # "A"
        for i, v in enumerate([0x81, 0x8b, 0x94, 0x84, 0x50]):   # "BLUE"
            pokes[a['wRivalName'] + i] = v
        for i, v in enumerate(name):
            pokes[a['wPartyMonNicks'] + i] = v
            pokes[a['wPartyMonOT'] + i] = v
        for addr, v in pokes.items():
            h.send(f'poke {addr} {v}')

    def start_battle(self, h, player, enemy, move, speed=3, delay=0, trainer_no=1):
        a = self.addr
        h.send('load', f'frames {delay}')
        h.send(f"poke {a['wTrainerNo']} {trainer_no}")   # which party, when enemy is a trainer class
        self.set_party(h, player, move, speed)
        h.send(f"poke {a['wCurOpponent']} {enemy}")
        h.reply(f"wait {a['wIsInBattle']} {2 if enemy >= OPP_ID_OFFSET else 1} 600", 'wait')
        if enemy == self.mons.index('MAROWAK'):
            # A wild Marowak is always the Pokemon Tower ghost (wCurOpponent == RESTLESS_SOUL).
            # The species is already copied to wEnemyMonSpecies2; change the id before the check.
            h.send(f"poke {a['wCurOpponent']} {self.mons.index('CUBONE')}")

    def mon_shot(self, h, species, path):
        self.start_battle(h, species, species, self.moves.index('TACKLE'))
        for _ in range(200):     # transition, "Wild X appeared!", then "Go! X!" sends ours out
            h.tap(A, 4)
            if h.peek(self.addr['wAnimationID']) == SEND_OUT_ANIM:
                break
        h.send('frames 90')
        h.send(f'shot {path}')

    # Trainer intros: label -> (class, party number). Every class with a party, plus
    # Jessie & James, who are Rocket parties $2A+ with their own pic.
    def trainer_jobs(self):
        no_party = {'NOBODY', 'CHIEF', 'UNUSED_JUGGLER'}
        jobs = {n: (i, 1) for i, n in enumerate(self.trainers) if n and n not in no_party}
        jobs['JESSIE_JAMES'] = (self.trainers.index('ROCKET'), 0x2a)
        return jobs

    def trainer_frames(self, h, cls, no, outdir, name):
        """Record the battle start until the screen holds still on "X wants to fight!".
        Only the part above the text box counts, since its ▼ prompt blinks."""
        self.start_battle(h, self.mons.index('PIKACHU'), OPP_ID_OFFSET + cls, self.moves.index('TACKLE'),
                          trainer_no=no)
        frames, still = [], 0
        for i in range(600):
            path = os.path.join(outdir, f'{name}.{i:03d}.ppm')
            h.send(f'shot {path}')
            h.peek(0)   # sync: shot written
            frames.append(path)
            if i and still_part(path) == still_part(frames[-2]):
                still += 1
                if still == 30:   # fast text is done and waits for A
                    break
            else:
                still = 0
            h.send('frames 2')
        for p in frames[len(frames) - still:-1]:
            os.remove(p)
        return frames[:len(frames) - still] + frames[-1:]   # last one shows the finished text

    # Moves that need a particular setup to animate at all.
    SPECIAL = {
        'LICK': dict(enemy='VAPOREON'),            # Ghost has no effect on a Normal target
        'DREAM_EATER': dict(asleep=True),          # only works on a sleeping target
        'BIDE': dict(taps=600),                    # unleashes after two or three turns
        'RAZOR_WIND': dict(taps=600),              # charges first, can miss
    }

    # Gen 1 plays the copied move's animation instead; there is nothing of its own to show.
    NO_ANIMATION = {'MIRROR_MOVE': 'plays the copied move instead'}

    def move_frames(self, h, move, outdir, name):
        for attempt in range(4):   # moves can miss; a later start rolls different random numbers
            frames = self._move_frames(h, move, outdir, name, delay=attempt * 7,
                                       **self.SPECIAL.get(name, {}))
            if frames:
                return frames
        return []

    def _move_frames(self, h, move, outdir, name, delay=0, enemy='SNORLAX', asleep=False, speed=3, taps=200):
        """Tap A until the move's animation starts, then grab every 2nd frame until the
        text box changes (the next message), which is when the animation is over."""
        a = self.addr
        self.start_battle(h, self.mons.index('PIKACHU'), self.mons.index(enemy), move, speed, delay)
        for _ in range(taps):
            if asleep:
                h.send(f"poke {a['wEnemyMonStatus']} 7")
            h.tap(A, 4)
            if h.peek(a['wAnimationID']) == move:
                break
        else:
            return []
        text = h.peekn(self.text_box, 6 * 20)
        frames = []
        for i in range(400):
            path = os.path.join(outdir, f'{name}.{i:03d}.ppm')
            h.send(f'shot {path}')
            frames.append(path)
            h.send('frames 2')
            if h.peek(a['wAnimationID']) != move or h.peekn(self.text_box, 6 * 20) != text:
                break
        return frames


class LinkCable:
    """Two copies of the game on either end of a link cable, recorded side by side."""
    STEP = 4   # frames between recorded frames

    def __init__(self, game, h, outdir, name):
        self.game, self.h, self.outdir, self.name = game, h, outdir, name
        self.frames = []   # [(machine 0 ppm, machine 1 ppm)]
        self.a = {n: sym(n) for n in ('wCurMap', 'wYCoord', 'wXCoord', 'wWarpEntries', 'wEventFlags',
                                       'wPlayerName', 'wCurrentMenuItem')}

    def walk_to(self, y, x, yfirst=False):
        """Step toward (y, x), one tile per press; True once there."""
        h, a = self.h, self.a
        for _ in range(80):
            cy, cx = h.peek(a['wYCoord']), h.peek(a['wXCoord'])
            if (cy, cx) == (y, x):
                return True
            if yfirst and cy != y or cx == x:
                btn = DOWN if cy < y else UP
            else:
                btn = RIGHT if cx < x else LEFT
            h.send(f'buttons {btn}', 'frames 8', 'buttons 0', 'frames 10')
        return False

    def to_receptionist(self):
        """From the snapshot in Red's room to facing the Viridian Pokemon Center's Cable Club desk."""
        h, a = self.h, self.a
        h.send('load')
        # EVENT_GOT_POKEDEX (bit 37) opens the Cable Club.
        h.send(f"poke {a['wEventFlags'] + 4} {h.peek(a['wEventFlags'] + 4) | 0x20}")
        # Send the stairs (warp 0) to VIRIDIAN_POKECENTER's door instead of downstairs.
        h.send(f"poke {a['wWarpEntries'] + 2} 0", f"poke {a['wWarpEntries'] + 3} {0x29}")
        route = [((6, 5), False), ((1, 5), True), ((1, 6), False)]   # around the plant to the stairs
        for (y, x), yfirst in route:
            assert self.walk_to(y, x, yfirst), (y, x)
        h.send(f'buttons {RIGHT}', 'frames 16', 'buttons 0', 'frames 120')
        assert h.peek(a['wCurMap']) == 0x29, 'did not reach the Pokemon Center'
        for y, x in ((6, 3), (5, 3), (5, 11), (4, 11)):   # below the plants, to the desk
            assert self.walk_to(y, x), (y, x)
        h.send(f'buttons {UP}', 'frames 4', 'buttons 0', 'frames 10')

    def connect(self, parties, names=('RED', 'BLUE')):
        """Copy the machine to the other end of the cable and give each side a party and name."""
        h, g = self.h, self.game
        h.send('link')
        for m, (species, name) in enumerate(zip(parties, names)):
            h.send(f'use {m}')
            g.set_party(h, g.mons.index(species), g.moves.index('TACKLE'))
            for i, c in enumerate(name.encode() + b'\x50'):   # A-Z are $80-$99, "@" ends it
                h.send(f"poke {self.a['wPlayerName'] + i} {c + 0x3f if c != 0x50 else c}")

    def press(self, button, hold=4, wait=0):
        for m in (0, 1):
            self.h.send(f'use {m}', f'buttons {button}', f'frames {hold}', 'buttons 0')
        self.wait(wait)

    def wait(self, n):
        for _ in range(0, n, self.STEP):
            self.h.send(f'frames {self.STEP}')
            pair = tuple(os.path.join(self.outdir, f'{self.name}.{len(self.frames):04d}.{m}.ppm') for m in (0, 1))
            for m, p in enumerate(pair):
                self.h.send(f'use {m}', f'shot {p}')
            self.frames.append(pair)

    def wait_still(self, limit, still=300, keep=60):
        """Record until neither screen has changed for `still` frames, then drop all but
        `keep` frames of that idle tail. The trade pauses for up to ~150 frames midway."""
        same = 0
        for _ in range(0, limit, self.STEP):
            self.wait(self.STEP)
            self.h.peek(0)   # sync: shots written
            if len(self.frames) > 1 and all(open(a, 'rb').read() == open(b, 'rb').read()
                                            for a, b in zip(self.frames[-1], self.frames[-2])):
                same += self.STEP
                if same >= still:
                    break
            else:
                same = 0
        for pair in self.frames[len(self.frames) - (same - keep) // self.STEP:]:
            for p in pair:
                os.remove(p)
        del self.frames[len(self.frames) - (same - keep) // self.STEP:]

    def enter_club(self, menu_downs):
        """Talk to the receptionist on both sides, save, and pick a room from the menu."""
        h = self.h
        # The second player talks a few frames later; with both on the same frame, both
        # would keep trying to drive the clock and never connect.
        h.send('use 0', f'buttons {A}', 'frames 3', 'buttons 0', 'use 1', 'frames 5',
               f'buttons {A}', 'frames 3', 'buttons 0')
        self.wait(240)
        for _ in range(4):   # "Please apply here", save the game? yes, saving, the room menu
            self.press(A, wait=52)
        self.wait(60)
        for _ in range(menu_downs):   # the link menu polls slowly: hold for it to see the press
            self.press(DOWN, hold=8, wait=20)
        for _ in range(3):
            self.press(A, wait=52)
        self.wait(120)
        assert all((h.send(f'use {m}'), h.peek(self.a['wCurMap']))[1] == 0xef + menu_downs for m in (0, 1)), \
            'did not enter the link room'
        # Sit facing the table: player 0 on the left, player 1 on the right.
        h.send('use 0', f'buttons {RIGHT}', 'frames 3', 'buttons 0',
               'use 1', f'buttons {LEFT}', 'frames 3', 'buttons 0')
        self.wait(20)

    def trade(self):
        self.enter_club(0)
        self.press(A, wait=60)
        self.press(A, wait=300)        # the party lists
        self.press(A, wait=60)         # first Pokemon: STATS / TRADE
        self.press(RIGHT, hold=6, wait=30)
        for _ in range(8):             # TRADE, confirm, and through the prompts on both sides
            self.press(A, wait=40)
        self.wait_still(6000)          # both ways, "Trade completed!", back to the lists

    def battle(self):
        self.enter_club(1)
        for _ in range(30):            # into the battle, FIGHT, TACKLE, one turn each
            self.press(A, wait=50)

    def finish(self):
        """Join each pair of frames side by side; returns the joined PNG paths."""
        self.h.peek(0)
        paths = []
        for pair in self.frames:
            im = Image.new('RGB', (330, 144), (30, 30, 30))
            for m, p in enumerate(pair):
                im.paste(Image.open(p), (m * 170, 0))
                os.remove(p)
            paths.append(pair[0][:-6] + '.png')
            im.save(paths[-1])
        return paths


def still_part(ppm):
    """The rows of a 160x144 PPM above the battle text box."""
    data = open(ppm, 'rb').read()
    return data[-160 * 144 * 3:][:160 * 96 * 3]


def contact_sheet(paths, out_png, out_gif, cols=8, every=1, duration=33):
    """Sheet of the distinct frames (every `every`th of them) and a GIF of all of them."""
    imgs = [Image.open(p).convert('RGB') for p in paths]
    uniq = [im for i, im in enumerate(imgs) if i == 0 or im.tobytes() != imgs[i - 1].tobytes()][::every]
    w, h = imgs[0].width + 2, imgs[0].height + 2
    rows = (len(uniq) + cols - 1) // cols
    sheet = Image.new('RGB', (cols * w, rows * h), (30, 30, 30))
    for i, im in enumerate(uniq):
        sheet.paste(im, ((i % cols) * w + 1, (i // cols) * h + 1))
    sheet.save(out_png)
    imgs[0].save(out_gif, save_all=True, append_images=imgs[1:], duration=duration, loop=0)
    for p in paths:
        os.remove(p)
    return len(uniq)


def worker(game, jobs, outdir):
    h = Harness()
    game.boot(h)
    done = []
    for kind, ident in jobs:
        if kind == 'mon':
            name = game.mons[ident]
            ppm = os.path.join(outdir, 'mons', name + '.ppm')
            game.mon_shot(h, ident, ppm)
            h.peek(0)   # sync: shot written
            Image.open(ppm).resize((320, 288), Image.NEAREST).save(ppm[:-4] + '.png')
            os.remove(ppm)
            done.append((kind, name, 1))
        elif kind == 'link':
            link_h = Harness()   # two machines from here on, so not the shared one
            game.boot(link_h)
            cable = LinkCable(game, link_h, os.path.join(outdir, 'link'), ident)
            cable.to_receptionist()
            cable.connect(('PIKACHU', 'CHARMANDER'))
            getattr(cable, ident.lower())()
            frames = cable.finish()
            link_h.close()
            n = contact_sheet(frames, os.path.join(outdir, 'link', ident + '.png'),
                              os.path.join(outdir, 'link', ident + '.gif'),
                              cols=4, every=16, duration=cable.STEP * 1000 // 60)
            done.append((kind, ident, n))
        elif kind == 'trainer':
            name, (cls, no) = ident
            frames = game.trainer_frames(h, cls, no, os.path.join(outdir, 'trainers'), name)
            n = contact_sheet(frames, os.path.join(outdir, 'trainers', name + '.png'),
                              os.path.join(outdir, 'trainers', name + '.gif'))
            done.append((kind, name, n))
        else:
            name = game.moves[ident]
            frames = game.move_frames(h, ident, os.path.join(outdir, 'moves'), name)
            h.peek(0)
            n = contact_sheet(frames, os.path.join(outdir, 'moves', name + '.png'),
                              os.path.join(outdir, 'moves', name + '.gif')) if frames else 0
            done.append((kind, name, n))
    h.close()
    return done


def write_index(outdir, counts):
    """Lists everything in OUTDIR, so partial runs add to earlier ones."""
    mons = sorted(f[:-4] for f in os.listdir(os.path.join(outdir, 'mons')) if f.endswith('.png'))
    trainers = sorted(f[:-4] for f in os.listdir(os.path.join(outdir, 'trainers')) if f.endswith('.png'))
    links = sorted(f[:-4] for f in os.listdir(os.path.join(outdir, 'link')) if f.endswith('.png'))
    cable = ''.join(f'<section><h3>{n}</h3><img class="gif" src="link/{n}.gif" alt="{n} over a link cable" '
                    f'loading="lazy" style="width:660px"><img src="link/{n}.png" alt="{n} frames" loading="lazy">'
                    '</section>' for n in links)
    intros = ''.join(f'<section><h3>{n}</h3><img class="gif" src="trainers/{n}.gif" alt="{n} intro" loading="lazy">'
                     f'<img src="trainers/{n}.png" alt="{n} frames" loading="lazy"></section>' for n in trainers)
    names = sorted({f[:-4] for f in os.listdir(os.path.join(outdir, 'moves')) if f.endswith('.png')} | set(counts))
    moves = [(n, counts.get(n, -1)) for n in names] + [(n, 0) for n in sorted(Game.NO_ANIMATION)]
    cards = ''.join(f'<figure><img src="mons/{n}.png" alt="{n}" loading="lazy"><figcaption>{n}</figcaption></figure>'
                    for n in mons)
    rows = ''.join(f'<section><h3>{n} <small>{f"{c} distinct frames" if c > 0 else ""}</small></h3>'
                   + (f'<img class="gif" src="moves/{n}.gif" alt="{n} animation" loading="lazy">'
                      f'<img src="moves/{n}.png" alt="{n} frames" loading="lazy">' if c
                      else f'<p>{Game.NO_ANIMATION.get(n, "No animation captured.").capitalize()}.</p>')
                   + '</section>' for n, c in moves)
    page = f'''<!doctype html><meta charset="utf-8"><title>Battle Preview</title>
<style>
:root{{--bg:#f4f4f2;--fg:#1b1b1f;--mut:#6b6b74;--line:#d6d6d0}}
@media (prefers-color-scheme:dark){{:root{{--bg:#16161a;--fg:#e8e8ea;--mut:#9a9aa4;--line:#2e2e36}}}}
body{{margin:0 auto;max-width:1400px;padding:12px 16px;font:14px system-ui,sans-serif;background:var(--bg);color:var(--fg)}}
nav a{{margin-right:12px;color:inherit}} h2{{border-bottom:1px solid var(--line);padding-bottom:4px}}
.mons{{display:flex;flex-wrap:wrap;gap:10px}} figure{{margin:0}} figcaption{{font:12px ui-monospace,monospace;color:var(--mut)}}
img{{image-rendering:pixelated;max-width:100%}} .gif{{width:320px;margin-right:12px;vertical-align:top}}
section{{margin:0 0 18px}} h3{{margin:0 0 4px;font-size:15px}} small{{color:var(--mut);font-weight:normal}}
</style>
<nav><a href="#moves">Moves ({len(moves)})</a><a href="#mons">Pok&eacute;mon ({len(mons)})</a><a href="#trainers">Trainers ({len(trainers)})</a><a href="#link">Link cable ({len(links)})</a></nav>
<h2 id="moves">Moves</h2>{rows}
<h2 id="mons">Pok&eacute;mon</h2><div class="mons">{cards}</div>
<h2 id="trainers">Trainers</h2>{intros}
<h2 id="link">Link cable</h2><p>Player 1 (left) and player 2 (right), joined by a cable.</p>{cable}'''
    open(os.path.join(outdir, 'index.html'), 'w').write(page)


def main():
    args = sys.argv[1:]
    # A bare --moves/--mons/--trainers (no list) means all of that kind.
    opt = lambda flag: (None if flag not in args else
                        '' if args.index(flag) + 1 == len(args) or args[args.index(flag) + 1].startswith('--')
                        else args[args.index(flag) + 1])
    outdir = next((a for a in args if not a.startswith('--') and a not in
                   (opt('--moves'), opt('--mons'), opt('--trainers'), opt('--link'), opt('--jobs'), opt('--rom'))),
                  os.path.join(ROOT, 'battlepreview'))
    if opt('--rom'):
        global ROM_PATH
        ROM_PATH = os.path.abspath(opt('--rom'))
    for sub in ('mons', 'moves', 'trainers', 'link'):
        os.makedirs(os.path.join(outdir, sub), exist_ok=True)
    build_harness()
    game = Game()
    want_moves = None if opt('--moves') is None else opt('--moves').upper().split(',') if opt('--moves') else []
    want_mons = None if opt('--mons') is None else opt('--mons').upper().split(',') if opt('--mons') else []
    want_trainers = None if opt('--trainers') is None else opt('--trainers').upper().split(',') if opt('--trainers') else []
    want_link = None if opt('--link') is None else opt('--link').upper().split(',') if opt('--link') else []
    everything = want_moves is None and want_mons is None and want_trainers is None and want_link is None
    jobs = []
    if want_link is not None or everything:
        jobs += [('link', n) for n in ('TRADE', 'BATTLE') if not want_link or n in want_link]
    if want_moves is not None or everything:
        jobs += [('move', i) for i, n in enumerate(game.moves)
                 if n and n != 'STRUGGLE' and n not in Game.NO_ANIMATION
                 and (not want_moves or n in want_moves)]
    if want_mons is not None or everything:
        jobs += [('mon', game.mons.index(d[4:])) for d in game.dex
                 if d[4:] in game.mons and (not want_mons or d[4:] in want_mons)]
    if want_trainers is not None or everything:
        jobs += [('trainer', t) for t in game.trainer_jobs().items()
                 if not want_trainers or t[0] in want_trainers]
    n = int(opt('--jobs') or os.cpu_count() or 4)
    chunks = [jobs[i::n] for i in range(n)]
    with ThreadPoolExecutor(n) as pool:
        results = [r for part in pool.map(lambda c: worker(game, c, outdir) if c else [], chunks) for r in part]
    write_index(outdir, {name: c for k, name, c in results if k == 'move'})
    empty = [name for k, name, c in results if k == 'move' and not c]
    count = lambda kind: sum(k == kind for k, _, _ in results)
    print(f'{count("move")} moves, {count("mon")} Pokemon, {count("trainer")} trainers, '
          f'{count("link")} link captures -> {outdir}')
    if empty:
        print('no animation captured:', ' '.join(empty))


if __name__ == '__main__':
    main()
