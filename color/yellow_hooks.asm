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

; Trade screens draw with Yellow's palette commands. A link trade suspends per-tile
; color before its screens and gets it back when LoadMapData reloads the room; an
; in-game trade suspends it in TradeAnimCommon and resumes in InGameTrade_RestoreScreen.
; The first trade screens come before any palette command, so rerun the overworld
; command the vanilla way: Yellow's palettes and a whole-screen attribute map,
; instead of the map's palettes and attributes left behind.
SuspendOverworldColor::
	call PerTileColorOwnsBgOnCGB
	ret z
	call ClearOverworldColor
	ld b, SET_PAL_OVERWORLD
	jp RunPaletteCommand

; Hands the screen back to per-tile color; the caller's map redraw restamps the
; attributes and SET_PAL_OVERWORLD reloads the palettes.
ResumeOverworldColor::
	ldh a, [hOnCGB]
	and a
	ret z
	ldh a, [rWBK]
	ld b, a
	ld a, 2
	ldh [rWBK], a
	ld a, 1
	ld [W2_UsePerTileColor], a
	ld [W2_ForceBGPUpdate], a
	ld [W2_ForceOBPUpdate], a
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
; Uploads palettes the line-$6e interrupt prepared, then arms that interrupt
; for the next frame. Uploading after the vblank copies landed on line $96
; during the battle-start flash, so on hardware a line of slack was enough to
; miss vblank every frame and the flash never showed. When a scrolled row or
; column was just drawn, or tile graphics are queued, upload after the copies
; instead (PrepareOAMData), so the ~2.3 lines can't push them past vblank. A late upload that runs out of vblank
; retries next frame. (The window third can't count here: the flash itself
; runs with auto BG transfer on.)
; Arms the line-$6e interrupt that builds the window attribute buffer.
; Building it here pushed AutoBgMapTransfer's attribute DMA past vblank,
; and the window colors flickered whenever a text box was up.
; Scanline effects (intro, surfing) own STAT while hLCDCPointer is set,
; and while the hblank interrupt is still enabled.
YellowColorVBlank::
	ld a, 2
	ldh [rWBK], a
	ld hl, W2_DrewRowOrColumn ; set by DrawMapRow/DrawMapColumn, earlier this vblank
	ld b, [hl]
	ld [hl], 0
	xor a
	ldh [rWBK], a
	ldh a, [hVBlankCopySize]
	or b
	ld b, a
	ldh a, [hVBlankCopyDoubleSize]
	or b
	call z, YellowColorUpload
	ldh a, [hLCDCPointer]
	and a
	ret nz
	ldh a, [rSTAT]
	and STAT_MODE_0
	ret nz
	ld a, 2
	ldh [rWBK], a
	ld a, [W2_UsePerTileColor]
	ld b, a
	xor a
	ldh [rWBK], a
	ld a, b
	and a
	ret z
	ldh a, [rIE]
	or IE_STAT
	ldh [rIE], a
	ld a, $6e
	ldh [rLYC], a
	ldh a, [rSTAT]
	or STAT_LYC
	ldh [rSTAT], a
	ret

; LCD interrupt, line $6e only. rWBK is 0. The caller checked the line.
; Clear LYC before returning: hardware retriggers STAT while the match holds,
; and the early-out below is short enough to still be on this line.
; The next vblank arms $6e again. Battles leave UsePerTileColor clear.
YellowLcdPrepare::
	ldh a, [hOnCGB]
	and a
	ret z
	ld a, $ff
	ldh [rLYC], a
	ld a, 2
	ldh [rWBK], a
	ld a, [W2_UsePerTileColor]
	and a
	jr z, .off
	xor a
	ldh [rWBK], a
	jp GbcPrepareVBlank
.off
	xor a
	ldh [rWBK], a
	ret

; Called from YellowColorVBlank at the start of vblank, and again from
; PrepareOAMData after the copies; only modified palettes are sent.
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
	cp $98 ; through line $97: both uploads (~2.3 lines) still end in vblank
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
	cp $98 ; through line $97: both uploads (~2.3 lines) still end in vblank
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
	cp $98 ; through line $97: both uploads (~2.3 lines) still end in vblank
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

; The trade party lists fill the window, which per-tile color draws as a text box in
; palette 7 (white, white, white, black). Their borders use the two middle shades, so
; give palette 7 the link rooms' Yellow palette (PAL_GRAYMON) while the lists are up.
; Leaving them runs SET_PAL_OVERWORLD, which reloads the room's palettes.
SetTradeListPalette::
	call PerTileColorOwnsBgOnCGB
	ret z
	ldh a, [rWBK]
	ld b, a
	ld a, 2
	ldh [rWBK], a
	ld hl, TradeListPalette
	ld de, W2_BgPaletteData + 7 * 8 ; palette 7, 4 colors * 2 bytes
	ld c, 8
.copy
	ld a, [hli]
	ld [de], a
	inc de
	dec c
	jr nz, .copy
	ld a, 1
	ld [W2_ForceBGPUpdate], a
	ld a, b
	ldh [rWBK], a
	ret

TradeListPalette:
	RGB 31,31,31, 20,23,10, 11,11,05, 03,03,03 ; PAL_GRAYMON

; SET_PAL_OVERWORLD while per-tile color owns the screen. Yellow's version
; would replace every palette and the attribute map with the town's 4-color
; set, e.g. when walking out of town. Reload the map's own palettes instead.
; Returns d = 1 if handled.
OverworldColorPaletteCommand::
	call PerTileColorOwnsBgOnCGB
	ld d, 0
	ret z
	ld a, SET_PAL_OVERWORLD
	ld [wDefaultPaletteCommand], a
	call LoadTilesetPalette
	call LoadOverworldSpritePalettes
	ldh a, [rWBK]
	ld b, a
	ld a, 2
	ldh [rWBK], a
	ld a, 1
	ld [W2_ForceBGPUpdate], a
	ld [W2_ForceOBPUpdate], a
	ld a, b
	ldh [rWBK], a
	ld d, 1
	ret

; Move effect sprites use OBJ palettes 2 and 3, which otherwise carry the two
; Pokemon's colors. Called around PlayAnimation in MoveAnimation, so the move's
; type picks the effect colors while it plays. Only the OBJ conversion reads
; W2_AttackPalPointer, so the Pokemon pics (BG) keep their colors through flashes.
SetAttackTypePalette::
	ldh a, [hOnCGB]
	and a
	ret z
	ld a, [wAnimationID]
	and a
	ret z
	cp NUM_ATTACKS + 1
	ret nc ; status and other non-move animations keep their colors
	ldh a, [hWhoseTurn]
	and a
	ld a, [wPlayerMoveType]
	jr z, .gotType
	ld a, [wEnemyMoveType]
.gotType
	cp NUM_TYPES
	jr c, .validType
	xor a ; NORMAL
.validType
	ld hl, AttackTypePalettes
	ld c, a
	ld b, 0
	add hl, bc
	ld c, [hl]
	; A few moves look wrong in their type's colors.
	ld a, [wAnimationID]
	ld b, a
	ld hl, AttackMovePalettes
.findMove
	ld a, [hli]
	cp -1
	jr z, .gotPalette
	cp b
	ld a, [hli]
	jr nz, .findMove
	ld c, a
.gotPalette
	ld a, c ; each palette is 4 colors * 2 bytes
	add a
	add a
	add a
	ld hl, CGBAttackPalettes ; in BANK(SuperPalettes), which DMGPalToCGBPal reads
	ld c, a
	ld b, 0
	add hl, bc
	ld a, 2
	ldh [rWBK], a
	ld a, h
	ld [W2_AttackPalPointer], a
	ld a, l
	ld [W2_AttackPalPointer + 1], a
	xor a
	ldh [rWBK], a
	jr RefreshAttackPalettes

RestoreAttackTypePalette::
	ldh a, [hOnCGB]
	and a
	ret z
	ld a, 2
	ldh [rWBK], a
	xor a
	ld [W2_AttackPalPointer], a
	ldh [rWBK], a
; fallthrough
; Reconvert OBP0 into the CGB OBJ palettes even if rOBP0 did not change.
RefreshAttackPalettes:
	ldh a, [rOBP0]
	cpl
	ld [wLastOBP0], a
	jp UpdateCGBPal_OBP0

; Moves whose effect reads better in another CGBAttackPalettes entry than
; their type's: move, palette.
AttackMovePalettes:
	db SAND_ATTACK, 8 ; tan sand, though the move is Normal
	db -1

; Index into CGBAttackPalettes for each type.
AttackTypePalettes:
	table_width 1
	db 0 ; NORMAL
	db 0 ; FIGHTING
	db 0 ; FLYING
	db 7 ; POISON
	db 3 ; GROUND
	db 3 ; ROCK
	db 0 ; BIRD
	db 5 ; BUG
	db 7 ; GHOST
	ds UNUSED_TYPES_END - UNUSED_TYPES, 0
	db 2 ; FIRE
	db 1 ; WATER
	db 5 ; GRASS
	db 4 ; ELECTRIC
	db 7 ; PSYCHIC_TYPE
	db 6 ; ICE
	db 1 ; DRAGON
	assert_table_length NUM_TYPES

; The portrait tiles are above the tileset, so they use the window palette (7).
; Yellow's palette commands would replace the overworld palettes and attributes.
LoadPikachuPortraitPalettes::
	call PerTileColorOwnsBgOnCGB
	jr nz, .perTile
	callfar LoadOverworldPikachuFrontpicPalettes
	ret
.perTile
	ldh a, [rWBK]
	ld b, a
	ld a, 2
	ldh [rWBK], a
	ld a, 1
	ld [W2_ForceBGPUpdate], a
	ld hl, PikachuPortraitBGPalette
	ld de, W2_BgPaletteData + 7 palettes
	ld c, 1 palettes
.copy
	ld a, [hli]
	ld [de], a
	inc de
	dec c
	jr nz, .copy
	ld a, b
	ldh [rWBK], a
	ret

; CGB colors of PAL_PIKACHU_PORTRAIT in data/sgb/sgb_palettes.asm.
PikachuPortraitBGPalette:
	RGB 31, 31, 31, 31, 18, 00, 19, 07, 01, 03, 03, 03

RestorePikachuPortraitPalettes::
	call PerTileColorOwnsBgOnCGB
	jp z, RunDefaultPaletteCommand
	ldh a, [rWBK]
	ld b, a
	ld a, 2
	ldh [rWBK], a
	ld a, 1
	ld [W2_ForceBGPUpdate], a
	ld a, b
	ldh [rWBK], a
	jp LoadTilesetPalette

; nz when the per-tile engine owns the palettes.
PerTileColorOwnsBgOnCGB:
	ldh a, [hOnCGB]
	and a
	ret z
	call PerTileColorOwnsBg
	ld a, d
	and a
	ret

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
	and a
	jr nz, .keepPrepared
	ld [W2_RedrawPalettesReady], a ; drawn without colors: drop what was prepared
.keepPrepared
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
