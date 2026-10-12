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
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "emulator-debug.h"

static JoypadButtons s_buttons;

static void joypad_callback(JoypadButtons* joyp, void* user_data) {
  (void)user_data;
  *joyp = s_buttons;
}

static void run_frames(Emulator* e, int n) {
  for (int i = 0; i < n; i++) {
    Ticks until = emulator_get_ticks(e) + PPU_FRAME_TICKS;
    while (!(emulator_run_until(e, until) & EMULATOR_EVENT_UNTIL_TICKS)) {
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
  Emulator* e = emulator_new(&init);
  if (!e) return 1;
  emulator_set_rom_usage_enabled(FALSE);
  if (strcmp(argv[2], "-") != 0 && !SUCCESS(emulator_read_ext_ram_from_file(e, argv[2]))) return 1;
  emulator_set_joypad_callback(e, joypad_callback, NULL);

  FileData snapshot = {0};
  char line[1024], arg[1000];
  int a, b, c;
  while (fgets(line, sizeof(line), stdin)) {
    if (sscanf(line, "frames %i", &a) == 1) {
      run_frames(e, a);
    } else if (sscanf(line, "buttons %i", &a) == 1) {
      s_buttons = (JoypadButtons){.A = a & 1, .B = (a >> 1) & 1, .select = (a >> 2) & 1,
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
        run_frames(e, 1);
        n++;
      }
      if (peek(e, a) == (u8)b) printf("wait %d\n", n); else printf("wait timeout\n");
    } else if (sscanf(line, "shot %999s", arg) == 1) {
      shot(e, arg);
    } else if (strncmp(line, "save", 4) == 0) {
      file_data_delete(&snapshot);
      emulator_init_state_file_data(&snapshot);
      emulator_write_state(e, &snapshot);
    } else if (strncmp(line, "load", 4) == 0) {
      emulator_read_state(e, &snapshot);
    } else if (sscanf(line, "echo %999[^\n]", arg) == 1) {
      printf("%s\n", arg);
    }
    fflush(stdout);
  }
  return 0;
}
