"""The game's window made again while it runs, for an Output resolution its window cannot hold (host/oot_window_grow.c).

The real file is compiled with the NVN layer's real window need, pool move and pool size (hos_nvn_window_need,
hos_nvn_pool_rehome, hos_nvn_pool_size and the guest checks they use, cut from host/nvn_native.c) and the real texture layout
(host/nvn_layout.c), beside stand-ins for the game's display-size object D, its window of three 2560x1440 textures and its pool
in guest memory, the GPU tracking, the renderer and the host's address space, and run through the game's presents:

- nothing changes without a request, and a request the window holds (a crop) changes nothing;
- a request the window cannot hold writes the size into D+8 and D+0xc and sets D+0xc8, at the next present only, one side
  possibly smaller than the window's;
- a window larger than its pool moves the pool to the host's storage: the need at 3840x2160 first, then the most any Output
  resolution needs (hos_output_size_valid's sizes), never more for a valid size;
- the storage a move replaces is kept: nothing is freed, however many presents follow.

The NVN layer's parts on their own:

- the need holds the window's textures at every valid size, each in the window's formats (RGBA8, RGB10A2) and in a 16-bit float
  one, each at a 64 KB boundary; an object that is not a window needs nothing;
- a moved pool takes the new storage as its memory and GPU address and the new size, its flags kept; the GPU tracking leaves
  the storage before for the new one, and the renderer is told of the new range; moving an object that is not a pool with
  storage stops the game;
- a pool's size is its own, 0 for no pool or another object.

python -I -B tests/test_window_grow.py [--cc gcc]
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cc", "gcc"]

ROOT = Path(__file__).resolve().parents[1]

FIXTURE = r'''
#include "gpu/render/rx_nvn.h"
#include "host/hos_wide_size.h"
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "FAIL:%d %s\n", __LINE__, #x); exit(1); } } while (0)
typedef long long LONG64;
static int64_t InterlockedExchange64(volatile int64_t *v, int64_t to) { const int64_t was = *v; *v = to; return was; }
/* (guest memory: D, the window, its textures and the pool objects; the game's own storage is an address in it, never read) */
enum { GUEST_BYTES = 0x10000, D = 0x100, WINDOW = 0x1000, TEXTURES = 0x2000, TEXTURE_STRIDE = 0x400, POOL = 0x3000,
       VIRTUAL_POOL = 0x3400, GAME_STORAGE = 0x8000, POOL_FLAGS = 0x21 };
static uint8_t guest[GUEST_BYTES];
#define GP(a) ((void *)(guest + (a)))
/* (the host's regions, handed out from REGION_TOP down: a moved pool's storage, which nothing here reads or writes) */
static const uint64_t REGION_LOW = 0x7000000000ULL, REGION_TOP = 0x7f00000000ULL;
static uint8_t region_stand_in;
static void *hos_guest_range(uint64_t a, uint64_t n) {
    if (a < GUEST_BYTES && n <= GUEST_BYTES - a) return guest + a;
    if (a >= REGION_LOW && a < REGION_TOP && n <= REGION_TOP - a) return &region_stand_in;
    return NULL;
}
static void hos_log(const char *fmt, ...) { (void)fmt; }
static void die(const char *fmt, ...) {
    va_list a;
    va_start(a, fmt);
    vfprintf(stderr, fmt, a);
    va_end(a);
    fputs(" (died)\n", stderr);
    exit(3);
}
/* (the GPU tracking and the renderer, as the move calls them) */
static uint64_t untracked_gpu, untracked_size, tracked_gpu, tracked_size, created_gpu, created_size, moves;
void hos_gpu_track(uint64_t gpu, uint64_t size, int on) {
    if (on) tracked_gpu = gpu, tracked_size = size;
    else untracked_gpu = gpu, untracked_size = size;
}
void rx_nvn_pool_created(uint64_t gpu, uint64_t size) { created_gpu = gpu, created_size = size, moves++; }
static uint64_t next_region = REGION_TOP, freed[4];
static int nfreed;
uint64_t hos_region_alloc(uint64_t size, uint64_t align) {
    CHECK(align == 0x10000 && size % 0x10000 == 0);
    next_region -= 0x100000000ULL;
    return next_region;
}
void hos_region_free(uint64_t addr) { CHECK(nfreed < 4); freed[nfreed++] = addr; }
@NVN@
@GROW@
static void set_window(float w, float h) { memcpy(GP(D + 8), &w, 4), memcpy(GP(D + 0xc), &h, 4); }
static float window_w(void) { float w; memcpy(&w, GP(D + 8), 4); return w; }
static float window_h(void) { float h; memcpy(&h, GP(D + 0xc), 4); return h; }
static uint8_t *rebuild(void) { return (uint8_t *)GP(D + 0xc8); }
static nvn_pool *pool(void) { return (nvn_pool *)GP(POOL); }
static uint64_t need(uint32_t w, uint32_t h) { return hos_nvn_window_need(WINDOW, w, h); }
/* (what one window texture takes in a format at w x h, as the game lays it out, at the window's 64 KB boundary) */
static uint64_t texture_bytes(int format, uint32_t w, uint32_t h) {
    nvn_texdesc d = ((const nvn_tex *)GP(TEXTURES))->d;
    nvn_texlayout layout;
    d.format = format, d.width = w, d.height = h;
    nvn_tex_layout(&d, &layout);
    return (layout.size + 0xffff) & ~(uint64_t)0xffff;
}
static void make_window(void) {
    nvn_win *o = (nvn_win *)GP(WINDOW);
    o->magic = NVN_MAGIC('W', 'I', 'N', 'D'), o->ntex = 3, o->active = 3, o->interval = 1;
    for (int i = 0; i < 3; i++) {
        nvn_tex *t = (nvn_tex *)GP(TEXTURES + i * TEXTURE_STRIDE);
        t->d.target = 1, t->d.format = NVN_FORMAT_RGBA8, t->d.width = 2560, t->d.height = 1440, t->d.depth = 1, t->d.levels = 1;
        o->tex[i] = TEXTURES + i * TEXTURE_STRIDE;
    }
    nvn_pool *p = pool();
    p->magic = NVN_MAGIC('P', 'O', 'O', 'L'), p->flags = POOL_FLAGS, p->mem = GAME_STORAGE, p->gpu = GAME_STORAGE;
    p->size = need(2560, 1440);   /* (the game's pool, for its start) */
    nvn_pool *v = (nvn_pool *)GP(VIRTUAL_POOL);
    v->magic = NVN_MAGIC('P', 'O', 'O', 'L'), v->mem = 0, v->size = 0x10000000;
}
int main(int argc, char **argv) {
    make_window();
    if (argc == 2) {   /* (a move of an object that is not a pool with storage) */
        hos_nvn_pool_rehome(!strcmp(argv[1], "window") ? WINDOW : VIRTUAL_POOL, REGION_TOP - 0x10000000ULL, 0x10000000);
        return 0;
    }
    /* (the NVN layer: the need holds the window's textures, the pool's size its own) */
    CHECK(need(2560, 1440) % 0x10000 == 0 && need(2560, 1440) >= 3 * texture_bytes(NVN_FORMAT_RGBA16F, 2560, 1440));
    CHECK(hos_nvn_window_need(0, 2560, 1440) == 0 && hos_nvn_window_need(POOL, 2560, 1440) == 0);
    CHECK(hos_nvn_pool_size(POOL) == need(2560, 1440) && hos_nvn_pool_size(0) == 0 && hos_nvn_pool_size(WINDOW) == 0);
    *(uint64_t *)GP(D + 0x70) = WINDOW, *(uint64_t *)GP(D + 0xc0) = POOL;
    set_window(2560, 1440);
    hos_window_present(D);
    CHECK(!*rebuild() && moves == 0);   /* (no request) */
    hos_window_request(1920, 1080);
    hos_window_present(D);
    CHECK(!*rebuild() && window_w() == 2560 && window_h() == 1440 && moves == 0);   /* (a crop of the window it has) */
    hos_window_request(3440, 1440);
    CHECK(!*rebuild() && window_w() == 2560);   /* (nothing before the game's present) */
    const uint64_t had = pool()->size;
    hos_window_present(D);
    CHECK(*rebuild() == 1 && window_w() == 3440 && window_h() == 1440);
    /* (the first step: 3840x2160's need, the pool object moved over it, its flags kept, the tracking and the renderer told) */
    const uint64_t first = pool()->mem;
    CHECK(moves == 1 && pool()->size == need(3840, 2160) && first != GAME_STORAGE && pool()->gpu == first);
    CHECK(pool()->flags == POOL_FLAGS && hos_nvn_pool_size(POOL) == pool()->size);
    CHECK(untracked_gpu == GAME_STORAGE && untracked_size == had && tracked_gpu == first && tracked_size == pool()->size);
    CHECK(created_gpu == first && created_size == pool()->size);
    *rebuild() = 0;   /* (the game makes its window again and clears it) */
    hos_window_request(2560, 1440);
    hos_window_present(D);
    CHECK(!*rebuild() && moves == 1);   /* (held by the grown window) */
    hos_window_request(3840, 2160);
    hos_window_present(D);
    CHECK(*rebuild() == 1 && window_w() == 3840 && window_h() == 2160 && moves == 1);   /* (in the first step's storage) */
    *rebuild() = 0;
    hos_window_request(5120, 2880);
    hos_window_present(D);
    CHECK(*rebuild() == 1 && window_w() == 5120 && window_h() == 2880 && moves == 2 && pool()->mem != first);
    CHECK(untracked_gpu == first && tracked_gpu == pool()->mem && created_gpu == pool()->mem);
    /* (the second step: the most any valid size needs, which every valid size fits; at each, the need holds the window's
       textures in its formats and in a 16-bit float one) */
    const uint64_t most = pool()->size;
    CHECK(most >= need(5120, 2880) && most >= need(8832, 1656) && most >= need(4288, 3432));
    for (uint32_t w = 640; w <= 9000; w += 8)
        for (uint32_t h = 360; h <= 4000; h += 8) {
            if (!hos_output_size_valid(w, h)) continue;
            const uint64_t n = need(w, h);
            CHECK(n <= most && n % 0x10000 == 0);
            CHECK(n >= 3 * texture_bytes(NVN_FORMAT_RGBA8, w, h) && n >= 3 * texture_bytes(NVN_FORMAT_RGB10A2, w, h));
            CHECK(n >= 3 * texture_bytes(NVN_FORMAT_RGBA16F, w, h));
        }
    *rebuild() = 0;
    hos_window_request(8832, 1656);   /* (wider than the window: made again at the size asked, in the same storage) */
    hos_window_present(D);
    CHECK(*rebuild() == 1 && window_w() == 8832 && window_h() == 1656 && moves == 2);
    /* (the storage the moves replaced, the game's own and the first step's, kept however many presents follow) */
    for (int i = 0; i < 400; i++) hos_window_present(D);
    CHECK(nfreed == 0 && moves == 2);
    /* (no window or pool at D: nothing written) */
    *(uint64_t *)GP(D + 0x70) = 0, *rebuild() = 0;
    hos_window_request(8832, 2000);
    hos_window_present(D);
    CHECK(!*rebuild() && window_w() == 8832 && window_h() == 1656);
    puts("ok");
    return 0;
}
'''


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def line(text, marker):
    start = text.index(marker)
    return text[start:text.index("\n", start) + 1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default="gcc")
    args = parser.parse_args()
    source = (ROOT / "host" / "oot_window_grow.c").read_text(encoding="utf-8")
    body = source[source.index("enum { D_WIDTH"):]   # (after its includes and the NVN layer's declarations)
    native = (ROOT / "host" / "nvn_native.c").read_text(encoding="utf-8")
    nvn = "\n".join((block(native, "static void *gw(uint64_t a, uint64_t n) {"),
                     block(native, "static const nvn_tex *win_tex(const nvn_win *o, int i) {"),
                     block(native, "void hos_nvn_pool_rehome(uint64_t pool, uint64_t storage, uint64_t size) {"),
                     block(native, "uint64_t hos_nvn_pool_size(uint64_t pool) {"),
                     line(native, "enum { WINDOW_TEXTURE_ALIGN"),
                     block(native, "uint64_t hos_nvn_window_need(uint64_t window, uint32_t width, uint32_t height) {"))) + "\n"
    with tempfile.TemporaryDirectory(prefix="window-grow-") as tmp:
        tmp = Path(tmp)
        c, layout, exe = tmp / "fixture.c", tmp / "layout.o", tmp / "fixture.exe"
        c.write_text(FIXTURE.replace("@NVN@", nvn).replace("@GROW@", body), encoding="utf-8")
        subprocess.run([args.cc, "-std=gnu11", "-O1", "-Wall", "-I", str(ROOT), "-c", str(ROOT / "host" / "nvn_layout.c"), "-o",
                        str(layout)], check=True)
        subprocess.run([args.cc, "-std=gnu11", "-O1", "-Wall", "-Wextra", "-Werror", "-I", str(ROOT), str(c), str(layout), "-o",
                        str(exe)], check=True)
        out = subprocess.run([str(exe)], capture_output=True, text=True)
        if out.returncode:
            raise SystemExit(out.stdout + out.stderr)
        for other in ("window", "virtual"):
            out = subprocess.run([str(exe), other], capture_output=True, text=True)
            if out.returncode != 3 or "(died)" not in out.stderr:
                raise SystemExit("FAIL: a move of the %s object did not stop the game: exit %d\n%s" % (other, out.returncode,
                                                                                                         out.stdout + out.stderr))
    print("PASS: the window made again at the game's present for a size it cannot hold only; the pool moved in two steps, the "
          "most a valid size needs at most; the storage the moves replaced kept; the NVN layer's need holds the window's "
          "textures at every valid size, its move and size as asked")


if __name__ == "__main__":
    main()
