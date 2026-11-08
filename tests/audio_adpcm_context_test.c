/* Authored DSP-ADPCM ramps around the actual source-frame decoder. No game samples or device. */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define GP(address) ((void *)(uintptr_t)(address))
#include "audio_adpcm.inc"

static const char *scenario;
static int offset;
#define CHECK(x) do { if (!(x)) { \
    fprintf(stderr, "FAIL %s offset %d, line %d: %s\n", scenario, offset, __LINE__, #x); exit(1); \
} } while (0)

/* Predictor 2*y[n-1]-y[n-2] with zero residuals generates an arithmetic sequence.
   This gives an independent exact oracle, including both history samples, without
   duplicating the ADPCM decoder. Three encoded frames contain 42 source samples. */
static const uint8_t ramp_data[24];
static int ramp_sample(int sample, int initial, int delta) { return initial + delta * (sample + 1); }

static Voice ramp_voice(int start, int end, int loop, int16_t *context) {
    Voice v;
    memset(&v, 0, sizeof v);
    v.format = FMT_ADPCM;
    v.channels = 1;
    v.coefs[0] = 4096;
    v.coefs[1] = -2048;
    v.nwb = 1;
    v.wb[0] = 0x11;
    v.wbc[0] = (WB){.buffer = (uintptr_t)ramp_data, .size = sizeof ramp_data,
                    .start = start, .end = end, .loop = loop, .context = (uintptr_t)context};
    return v;
}

static void expect_sample(Voice *v, int expected) {
    CHECK(next_source_frame(v));
    const int actual = (int)(v->cur[0] * 32768.0f);
    if (actual != expected) {
        fprintf(stderr, "sample: expected %d, got %d\n", expected, actual);
        CHECK(actual == expected);
    }
}

static void context_starts(int loop) {
    scenario = loop ? "context loops" : "context starts";
    /* Every intra-frame offset, at both the first and a later frame; also aligned starts.
       Both rising and falling signals exercise signed history and both predictor terms. */
    for (int direction = 0; direction < 2; direction++) {
        const int initial = direction ? -2000 : 1000, delta = direction ? -29 : 37;
        for (offset = 0; offset < 28; offset++) {
            int16_t context[3] = {0, (int16_t)ramp_sample(offset - 1, initial, delta),
                                 (int16_t)ramp_sample(offset - 2, initial, delta)};
            Voice v = ramp_voice(offset, 42, loop, context);
            v.yn1 = -123; v.yn2 = 456;   /* The supplied context must replace older voice history. */
            const int cycles = loop ? 3 : 1;
            for (int repeat = 0; repeat < cycles; repeat++) {
                for (int sample = offset; sample < 42; sample++)
                    expect_sample(&v, ramp_sample(sample, initial, delta));
            }
            CHECK(v.played == cycles * (42 - offset));
            if (loop) {
                CHECK(v.nwb == 1 && v.nrel == 0);
            } else {
                CHECK(!next_source_frame(&v));
                CHECK(v.nwb == 0 && v.nrel == 1 && v.rel[0] == 0x11);
            }
        }
    }
}

static void no_context_starts(void) {
    scenario = "no-context prefix";
    for (offset = 0; offset < 28; offset++) {
        const int frame_start = offset / 14 * 14;
        Voice v = ramp_voice(offset, 42, 0, NULL);
        /* Without a context, the existing fallback carries history from the frame boundary. */
        v.yn1 = (int16_t)ramp_sample(frame_start - 1, 1000, 37);
        v.yn2 = (int16_t)ramp_sample(frame_start - 2, 1000, 37);
        for (int sample = offset; sample < 42; sample++) expect_sample(&v, ramp_sample(sample, 1000, 37));
        CHECK(v.played == 42 - offset);
        CHECK(!next_source_frame(&v));
        CHECK(v.nrel == 1);
    }
}

static void buffer_continuation(void) {
    scenario = "buffer continuation";
    offset = 0;
    int16_t context[3] = {0, 1000, 963};
    Voice v = ramp_voice(0, 14, 0, context);
    v.nwb = 2;
    v.wb[1] = 0x22;
    v.wbc[1] = v.wbc[0];
    v.wbc[1].end = 28;
    v.wbc[1].context = 0;   /* The next buffer continues the predictor, without a new context. */
    for (int sample = 0; sample < 42; sample++) expect_sample(&v, ramp_sample(sample, 1000, 37));
    CHECK(v.played == 42);
    CHECK(!next_source_frame(&v));
    CHECK(v.nrel == 2 && v.rel[0] == 0x11 && v.rel[1] == 0x22);
}

static void no_context_loop(void) {
    scenario = "no-context loop carries history";
    offset = 0;
    Voice v = ramp_voice(0, 14, 1, NULL);
    v.yn1 = 1000; v.yn2 = 963;
    for (int sample = 0; sample < 42; sample++) expect_sample(&v, ramp_sample(sample, 1000, 37));
    CHECK(v.played == 42 && v.nwb == 1 && v.nrel == 0);
}

static void pcm_loop(void) {
    scenario = "PCM loop";
    offset = 3;
    const int16_t pcm[] = {-20, 80, -160, 320, -640, 1280, -2560, 5120, -10240, 100};
    Voice v;
    memset(&v, 0, sizeof v);
    v.format = FMT_PCM16;
    v.channels = 1;
    v.nwb = 1;
    v.wbc[0] = (WB){.buffer = (uintptr_t)pcm, .size = sizeof pcm, .start = 3, .end = 9, .loop = 1};
    for (int sample = 0; sample < 24; sample++) expect_sample(&v, pcm[3 + sample % 6]);
    CHECK(v.played == 24 && v.nwb == 1 && v.nrel == 0);
}

int main(void) {
    context_starts(0);
    context_starts(1);
    no_context_starts();
    buffer_continuation();
    no_context_loop();
    pcm_loop();
    puts("PASS: actual decoder, all 13 unaligned offsets across two frames, signed contexts, repeated loops, fallback, continuation and PCM");
    return 0;
}
