; Macros for the per-tile GBC color engine (from pokered-gbc).

; rst $18 is not a bankswitch in Yellow, so this is a normal far call.
MACRO CALL_INDIRECT
	farcall \1
ENDM

MACRO tilepal
; vram bank, pals
; without some code rewrites, only vram0 is usable for now
DEF x = \1 << 3
REPT _NARG +- 1
	db (x | PAL_BG_\2)
	SHIFT
ENDR
ENDM
