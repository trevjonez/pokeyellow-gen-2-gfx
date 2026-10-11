LoadTilesetHeader:
	call GetPredefRegisters
	push hl
	call ReloadTilesetHeaderFromROM
	pop hl
	ld a, [wCurMapTileset]
	push hl
	push de
	ld hl, DungeonTilesets
	ld de, $1
	call IsInArray
	pop de
	pop hl
	jr c, .dungeon
	ld a, [wCurMapTileset]
	ld b, a
	ldh a, [hPreviousTileset]
	cp b
	jr z, .done
.dungeon
	ld a, [wDestinationWarpID]
	cp $ff
	jr z, .done
	call LoadDestinationWarpPosition
	ld a, [wYCoord]
	and $1
	ld [wYBlockCoord], a
	ld a, [wXCoord]
	and $1
	ld [wXBlockCoord], a
.done
	ret

; Copy this ROM's tileset header over the twelve bytes restored from SRAM.
; Block, graphics, and collision pointers are absolute, so a save written
; by an older layout otherwise keeps the old collision list.
ReloadTilesetHeaderFromROM::
	ld d, 0
	ld a, [wCurMapTileset]
	add a
	add a
	ld e, a
	ld hl, Tilesets
	add hl, de
	add hl, de
	add hl, de
	ld de, wTilesetBank
	ld bc, $b
	call CopyData
	ld a, [hl]
	ldh [hTileAnimations], a
	xor a
	ldh [hMovingBGTilesCounter1], a
	ret

INCLUDE "data/tilesets/dungeon_tilesets.asm"

INCLUDE "data/tilesets/tileset_headers.asm"
