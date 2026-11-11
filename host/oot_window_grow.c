/* (hookshot) The game's window made again while it runs, for an Output resolution the window it has cannot hold.

   The game makes its window (its textures, the display-size object D's +0x70) at its start, in a pool of its own (D+0xc0)
   sized for that start. Its present method (f_80547f20) makes them again at D+8 x D+0xc (floats) when D+0xc8 is set; its own
   HDR switch uses that path. A display size, brought by a 300 host/nn_applet.c sends, is asked for here. At the game's next
   present, on its presenting thread before the method reads D+0xc8 (nx2/oot_patches.py), the pool object moves to storage of
   the host's when the new window does not fit it, the size is written and the flag set: the game makes its window again.

   A display size the window holds is a crop of it; any other makes the window again at that size, one side possibly smaller.
   Only the storage grows, in two steps: the need at 3840 x 2160, then the most any Output resolution needs
   (host/hos_wide_size.h hos_output_size_valid). The storage a move replaces is kept: the game's own, and the first step's
   after a second move. */
#include "hos.h"
#include "hos_wide_size.h"
#include <string.h>
#define WIN32_LEAN_AND_MEAN
#include <windows.h>

uint64_t hos_nvn_window_need(uint64_t window, uint32_t width, uint32_t height);   /* nvn_native.c */
void hos_nvn_pool_rehome(uint64_t pool, uint64_t storage, uint64_t size);
uint64_t hos_nvn_pool_size(uint64_t pool);

enum { D_WIDTH = 8, D_HEIGHT = 0xc, D_WINDOW = 0x70, D_POOL = 0xc0, D_REBUILD = 0xc8 };
enum { GRANT_ALIGN = 0x10000 };
enum { UHD_WIDTH = 3840, UHD_HEIGHT = 2160 };
/* (an Output resolution's sides, whole multiples of 8 pixels; see also: host/nn_applet.c hos_output_parse, gpu/vk/vk_menu.cpp
   parse_output) */
enum { SIZE_STEP = 8 };

static volatile int64_t requested;   /* (the display size asked for: width | height << 32; 0 none) */

/* nn_applet.c, at the game's pop of a 300 that brings a display size: room made for it at the next present */
void hos_window_request(uint32_t width, uint32_t height) { InterlockedExchange64(&requested, (int64_t)height << 32 | width); }

/* The most a window of this kind takes at any size hos_output_size_valid accepts: for each width, its tallest valid height */
static uint64_t most_need(uint64_t window) {
    static uint64_t most;
    if (most) return most;
    for (uint32_t w = HOS_OUTPUT_MIN_WIDTH; (uint64_t)w * HOS_OUTPUT_MIN_HEIGHT <= HOS_OUTPUT_MAX_PIXELS; w += SIZE_STEP) {
        uint64_t h = (uint64_t)w * HOS_OUTPUT_NARROWEST_H / HOS_OUTPUT_NARROWEST_W;
        if (h > HOS_OUTPUT_MAX_PIXELS / w) h = HOS_OUTPUT_MAX_PIXELS / w;
        h -= h % SIZE_STEP;
        if (h < HOS_OUTPUT_MIN_HEIGHT || !hos_output_size_valid(w, (uint32_t)h)) continue;
        const uint64_t need = hos_nvn_window_need(window, w, (uint32_t)h);
        if (need > most) most = need;
    }
    return most;
}

/* The storage a move takes for a need: the need at 3840 x 2160, else the most any Output resolution needs, else the need */
static uint64_t grant_size(uint64_t window, uint64_t need) {
    const uint64_t uhd = hos_nvn_window_need(window, UHD_WIDTH, UHD_HEIGHT);
    if (need <= uhd) return uhd;
    const uint64_t most = most_need(window);
    return need <= most ? most : need;
}

/* nx2/oot_patches.py: the game's present method, after its QueuePresentTexture, with D */
void hos_window_present(uint64_t d) {
    static long presents;
    presents++;
    const int64_t want = InterlockedExchange64(&requested, 0);
    if (!want || !d) return;
    const uint32_t w = (uint32_t)want, h = (uint32_t)((uint64_t)want >> 32);
    float fw, fh;
    memcpy(&fw, GP(d + D_WIDTH), 4), memcpy(&fh, GP(d + D_HEIGHT), 4);
    if (w <= (uint32_t)fw && h <= (uint32_t)fh) return;   /* (a crop of the window it has) */
    const uint64_t window = *(uint64_t *)GP(d + D_WINDOW), pool = *(uint64_t *)GP(d + D_POOL);
    const uint64_t need = hos_nvn_window_need(window, w, h), had = hos_nvn_pool_size(pool);
    if (!need || !had) {
        hos_log("nvn: window: no window or pool at D %#llx: %ux%u shown in the window of %.0fx%.0f", (unsigned long long)d, w, h,
                (double)fw, (double)fh);
        return;
    }
    if (need > had) {
        const uint64_t size = grant_size(window, need), storage = hos_region_alloc(size, GRANT_ALIGN);
        hos_nvn_pool_rehome(pool, storage, size);
        hos_log("nvn: window: %llu MB of storage for %ux%u (it needs %llu MB; the pool's %llu MB before kept)",
                (unsigned long long)(size >> 20), w, h, (unsigned long long)(need >> 20), (unsigned long long)(had >> 20));
    }
    const float nw = (float)w, nh = (float)h;
    memcpy(GP(d + D_WIDTH), &nw, 4), memcpy(GP(d + D_HEIGHT), &nh, 4);
    *(uint8_t *)GP(d + D_REBUILD) = 1;
    hos_log("nvn: window: made again at %ux%u (it was %.0fx%.0f) at the game's present %ld", w, h, (double)fw, (double)fh, presents);
}
