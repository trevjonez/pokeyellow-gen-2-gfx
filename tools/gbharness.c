/*
 * Scripted headless Game Boy runner built on binjgb (https://github.com/binji/binjgb).
 * tools/battlepreview.py builds and drives it; see that file for how.
 *
 * Usage: gbharness ROM SAV|- < script
 *
 * Script commands, one per line (numbers are decimal or 0x hex):
 *   frames N             run N frames
 *   buttons MASK         hold buttons: A=1 B=2 SELECT=4 START=8 RIGHT=16 LEFT=32 UP=64 DOWN=128
 *   poke ADDR VAL        write a byte; $D000-$DFFF go to WRAM bank 1
 *   peek ADDR            print "peek ADDR VAL"
 *   peekn ADDR N         print "peekn ADDR" and N bytes as hex
 *   wait ADDR VAL N      run until [ADDR] == VAL, up to N frames; prints "wait FRAMES" or "wait timeout"
 *   shot PATH            write the current frame as a binary PPM
 *   save / load          snapshot / restore the whole machine in memory
 *   echo TEXT            print TEXT (handy to delimit output)
 *   link                 copy this machine into a second one joined by a link cable
 *                        (tools/binjgb-link.patch); frames then runs both in lockstep
 *   use N                send later commands to machine N (0 or 1)
 *   bgmap N              print "bgmap N", the 32x32 BG map at $9800 (N=0) or $9C00 (N=1)
 *                        as hex tile IDs, then its CGB attributes, read straight from VRAM
 */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "emulator-debug.h"

void emulator_link(Emulator*, Emulator*);   /* from tools/binjgb-link.patch */

static Emulator* s_emu[2];
static int s_count = 1;
static JoypadButtons s_buttons[2];

static void joypad_callback(JoypadButtons* joyp, void* user_data) {
  *joyp = s_buttons[(intptr_t)user_data];
}

/* Linked machines run in slices of a few scanlines, so neither gets far ahead
 * of the other while they swap bytes. */
#define LINK_SLICE_TICKS (PPU_FRAME_TICKS / 32)

static void run_frames(int n) {
  Ticks slice = s_count == 1 ? PPU_FRAME_TICKS : LINK_SLICE_TICKS;
  for (Ticks t = 0; t < (Ticks)n * PPU_FRAME_TICKS; t += slice) {
    for (int i = 0; i < s_count; i++) {
      Ticks until = emulator_get_ticks(s_emu[i]) + slice;
      while (!(emulator_run_until(s_emu[i], until) & EMULATOR_EVENT_UNTIL_TICKS)) {
      }
    }
  }
}

static int is_banked_wram(int addr) { return addr >= 0xd000 && addr < 0xe000; }

static u8 peek(Emulator* e, int addr) {
  if (!is_banked_wram(addr)) return emulator_read_u8_raw(e, addr);
  u8 bank = emulator_read_u8_raw(e, 0xff70);
  emulator_write_u8_raw(e, 0xff70, 1);
  u8 v = emulator_read_u8_raw(e, addr);
  emulator_write_u8_raw(e, 0xff70, bank);
  return v;
}

static void poke(Emulator* e, int addr, u8 value) {
  if (!is_banked_wram(addr)) {
    emulator_write_u8_raw(e, addr, value);
    return;
  }
  u8 bank = emulator_read_u8_raw(e, 0xff70);
  emulator_write_u8_raw(e, 0xff70, 1);
  emulator_write_u8_raw(e, addr, value);
  emulator_write_u8_raw(e, 0xff70, bank);
}

static void shot(Emulator* e, const char* path) {
  FILE* f = fopen(path, "wb");
  if (!f) {
    fprintf(stderr, "cannot write %s\n", path);
    exit(1);
  }
  fprintf(f, "P6\n%d %d\n255\n", SCREEN_WIDTH, SCREEN_HEIGHT);
  RGBA* px = *emulator_get_frame_buffer(e);
  for (int i = 0; i < SCREEN_WIDTH * SCREEN_HEIGHT; i++) {
    u8 rgb[3] = {px[i] & 0xff, (px[i] >> 8) & 0xff, (px[i] >> 16) & 0xff};
    fwrite(rgb, 1, 3, f);
  }
  fclose(f);
}

int main(int argc, char** argv) {
  if (argc < 3) {
    fprintf(stderr, "usage: %s ROM SAV|- < script\n", argv[0]);
    return 1;
  }
  FileData rom;
  if (!SUCCESS(file_read_aligned(argv[1], MINIMUM_ROM_SIZE, &rom))) return 1;
  EmulatorInit init;
  ZERO_MEMORY(init);
  init.rom = rom;
  init.audio_frequency = 44100;
  init.audio_frames = 4410 * SOUND_OUTPUT_COUNT;
  init.random_seed = 1;
  Emulator* e = s_emu[0] = emulator_new(&init);
  if (!e) return 1;
  emulator_set_rom_usage_enabled(FALSE);
  if (strcmp(argv[2], "-") != 0 && !SUCCESS(emulator_read_ext_ram_from_file(e, argv[2]))) return 1;
  emulator_set_joypad_callback(e, joypad_callback, (void*)0);

  FileData snapshots[2] = {{0}};
  int cur = 0;
  char line[1024], arg[1000];
  int a, b, c;
  while (fgets(line, sizeof(line), stdin)) {
    if (sscanf(line, "frames %i", &a) == 1) {
      run_frames(a);
    } else if (sscanf(line, "use %i", &a) == 1 && a >= 0 && a < s_count) {
      cur = a;
      e = s_emu[cur];
    } else if (strncmp(line, "link", 4) == 0 && s_count == 1) {
      FileData state;
      emulator_init_state_file_data(&state);
      emulator_write_state(e, &state);
      s_emu[1] = emulator_new(&init);
      emulator_read_state(s_emu[1], &state);
      file_data_delete(&state);
      emulator_set_joypad_callback(s_emu[1], joypad_callback, (void*)1);
      emulator_link(s_emu[0], s_emu[1]);
      s_count = 2;
    } else if (sscanf(line, "buttons %i", &a) == 1) {
      s_buttons[cur] = (JoypadButtons){.A = a & 1, .B = (a >> 1) & 1, .select = (a >> 2) & 1,
                                  .start = (a >> 3) & 1, .right = (a >> 4) & 1, .left = (a >> 5) & 1,
                                  .up = (a >> 6) & 1, .down = (a >> 7) & 1};
    } else if (sscanf(line, "poke %i %i", &a, &b) == 2) {
      poke(e, a, (u8)b);
    } else if (sscanf(line, "peekn %i %i", &a, &b) == 2) {
      printf("peekn 0x%04x ", a);
      for (int i = 0; i < b; i++) printf("%02x", peek(e, a + i));
      printf("\n");
    } else if (sscanf(line, "peek %i", &a) == 1) {
      printf("peek 0x%04x 0x%02x\n", a, peek(e, a));
    } else if (sscanf(line, "wait %i %i %i", &a, &b, &c) == 3) {
      int n = 0;
      while (n < c && peek(e, a) != (u8)b) {
        run_frames(1);
        n++;
      }
      if (peek(e, a) == (u8)b) printf("wait %d\n", n); else printf("wait timeout\n");
    } else if (sscanf(line, "shot %999s", arg) == 1) {
      shot(e, arg);
    } else if (strncmp(line, "save", 4) == 0) {
      file_data_delete(&snapshots[cur]);
      emulator_init_state_file_data(&snapshots[cur]);
      emulator_write_state(e, &snapshots[cur]);
    } else if (strncmp(line, "load", 4) == 0) {
      emulator_read_state(e, &snapshots[cur]);
    } else if (sscanf(line, "bgmap %i", &a) == 1) {
      TileMap tiles, attrs;
      emulator_get_tile_map(e, a ? TILE_MAP_9C00_9FFF : TILE_MAP_9800_9BFF, tiles);
      emulator_get_tile_map_attr(e, a ? TILE_MAP_9C00_9FFF : TILE_MAP_9800_9BFF, attrs);
      printf("bgmap %d ", a);
      for (int i = 0; i < TILE_MAP_SIZE; i++) printf("%02x", tiles[i]);
      printf(" ");
      for (int i = 0; i < TILE_MAP_SIZE; i++) printf("%02x", attrs[i]);
      printf("\n");
    } else if (sscanf(line, "echo %999[^\n]", arg) == 1) {
      printf("%s\n", arg);
    }
    fflush(stdout);
  }
  return 0;
}
