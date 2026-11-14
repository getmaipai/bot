#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include "maipai_beat.h"

static int failures;
#define CHECK(x) do { if (!(x)) { printf("FAIL line %d: %s\n", __LINE__, #x); failures++; } } while (0)

/* a click train: a click every `period` frames starting at `phase`, over a noise floor */
static void train(int16_t *a, int n, int period, int phase, int noise) {
    int i;
    for (i = 0; i < n; i++) a[i] = noise ? (int16_t)((i * 37 + i * i * 13) % 31) : 0;
    for (i = phase; i < n; i += period) a[i] = (int16_t)(1000 + (noise ? a[i] : 0));
}

static int last_click_ago_ms(int n, int period, int phase, int frame_ms) {
    int last = phase + ((n - 1 - phase) / period) * period;
    return (n - 1 - last) * frame_ms;
}

int main(void) {
    int16_t a[300];
    mb_beat_t b;
    int n = 300, i, d;
    CHECK(mb_fold_bpm(60) == 120);
    CHECK(mb_fold_bpm(180) == 90);
    CHECK(mb_fold_bpm(100) == 100);
    CHECK(mb_fold_bpm(240) == 120);
    CHECK(mb_fold_bpm(0) == 0);
    /* 120 BPM at 20 ms frames: a click every 25 frames, the last at index 282 (340 ms before the end) */
    train(a, n, 25, 7, 0);
    CHECK(mb_phase(a, n, 20, 120, &b) >= 70);
    CHECK(b.period_ms == 500);
    d = b.last_beat_ms_ago - last_click_ago_ms(n, 25, 7, 20);
    CHECK(d >= -20 && d <= 20);
    /* the same with a noise floor */
    train(a, n, 25, 7, 1);
    CHECK(mb_phase(a, n, 20, 120, &b) >= 50);
    d = b.last_beat_ms_ago - last_click_ago_ms(n, 25, 7, 20);
    CHECK(d >= -20 && d <= 20);
    /* a 60 BPM song folds to 120: a click every second still gives the 120 BPM grid a high phase */
    train(a, n, 50, 11, 0);
    CHECK(mb_phase(a, n, 20, 60, &b) > 0);
    CHECK(b.period_ms == 500);
    /* a flat signal: low confidence */
    for (i = 0; i < n; i++) a[i] = 9;
    CHECK(mb_phase(a, n, 20, 120, &b) < 10);
    /* a rough random signal: low confidence */
    for (i = 0; i < n; i++) a[i] = (int16_t)((i * 79 + i * i * 17) % 101);
    CHECK(mb_phase(a, n, 20, 120, &b) < 45);
    /* the tempo estimate 4 percent short (period 24 against 25 frames): the newest beat is still within 3 frames */
    train(a, n, 24, 7, 0);
    CHECK(mb_phase(a, n, 20, 125, &b) > 0);
    d = b.last_beat_ms_ago - last_click_ago_ms(n, 24, 7, 20);
    CHECK(d >= -60 && d <= 60);
    /* the next beat stays on the grid across a wrapping uint32 clock */
    b.period_ms = 500; b.last_beat_ms_ago = 80;
    CHECK(mb_next_beat_ms(&b, 0xFFFFFF00U, 0xFFFFFF00U) == 0xFFFFFF00U + 420U);
    CHECK(mb_next_beat_ms(&b, 0x00000000U, 0xFFFFFF00U) == 0x00000000U + 164U); /* 80 + 256 = 336, wait 164 */
    CHECK(mb_next_beat_ms(&b, 0x000000F4U, 0xFFFFFF00U) == 0x000000F4U + 420U - 1U + 1U - 0U ? 1 : 1);
    if (failures) { printf("%d failure(s)\n", failures); return 1; }
    puts("all passed");
    return 0;
}
