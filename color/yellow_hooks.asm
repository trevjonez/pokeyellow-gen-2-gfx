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
; From a LoadMapData that kept the LCD on (BeginMapLoad), the screen is blank:
; DMA the map in and let vblank upload the palettes.
ApplyOverworldColor::
	ld a, 2
	ldh [rWBK], a
	xor a
	ld [W2_MenuColorSuspended], a
	inc a
	ld [W2_UsePerTileColor], a
	ld [W2_ForceBGPUpdate], a
	ld [W2_ForceOBPUpdate], a
	xor a
	ldh [rWBK], a
	call LoadTilesetPalette
	call LoadOverworldSpritePalettes
	ldh a, [hFastVRAMCopy]
	and a
	jr z, .lcdOff
	xor a
	ldh [hFastVRAMCopy], a
	jp LoadMapVramAndColorsDMA
.lcdOff
	call GbcPrepareVBlank
	ld a, 1
	call UploadBgPalettes
	ld a, 1
	call UploadObjPalettes
	jp LoadMapVramAndColors

; In place of LoadMapData's DisableLCD. Turning the LCD off shows white on the
; GBC, a flash in the middle of the fade to black. While the screen is blank
; anyway (every palette black or white), leave it on: CopyVideoData then goes
; through FastCopyVideoData, and ApplyOverworldColor DMAs the map.
BeginMapLoad::
	ldh a, [hOnCGB]
	and a
	jp z, DisableLCD
	ldh a, [rLCDC]
	bit B_LCDC_ENABLE, a
	ret z
	ldh a, [rBGP]
	ld b, a
	ldh a, [rOBP0]
	cp b
	jp nz, DisableLCD
	ldh a, [rOBP1]
	cp b
	jp nz, DisableLCD
	inc a
	jr z, .blank ; all black
	dec a
	jp nz, DisableLCD
.blank ; or all white
	ld a, 2
	ldh [rWBK], a
	ld hl, FastHDMARun
	ld de, W2_FastHDMARun
	ld c, FastHDMARunEnd - FastHDMARun
.copyRun
	ld a, [hli]
	ld [de], a
	inc de
	dec c
	jr nz, .copyRun
	xor a
	ldh [rWBK], a
	inc a
	ldh [hFastVRAMCopy], a
	ret

; Runs from W2_FastHDMARun, with interrupts off and the DMA registers but HDMA5
; set: maps ROM bank b, starts an HBlank DMA of c, waits for it, and maps back
; hLoadedROMBank.
FastHDMARun:
	ld a, b
	ld [rROMB], a
	ld a, c
	ldh [rHDMA5], a
.busy
	ldh a, [rHDMA5]
	inc a ; $ff when done
	jr nz, .busy
	ldh a, [hLoadedROMBank]
	ld [rROMB], a
	ret
FastHDMARunEnd:

ASSERT FAST_COPY_STAGING + FAST_COPY_MAX_TILES * TILE_SIZE <= wTileMapBackup + 480 ; the union's size

; From CopyVideoData through rst $18: copy c tiles from [hFastCopyBank]:de to
; [hFastCopyDest] with the LCD on. The DMA reads 16-byte-aligned sources, so
; aligned graphics (tilesets, NPC sprites) go straight from ROM; anything else
; (the text box) through the staging buffer.
FastCopyVideoData::
	ld a, e
	and $f
	jr nz, .staged
.direct
	ld a, c
	and a
	ret z
	cp 112 + 1 ; still leaves a chunk room to start, with 30 lines to spare
	jr c, .gotDirectCount
	ld a, 112
.gotDirectCount
	ld b, a
	push bc
	ld h, d
	ld l, e
	ldh a, [hFastCopyBank]
	ld c, a
	ld a, b
	ld b, c
	call FastHDMA
	pop bc
	ld d, h
	ld e, l
	ld a, c
	sub b
	ld c, a
	jr .direct

.staged
	ld a, c
	and a
	ret z
	cp FAST_COPY_MAX_TILES + 1
	jr c, .gotCount
	ld a, FAST_COPY_MAX_TILES
.gotCount
	ld b, a
	push bc
	push de
	ld l, a
	ld h, 0
	add hl, hl
	add hl, hl
	add hl, hl
	add hl, hl
	ld b, h
	ld c, l
	ld h, d
	ld l, e
	ld de, FAST_COPY_STAGING
	ldh a, [hFastCopyBank]
	call FarCopyData
	pop de
	pop bc
	push bc
	push de
	ld a, b
	ld hl, FAST_COPY_STAGING
	ld b, BANK(@)
	call FastHDMA
	pop de
	pop bc
	ld l, b
	ld h, 0
	add hl, hl
	add hl, hl
	add hl, hl
	add hl, hl
	add hl, de
	ld d, h
	ld e, l
	ld a, c
	sub b
	ld c, a
	jr .staged

; Copy a blocks of 16 bytes from b:hl to [hFastCopyDest] in rVBK's bank, with
; the LCD on; hl and [hFastCopyDest] end up past them. HBlank DMA moves one
; block per hblank by itself, so this doesn't wait for vblank: 28 tiles take 28
; lines. (The vblank handler can use all of vblank during a map load, which
; left no room for a GDMA.) The DMA reads rVBK and its registers live, and the
; vblank handler, which can run past line 153 here, sets both. So a chunk
; starts only if it ends before vblank, with interrupts off until it's done.
FastHDMA::
	ld c, a
.wait
	ldh a, [rLY]
	add c
	cp LY_VBLANK - 2
	jr nc, .wait
	di
	ldh a, [rLY]
	add c
	cp LY_VBLANK - 2
	jr c, .go
	ei
	jr .wait
.go
	ld a, h
	ldh [rHDMA1], a
	ld a, l
	ldh [rHDMA2], a
	ldh a, [hFastCopyDest + 1]
	ldh [rHDMA3], a
	ldh a, [hFastCopyDest]
	ldh [rHDMA4], a
	push bc
	ld a, c
	dec a
	or VDMA_LEN_MODE_HBLANK
	ld c, a
	ld a, 2
	ldh [rWBK], a
	call W2_FastHDMARun
	xor a
	ldh [rWBK], a
	pop bc
	ei
	ld e, c
	ld d, 0
REPT 4
	sla e
	rl d
ENDR
	add hl, de
	ldh a, [hFastCopyDest]
	add e
	ldh [hFastCopyDest], a
	ldh a, [hFastCopyDest + 1]
	adc d
	ldh [hFastCopyDest + 1], a
	ret

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
	jr nz, .perTile
	ld d, 0
	ldh a, [hOnCGB]
	and a
	ret z
	ldh a, [rWBK]
	ld b, a
	ld a, 2
	ldh [rWBK], a
	ld a, [W2_MenuColorSuspended]
	ld c, a
	ld a, b
	ldh [rWBK], a
	ld a, c
	and a
	ret z
	call ResumeOverworldColorAfterMenu
.perTile
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

; d = a palette command other than SET_PAL_OVERWORLD, about to run. Full-screen
; menus opened from the overworld (party, status, Pokedex, trainer card, naming,
; slots...) lay out their own palettes and BG attributes. With per-tile color
; still on, its window refresh overwrote their attributes and Yellow's palette
; updates were skipped: party icons kept the colors of their list slots. Step
; aside for them; SET_PAL_OVERWORLD on the way back resumes per-tile color.
MenuPaletteCommand::
	ld a, d
	cp SET_PAL_STATUS_SCREEN
	jr z, .handOff
	cp SET_PAL_POKEDEX
	jr z, .handOff
	cp SET_PAL_SLOTS
	jr z, .handOff
	cp SET_PAL_GENERIC
	jr z, .handOff
	cp SET_PAL_PARTY_MENU
	jr z, .handOff
	cp SET_PAL_POKEMON_WHOLE_SCREEN
	jr z, .handOff
	cp SET_PAL_TRAINER_CARD
	ret nz
.handOff
	call PerTileColorOwnsBgOnCGB
	ret z
	call ClearOverworldColor
	ldh a, [rWBK]
	ld b, a
	ld a, 2
	ldh [rWBK], a
	ld a, 1
	ld [W2_MenuColorSuspended], a
	ld a, b
	ldh [rWBK], a
	ret

; Back from a menu MenuPaletteCommand stepped aside for. Its palette layout also
; wrote both BG maps' attributes (LoadBGMapAttributes), so with the LCD off,
; recolor every BG map entry from its tile; the return path has the screen
; whited out already. The caller reloads the palettes.
ResumeOverworldColorAfterMenu:
	ldh a, [rLCDC]
	push af
	and LCDC_ON
	call nz, DisableLCD ; it waits for line 145, which never comes with the LCD off
	ld a, 2
	ldh [rWBK], a
	xor a
	ld [W2_MenuColorSuspended], a
	inc a
	ld [W2_UsePerTileColor], a
	ld hl, vBGMap0
	ld d, HIGH(W2_TilesetPaletteMap)
.restamp
	xor a
	ldh [rVBK], a
	ld e, [hl]
	inc a
	ldh [rVBK], a
	ld a, [de]
	ld [hli], a
	ld a, h
	cp HIGH(vBGMap1 + TILEMAP_AREA)
	jr nz, .restamp
	xor a
	ldh [rVBK], a
	ldh [rWBK], a
	pop af
	and LCDC_ON
	ret z
	jp EnableLCD

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
	; Razor Leaf's falling leaves set rOBP0 to wAnimPalette and never put it back.
	; Restore what SetAnimationPalette gave every move, so no effect's shades stick.
	ld a, $e4
	ldh [rOBP0], a
	call ClearAttackPalPointer
; fallthrough
; Reconvert OBP0 into the CGB OBJ palettes even if rOBP0 did not change.
RefreshAttackPalettes:
	ldh a, [rOBP0]
	cpl
	ld [wLastOBP0], a
	jp UpdateCGBPal_OBP0

ClearAttackPalPointer:
	ld a, 2
	ldh [rWBK], a
	xor a
	ld [W2_AttackPalPointer], a
	ldh [rWBK], a
	ret

; A thrown ball, colored by its type, is drawn in OBJ palettes 2 and 3 like move effects, which
; otherwise carry the two Pokemon's colors. TossBallAnimation calls this before
; each part: the ball (toss, shakes, a trainer blocking it) gets the ball palette,
; the smoke and the pic hiding or showing get the Pokemon colors back.
SetBallAnimPalette::
	ldh a, [hOnCGB]
	and a
	ret z
	ld a, [wAnimationID]
	cp POOF_ANIM
	jr z, ClearAttackPalPointer
	cp TOSS_ANIM
	jr c, ClearAttackPalPointer
	cp ULTRATOSS_ANIM + 1
	jr nc, ClearAttackPalPointer
	ld a, [wCurItem] ; MASTER_BALL to POKE_BALL are 1-4; anything else is the Safari Ball
	dec a
	cp POKE_BALL
	jr c, .gotBall
	ld a, POKE_BALL
.gotBall
	ld hl, CGBAttackPalettes + 9 * PAL_SIZE ; Master Ball
	ld bc, PAL_SIZE
	call AddNTimes
	ld a, 2
	ldh [rWBK], a
	ld a, h
	ld [W2_AttackPalPointer], a
	ld a, l
	ld [W2_AttackPalPointer + 1], a
	xor a
	ldh [rWBK], a
	ret

; After the toss. A caught ball (last part: shaking) stays on screen through the
; text, so its colors stay in the palettes; anything later converts OBP0 without
; the ball palette. Otherwise the ball is gone: reconvert now.
ClearBallAnimPalette::
	ldh a, [hOnCGB]
	and a
	ret z
	call ClearAttackPalPointer
	ld a, [wAnimationID]
	cp SHAKE_ANIM
	ret z
	jr RefreshAttackPalettes

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
