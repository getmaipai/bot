#ifndef MAIPAI_BEAT_H
#define MAIPAI_BEAT_H

/* The beat of a song, from the onset signal the unit already measures (maipai_music_core.h): plain C99, no
 * hardware. mb_fold_bpm folds the autocorrelation's tempo (often a half or a double) into 70 to 140 BPM;
 * mb_phase finds where the beats fall in the last few seconds of the onset signal; mb_next_beat_ms says when
 * the next one comes. The dance sways on those times and follows the tempo. */

#include <stdint.h>

#define MB_MAX_FRAMES 512
#define MB_MAX_PERIOD_FRAMES 64

typedef struct {
    int confidence;       /* 0..100: how much better the best phase is than an average one */
    int last_beat_ms_ago; /* from the newest frame back to the latest beat */
    int period_ms;        /* one beat, after folding */
} mb_beat_t;

static inline int mb_fold_bpm(int bpm) {
    if (bpm <= 0) return 0;
    while (bpm < 70) bpm *= 2;
    while (bpm > 140) bpm = (bpm + 1) / 2;
    return bpm;
}

/* onset_oldest_first: n_frames values, one per frame_ms. Returns the confidence (0 when there is no usable
 * beat). Recent beats weigh more, so a tempo that is a few percent off still lands the newest beat. */
static inline int mb_phase(const int16_t *onset_oldest_first, int n_frames, int frame_ms, int bpm,
                           mb_beat_t *out) {
    int folded, period_ms, period_frames, offset, i, median = 0, best_offset = 0, last_idx;
    int16_t sorted[MB_MAX_FRAMES];
    int64_t total = 0, best = -1;
    if (out == 0) return 0;
    out->confidence = 0;
    out->last_beat_ms_ago = 0;
    out->period_ms = 0;
    if (onset_oldest_first == 0 || n_frames <= 0 || frame_ms <= 0 || bpm <= 0) return 0;
    folded = mb_fold_bpm(bpm);
    period_ms = 60000 / folded;
    period_frames = (period_ms + frame_ms / 2) / frame_ms;
    if (period_frames < 2 || period_frames > MB_MAX_PERIOD_FRAMES) return 0;
    if (n_frames > MB_MAX_FRAMES) {
        onset_oldest_first += n_frames - MB_MAX_FRAMES; /* keep the newest */
        n_frames = MB_MAX_FRAMES;
    }
    if (n_frames < 2 * period_frames) return 0;
    for (i = 0; i < n_frames; i++) sorted[i] = onset_oldest_first[i];
    for (i = 1; i < n_frames; i++) { /* insertion sort, n is at most 512 */
        int16_t v = sorted[i];
        int j;
        for (j = i; j > 0 && sorted[j - 1] > v; j--) sorted[j] = sorted[j - 1];
        sorted[j] = v;
    }
    median = sorted[n_frames / 2];
    for (offset = 0; offset < period_frames; offset++) {
        int64_t score = 0;
        for (i = offset; i < n_frames; i += period_frames) {
            int k, v = 0;
            for (k = -1; k <= 1; k++) { /* one frame of jitter either side */
                int at = i + k;
                if (at >= 0 && at < n_frames && onset_oldest_first[at] - median > v)
                    v = onset_oldest_first[at] - median;
            }
            score += (int64_t)v * (n_frames + 3 * i); /* newer beats weigh up to four times more */
        }
        total += score;
        if (score > best) { best = score; best_offset = offset; }
    }
    if (best <= 0) return 0;
    {
        int64_t mean = total / period_frames;
        int confidence = (int)(((best - mean) * 100) / best);
        if (confidence < 0) confidence = 0;
        if (confidence > 100) confidence = 100;
        out->confidence = confidence;
    }
    last_idx = best_offset + ((n_frames - 1 - best_offset) / period_frames) * period_frames;
    out->period_ms = period_ms;
    out->last_beat_ms_ago = (n_frames - 1 - last_idx) * frame_ms;
    return out->confidence;
}

/* The next beat on the caller's clock: the first beat time after now_ms, advancing by whole periods from the
 * moment the phase was computed (computed_at_ms). Wrap safe. */
static inline uint32_t mb_next_beat_ms(const mb_beat_t *b, uint32_t now_ms, uint32_t computed_at_ms) {
    uint32_t elapsed, since, period, wait;
    if (b == 0 || b->period_ms <= 0) return now_ms;
    period = (uint32_t)b->period_ms;
    elapsed = now_ms - computed_at_ms;
    since = (uint32_t)b->last_beat_ms_ago + elapsed;
    wait = period - (since % period);
    return now_ms + wait;
}

#endif
