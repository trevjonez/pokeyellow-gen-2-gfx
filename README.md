# Pokémon Yellow, full Game Boy Color

English Pokémon Yellow with Gen 2 sprites and per-tile Game Boy Color backgrounds. The overworld and interiors are colored tile by tile, the way Gold and Silver are, instead of with Yellow's four whole-screen palettes.

![Pallet Town](screenshots/pallet-town.png)

This is a fork of [dannye/pokeyellow-gen-2-gfx](https://github.com/dannye/pokeyellow-gen-2-gfx). The color engine comes from [dannye/pokered-gbc](https://github.com/dannye/pokered-gbc) (FroggestSpirit, Drenn, and dannye), adapted to Yellow.

## What this fork adds

- Per-tile background color on every map: town roof colors, wood, water, grass, and furniture palettes.
- Colored overworld sprites, including the yellow follower Pikachu.
- Battle transitions, text boxes, menus, the town map and Pikachu's portrait keep their colors.
- Many tiles that read as gray next to colored neighbors are recolored. Examples are flowers, signs, posts, stools, shelves, beds, stairs, cliffs and floors.

It is tested on a ModRetro Chromatic through an EverDrive-GB X7.

## Building

Follow [INSTALL.md](INSTALL.md) to install **rgbds 1.0.1**, then run `make`. The output is `pokeyellow.gbc`. `make compare` does not match the retail ROM in this fork.

## Map viewer

`tools/colormap.py` renders every map in its game colors from the source data. Run `make` first, then:

```
tools/colormap.py
```

Open `colormap/index.html` in a browser. You can:

- Pan and zoom the connected overworld.
- Click a door, ladder or stairs to open the map it leads to.
- Toggle warps, NPCs, items and hidden items.
- Browse every tileset's tiles with their assigned palettes.

The output folder is ignored by git.

![Map viewer](screenshots/colormap-viewer.png)

---

Original README follows...

# pokeyellow-gen-2-gfx

Pokémon Yellow with 2nd Gen. Graphical Enhancements.

**Note:** This repository used to be called **pokeyellow-gen-II**.

Original README follows...

# Pokémon Yellow [![Build Status][ci-badge]][ci]

This is a disassembly of Pokémon Yellow.

It builds the following ROMs:

- Pokemon Yellow (UE) [C][!].gbc  `sha1: cc7d03262ebfaf2f06772c1a480c7d9d5f4a38e1`
- YELLMONS.GB (debug build) `sha1: d44e96eddfbdad633cbe4e6e64915e9e198974b0`
- Dmgapse0.h08.patch `sha1: f3346a5559d52c296b8feab0cdbbfb0e250ac161`

To set up the repository, see [**INSTALL.md**](INSTALL.md).


## See also

- [**Wiki**][wiki] (includes [tutorials][tutorials])
- [**Symbols**][symbols]
- [**Tools**][tools]

You can find us on [Discord (pret, #pokered)](https://discord.gg/d5dubZ3).

For other pret projects, see [pret.github.io](https://pret.github.io/).

[wiki]: https://github.com/pret/pokeyellow/wiki
[tutorials]: https://github.com/pret/pokeyellow/wiki/Tutorials
[symbols]: https://github.com/pret/pokeyellow/tree/symbols
[tools]: https://github.com/pret/gb-asm-tools
[ci]: https://github.com/pret/pokeyellow/actions
[ci-badge]: https://github.com/pret/pokeyellow/actions/workflows/main.yml/badge.svg
