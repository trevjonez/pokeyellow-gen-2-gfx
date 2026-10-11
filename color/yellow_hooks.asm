; Yellow-specific glue for the pokered-gbc per-tile color engine.
; Overworld BG and sprite palettes come from that engine.
; Battles clear the flag so Yellow's own battle palettes run again.

; d = 1 when the overworld currently owns BG palettes. d is preserved by Bankswitch.
; The stack lives in banked WRAM, so the saved bank stays in b across the switch.
PerTileColorOwnsBg::
	ldh a, [rWBK]
	ld b, a
	ld a, 2
	ldh [rWBK], a
	ld a, [W2_UsePerTileColor]
	ld d, a
	ld a, b
	ldh [rWBK], a
	ret

ClearOverworldColor::
	ldh a, [rWBK]
	ld b, a
	ld a, 2
	ldh [rWBK], a
	xor a
	ld [W2_UsePerTileColor], a
	ld a, b
	ldh [rWBK], a
	ret

; LCD is off. Loads the tileset palettes, writes them, and stamps the attribute map.
ApplyOverworldColor::
	ld a, 2
	ldh [rWBK], a
	ld a, 1
	ld [W2_UsePerTileColor], a
	ld [W2_ForceBGPUpdate], a
	xor a
	ldh [rWBK], a
	call LoadTilesetPalette
	call LoadOverworldSpritePalettes
	call GbcPrepareVBlank
	ld a, 1
	call UploadBgPalettes
	ld a, 1
	call UploadObjPalettes
	jp LoadMapVramAndColors

; Called at the start of VBlank, after rWBK has been switched to bank 1.
; Fills the window attribute buffer before AutoBgMapTransfer DMAs it.
; The palette register writes happen later, in YellowColorUpload, so a
; redrawn map row still has vblank time left to land its attributes.
YellowColorVBlank::
	ld a, 2
	ldh [rWBK], a
	ld a, [W2_UsePerTileColor]
	ld b, a
	xor a
	ldh [rWBK], a
	ld a, b
	and a
	ret z
	jp GbcPrepareVBlank

; Called from PrepareOAMData, after the vblank tile copies.
YellowColorUpload::
	ld a, 2
	ldh [rWBK], a
	ld a, [W2_UsePerTileColor]
	ld b, a
	xor a
	ldh [rWBK], a
	ld a, b
	and a
	ret z
	xor a
	call UploadBgPalettes
	xor a
	jp UploadObjPalettes

; a = 0: upload only if there is vblank time left. a = 1: upload even with the LCD off.
UploadBgPalettes::
	ld e, a
	ld a, 2
	ldh [rWBK], a
	ld a, [W2_BgPaletteDataModified]
	and a
	jp z, .done
	ld a, e
	and a
	jr nz, .go
	ldh a, [rLY]
	cp $97
	jp nc, .done
	cp $90
	jp c, .done
.go
	ld a, $80
	ldh [rBGPI], a
	ld c, LOW(rBGPD)
	ld hl, W2_BgPaletteDataBuffer
REPT 64
	ld a, [hli]
	ldh [c], a
ENDR
	xor a
	ld [W2_BgPaletteDataModified], a
.done
	xor a
	ldh [rWBK], a
	ret

; a = 0: upload only if there is vblank time left. a = 1: upload even with the LCD off.
; The town map uses one OBJ palette. The overworld set would tint the whole map.
UploadObjPalettes::
	ld e, a
	ld a, 2
	ldh [rWBK], a
	ld a, [W2_PlainWindowPal]
	and a
	jp nz, .townMap
	ld a, [W2_SprPaletteDataModified]
	and a
	jp z, .done
	ld a, e
	and a
	jr nz, .go
	ldh a, [rLY]
	cp $97
	jp nc, .done
	cp $90
	jp c, .done
.go
	ld a, $80
	ldh [rOBPI], a
	ld c, LOW(rOBPD)
	ld hl, W2_SprPaletteDataBuffer
REPT 64
	ld a, [hli]
	ldh [c], a
ENDR
	xor a
	ld [W2_SprPaletteDataModified], a
	jr .done
.townMap
	ld a, e
	and a
	jr nz, .townGo
	ldh a, [rLY]
	cp $97
	jr nc, .done
	cp $90
	jr c, .done
.townGo
	ld a, $80
	ldh [rOBPI], a
	ld c, LOW(rOBPD)
	ld hl, TownMapOBJPalette
REPT 8
	ld a, [hli]
	ldh [c], a
ENDR
.done
	xor a
	ldh [rWBK], a
	ret

; One BG palette for the whole window, taken from Yellow's CGB town-map colors.
SetPlainWindowPal::
	ldh a, [rWBK]
	ld b, a
	ld a, 2
	ldh [rWBK], a
	ld a, 1
	ld [W2_PlainWindowPal], a
	ld [W2_ForceBGPUpdate], a
	ld hl, TownMapBGPalette
	ld de, W2_BgPaletteData
	ld c, 8
.copy
	ld a, [hli]
	ld [de], a
	inc de
	dec c
	jr nz, .copy
	ld a, b
	ldh [rWBK], a
	ret

TownMapBGPalette:
	RGB 31, 31, 31, 00, 21, 31, 10, 28, 00, 01, 01, 01

; Player and fly bird share OBJ palette 0. Index 0 is transparent.
; 1 is skin and light feathers, 2 is red, 3 is the outline.
; The 1bpp nest icon and town-map cursor use index 3 only.
TownMapOBJPalette:
	RGB 31, 31, 31, 31, 19, 10, 31, 7, 1, 0, 0, 0

; Restore the map's BG palettes and let sprite palettes upload again.
ClearPlainWindowPal::
	ldh a, [rWBK]
	ld b, a
	ld a, 2
	ldh [rWBK], a
	xor a
	ld [W2_PlainWindowPal], a
	ld a, 1
	ld [W2_ForceBGPUpdate], a
	ld [W2_ForceOBPUpdate], a
	ld a, b
	ldh [rWBK], a
	jp LoadTilesetPalette

; The heal machine writes OBJ palettes itself. Ask the next vblank to put ours back.
ForceOverworldSpritePalettes::
	ldh a, [rWBK]
	ld b, a
	ld a, 2
	ldh [rWBK], a
	ld a, 1
	ld [W2_ForceOBPUpdate], a
	ld a, b
	ldh [rWBK], a
	ret

; The battle-animation palette loader references this. The overworld path does not call it.
LoadSGBPalette_Sprite::
	ret

YellowRedrawRowOrColumn::
	ldh a, [hRedrawRowOrColumnMode]
	and a
	ret z
	ld c, a
	xor a
	ldh [hRedrawRowOrColumnMode], a
	ldh a, [hOnCGB]
	and a
	jr z, .dmg
	ld a, 2
	ldh [rWBK], a
	ld a, [W2_UsePerTileColor]
	ld b, a
	xor a
	ldh [rWBK], a
	ld a, b
	and a
	jr z, .dmg
	ld a, c
	dec a
	jp z, DrawMapColumn
	jp DrawMapRow

.dmg
	ld a, c
	ld b, a
	dec b
	jr nz, .redrawRow
	ld hl, wRedrawRowOrColumnSrcTiles
	ldh a, [hRedrawRowOrColumnDest]
	ld e, a
	ldh a, [hRedrawRowOrColumnDest + 1]
	ld d, a
	ld c, SCREEN_HEIGHT
.loop1
	ld a, [hli]
	ld [de], a
	inc de
	ld a, [hli]
	ld [de], a
	ld a, TILEMAP_WIDTH - 1
	add e
	ld e, a
	jr nc, .noCarry
	inc d
.noCarry
	ld a, d
	and HIGH(TILEMAP_AREA - 1)
	or HIGH(vBGMap0)
	ld d, a
	dec c
	jr nz, .loop1
	ret
.redrawRow
	ld hl, wRedrawRowOrColumnSrcTiles
	ldh a, [hRedrawRowOrColumnDest]
	ld e, a
	ldh a, [hRedrawRowOrColumnDest + 1]
	ld d, a
	push de
	call .DrawHalf
	pop de
	ld a, TILEMAP_WIDTH
	add e
	ld e, a
.DrawHalf
	ld c, SCREEN_WIDTH / 2
.loop2
	ld a, [hli]
	ld [de], a
	inc de
	ld a, [hli]
	ld [de], a
	ld a, e
	inc a
	and %11111
	ld b, a
	ld a, e
	and %11100000
	or b
	ld e, a
	dec c
	jr nz, .loop2
	ret

YellowAutoBgMapTransfer::
	ldh a, [hOnCGB]
	and a
	jr z, .dmg
	ld a, 2
	ldh [rWBK], a
	ld a, [W2_UsePerTileColor]
	ld b, a
	xor a
	ldh [rWBK], a
	ld a, b
	and a
	jp nz, RefreshWindow
.dmg
	ldh a, [hAutoBGTransferEnabled]
	and a
	ret z
	ld [hSPTemp], sp
	ldh a, [hAutoBGTransferPortion]
	and a
	jr z, .transferTopThird
	dec a
	jr z, .transferMiddleThird
	hlcoord 0, 2 * SCREEN_HEIGHT / 3
	ld sp, hl
	ldh a, [hAutoBGTransferDest + 1]
	ld h, a
	ldh a, [hAutoBGTransferDest]
	ld l, a
	ld de, 12 * TILEMAP_WIDTH
	add hl, de
	xor a
	jr .doTransfer
.transferTopThird
	hlcoord 0, 0
	ld sp, hl
	ldh a, [hAutoBGTransferDest + 1]
	ld h, a
	ldh a, [hAutoBGTransferDest]
	ld l, a
	ld a, TRANSFERMIDDLE
	jr .doTransfer
.transferMiddleThird
	hlcoord 0, SCREEN_HEIGHT / 3
	ld sp, hl
	ldh a, [hAutoBGTransferDest + 1]
	ld h, a
	ldh a, [hAutoBGTransferDest]
	ld l, a
	ld de, 6 * TILEMAP_WIDTH
	add hl, de
	ld a, TRANSFERBOTTOM
.doTransfer
	ldh [hAutoBGTransferPortion], a
	ld b, SCREEN_HEIGHT / 3
	jp TransferBgRows
