/* Host test for the on-unit music features (patch 100): cc -std=c99 -Wall -Wextra -Werror -I<dir with the header> ... -lm.
 * Synthesizes 24 kHz signals, runs them through the front end and the analysis the way the firmware
 * worker does (a summary once a second) and prints one "FEAT <name> ..." line per signal for the
 * Python test, which applies the host decision layer. The C asserts only what the extractor itself
 * promises (tempo of a steady beat, no tempo in a steady tone, a speech-like 4 Hz envelope shows
 * up in the 3 to 6 Hz share, near-silence stays under the level gate). */
#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include "maipai_music_core.h"

#define RATE 24000
#define SECONDS 12
#define N (RATE * SECONDS)
#define PI 3.14159265f

static int failures;
#define CHECK(cond)                                                      \
    do {                                                                 \
        if (!(cond)) {                                                   \
            printf("FAIL line %d: %s\n", __LINE__, #cond);               \
            failures++;                                                  \
        }                                                                \
    } while (0)

static uint32_t rng = 12345u;
static float noise(void) /* uniform -1..1, deterministic */
{
    rng = rng * 1664525u + 1013904223u;
    return (float)((int32_t)(rng >> 8) - 0x800000) / (float)0x800000;
}

static int16_t buf[N];

static void scale_to_rms(float* x, float rms)
{
    double s = 0;
    int i;
    for (i = 0; i < N; ++i) s += (double)x[i] * x[i];
    s = sqrt(s / N);
    for (i = 0; i < N; ++i) buf[i] = (int16_t)fmaxf(-32000.0f, fminf(32000.0f, x[i] * (float)(rms / s)));
}

static float sig[N];

static void gen_click(float bpm) /* a 5 ms decaying 1 kHz burst on every beat */
{
    int i, period = (int)(RATE * 60.0f / bpm);
    memset(sig, 0, sizeof(sig));
    for (i = 0; i < N; ++i) {
        const int t = i % period;
        if (t < RATE / 200) sig[i] = sinf(2.0f * PI * 1000.0f * (float)t / RATE) * expf(-(float)t / (RATE * 0.0015f));
    }
}

static void gen_music(float bpm) /* kick, off-beat snare noise, 8th-note hats, a chord pad */
{
    int i, beat = (int)(RATE * 60.0f / bpm);
    static const float chord[2][3] = {{261.6f, 329.6f, 392.0f}, {220.0f, 277.2f, 329.6f}};
    float hat_lp = 0;
    for (i = 0; i < N; ++i) {
        const int tb = i % beat, bi = i / beat, th = i % (beat / 2);
        const float t = (float)i / RATE;
        float v = 0, tk = (float)tb / RATE;
        const float* c = chord[(i / (RATE * 2)) % 2];
        v += 0.9f * sinf(2.0f * PI * (55.0f + 90.0f * expf(-tk * 30.0f)) * tk) * expf(-tk * 9.0f); /* kick */
        if (bi % 2 == 1) v += 0.35f * noise() * expf(-tk * 18.0f);                                  /* snare */
        {
            const float hn = noise();
            const float hp = hn - hat_lp;
            hat_lp += 0.3f * hp;
            v += 0.15f * hp * expf(-(float)th / RATE * 60.0f);                                      /* hat */
        }
        v += 0.12f * (sinf(2.0f * PI * c[0] * t) + sinf(2.0f * PI * c[1] * t) + sinf(2.0f * PI * c[2] * t));
        sig[i] = v;
    }
}

static void gen_sine(void) { int i; for (i = 0; i < N; ++i) sig[i] = sinf(2.0f * PI * 440.0f * (float)i / RATE); }
static void gen_white(void) { int i; for (i = 0; i < N; ++i) sig[i] = noise(); }
static void gen_am4(void) /* white noise at a 4 Hz raised-cosine envelope */
{
    int i;
    for (i = 0; i < N; ++i) sig[i] = noise() * (0.5f - 0.5f * cosf(2.0f * PI * 4.0f * (float)i / RATE));
}
static void gen_syllables(void) /* a voiced buzz (120 Hz and harmonics, a formant sweep) in 120-250 ms syllables with 60-200 ms pauses, a hiss now and then */
{
    int i = 0;
    while (i < N) {
        const int len = (int)(RATE * (0.12f + 0.13f * (noise() * 0.5f + 0.5f)));
        const int gap = (int)(RATE * (0.06f + 0.14f * (noise() * 0.5f + 0.5f)));
        const int hiss = noise() > 0.6f;
        const float f0 = 100.0f + 40.0f * (noise() * 0.5f + 0.5f);
        int j, k;
        for (j = 0; j < len && i + j < N; ++j) {
            const float env = sinf(PI * (float)j / len);
            float v = 0;
            if (hiss) {
                v = noise() * 0.4f;
            } else {
                for (k = 1; k <= 12; ++k) v += sinf(2.0f * PI * f0 * (float)k * (float)(i + j) / RATE) / (float)k * (k < 5 ? 1.0f : 0.5f);
            }
            sig[i + j] = v * env;
        }
        i += len;
        for (j = 0; j < gap && i + j < N; ++j) sig[i + j] = 0.01f * noise();
        i += gap;
    }
}

static void run(const char* name, float rms, mm_feat_t* last)
{
    mm_front_t f; mm_an_t* a = (mm_an_t*)malloc(sizeof(mm_an_t));
    mm_frame_t out[8];
    int pos = 0, got, k, frames = 0;
    scale_to_rms(sig, rms);
    mm_front_init(&f, RATE);
    mm_an_reset(a);
    while (pos < N) {
        int chunk = 720; /* the codec hands over 30 ms at a time */
        if (pos + chunk > N) chunk = N - pos;
        got = mm_front_feed(&f, buf + pos, chunk, 1, out);
        for (k = 0; k < got; ++k) {
            mm_an_push(a, &out[k]);
            if (++frames % MM_FPS == 0) { mm_summarize(a, last); }
        }
        pos += chunk;
    }
    printf("FEAT %s lv=%d b=%d,%d,%d,%d bpm=%d tc=%d fl=%d zc=%d zs=%d mo=%d ps=%d on=%d valid=%d\n", name, last->lv,
           last->b[0], last->b[1], last->b[2], last->b[3], last->bpm, last->tc, last->fl, last->zc, last->zs,
           last->mo, last->ps, last->on, last->valid);
    free(a);
}

int main(void)
{
    mm_feat_t f;
    gen_click(120.0f); run("click120", 3000.0f, &f);
    CHECK(f.valid && f.bpm >= 118 && f.bpm <= 122 && f.tc >= 60);
    gen_click(90.0f); run("click90", 3000.0f, &f);
    CHECK(f.valid && f.bpm >= 88 && f.bpm <= 92 && f.tc >= 60);
    gen_click(150.0f); run("click150", 3000.0f, &f);
    CHECK(f.valid && f.bpm >= 147 && f.bpm <= 153 && f.tc >= 60);
    gen_music(120.0f); run("music120", 3000.0f, &f);
    CHECK(f.valid && f.bpm >= 118 && f.bpm <= 122 && f.tc >= 50);
    gen_music(100.0f); run("music100", 2000.0f, &f);
    CHECK(f.valid && f.bpm >= 98 && f.bpm <= 102 && f.tc >= 50);
    gen_sine(); run("sine", 3000.0f, &f);
    CHECK(f.valid && f.tc < 30 && f.ps == 0);
    gen_white(); run("white", 3000.0f, &f);
    CHECK(f.valid && f.tc < 30 && f.fl >= 50);
    gen_am4(); run("am4noise", 3000.0f, &f);
    CHECK(f.valid && f.mo >= 40);
    gen_syllables(); run("syllables", 3000.0f, &f);
    CHECK(f.valid && f.ps >= 10);
    gen_white(); run("quiet", 90.0f, &f);
    CHECK(f.lv < 150);
    {   /* too little history: nothing valid */
        mm_an_t* a = (mm_an_t*)malloc(sizeof(mm_an_t));
        mm_frame_t fr; memset(&fr, 0, sizeof(fr)); fr.n = 480; fr.etot = 1e6f;
        mm_an_reset(a); mm_an_push(a, &fr); mm_summarize(a, &f);
        CHECK(!f.valid);
        free(a);
    }
    if (failures) { printf("%d failed\n", failures); return 1; }
    printf("all passed\n");
    return 0;
}
