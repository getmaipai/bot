#ifndef MAIPAI_MUSIC_JUDGE_H
#define MAIPAI_MUSIC_JUDGE_H

#include <stdint.h>

#define MMJ_MIN_LEVEL 400
#define MMJ_MIN_BPM 60
#define MMJ_MAX_BPM 187
#define MMJ_STEADY_TC_MIN 8
#define MMJ_STEADY_LEVEL 800
#define MMJ_STEADY_MO_MAX 32
#define MMJ_STEADY_PS_MAX 20
#define MMJ_STEADY_FL_MAX 97
#define MMJ_DETECT_MS 4000U
#define MMJ_GAP_MS 2500U
#define MMJ_NOD_TO_DANCE_MS 20000U
#define MMJ_END_SILENCE_MS 9000U
#define MMJ_MIN_GAP_MS 120000U
#define MMJ_MAX_PER_HOUR 6
#define MMJ_MAX_PER_DAY 10

typedef struct {
    int lv, bpm, tc, fl, mo, ps;
    int muted;
} mmj_feat_t;

typedef enum { MMJ_SENS_LOW, MMJ_SENS_MEDIUM, MMJ_SENS_HIGH } mmj_sens_t;
typedef enum {
    MMJ_BELOW_LEVEL_GATE,
    MMJ_WEAK_BEAT,
    MMJ_NO_TEMPO,
    MMJ_TEMPO_OUT_OF_RANGE,
    MMJ_TOO_FLAT,
    MMJ_SPEECH_LIKE_MODULATION,
    MMJ_SPEECH_LIKE_PAUSES,
    MMJ_SELF_HEARING_BLANK,
    MMJ_MUSIC
} mmj_reason_t;

typedef struct { int music; mmj_reason_t reason; } mmj_verdict_t;

typedef struct { int tc_min, mo_max, ps_max, ps_tc_free, fl_max; } mmj_sensitivity_t;
static const mmj_sensitivity_t MMJ_SENSITIVITIES[] = {
    {40, 40, 40, 50, 88}, {20, 45, 40, 50, 88}, {14, 55, 40, 50, 88}
};

static inline int mmj_steady(const mmj_feat_t *f) {
    return f->lv >= MMJ_STEADY_LEVEL && f->bpm > 0 && f->tc >= MMJ_STEADY_TC_MIN &&
           f->mo < MMJ_STEADY_MO_MAX && f->ps < MMJ_STEADY_PS_MAX && f->fl < MMJ_STEADY_FL_MAX;
}

static inline mmj_verdict_t mmj_make(int yes, mmj_reason_t why) {
    mmj_verdict_t v = {yes, why}; return v;
}

static inline mmj_verdict_t mmj_judge(const mmj_feat_t *f, mmj_sens_t sensitivity, int relaxed) {
    mmj_sensitivity_t s;
    int tc_min, mo_max, ps_max, fl_max;
    if (sensitivity < MMJ_SENS_LOW || sensitivity > MMJ_SENS_HIGH) sensitivity = MMJ_SENS_MEDIUM;
    s = MMJ_SENSITIVITIES[sensitivity];
    tc_min = s.tc_min; mo_max = s.mo_max; ps_max = s.ps_max; fl_max = s.fl_max;
    if (relaxed) { tc_min = tc_min / 2; if (tc_min < 8) tc_min = 8; fl_max += 10; mo_max += 10; ps_max += 10; }
    if (f->muted) return mmj_make(0, MMJ_SELF_HEARING_BLANK);
    if (f->lv < MMJ_MIN_LEVEL) return mmj_make(0, MMJ_BELOW_LEVEL_GATE);
    if (sensitivity != MMJ_SENS_LOW && mmj_steady(f)) return mmj_make(1, MMJ_MUSIC);
    if (f->tc < tc_min) return mmj_make(0, MMJ_WEAK_BEAT);
    if (f->bpm == 0) return mmj_make(0, MMJ_NO_TEMPO);
    if (f->bpm < MMJ_MIN_BPM || f->bpm > MMJ_MAX_BPM) return mmj_make(0, MMJ_TEMPO_OUT_OF_RANGE);
    if (f->fl >= fl_max) return mmj_make(0, MMJ_TOO_FLAT);
    if (f->mo >= mo_max) return mmj_make(0, MMJ_SPEECH_LIKE_MODULATION);
    if (f->ps >= ps_max && f->tc < s.ps_tc_free) return mmj_make(0, MMJ_SPEECH_LIKE_PAUSES);
    return mmj_make(1, MMJ_MUSIC);
}

typedef enum { MMJ_ACTION_NONE, MMJ_ACTION_NOD, MMJ_ACTION_DANCE, MMJ_ACTION_END } mmj_action_t;
typedef struct {
    uint32_t run_start, last_music, nod_at, last_nod, last_dance_end;
    uint32_t starts[MMJ_MAX_PER_DAY];
    uint8_t start_count;
    uint8_t state; /* 0 idle, 1 nod/watch, 2 dancing */
    uint8_t nod_sent, dance_sent, has_music, has_nod, has_dance_end;
} mmj_session_t;

static inline uint32_t mmj_elapsed(uint32_t now, uint32_t then) { return now - then; }
static inline void mmj_session_init(mmj_session_t *s) {
    unsigned i; s->run_start = s->last_music = s->nod_at = s->last_nod = s->last_dance_end = 0;
    s->start_count = s->state = s->nod_sent = s->dance_sent = 0;
    s->has_music = s->has_nod = s->has_dance_end = 0;
    for (i = 0; i < MMJ_MAX_PER_DAY; ++i) s->starts[i] = 0;
}
/* Call once per second; action is emitted once per stage. A nod begins after 4 s of positives. */
static inline mmj_action_t mmj_session_step(mmj_session_t *s, uint32_t now_ms, int music) {
    unsigned i, kept = 0, hourly = 0;
    int have_last = s->has_music;
    if (s->start_count) {
        for (i = 0; i < s->start_count; ++i) {
            if (mmj_elapsed(now_ms, s->starts[i]) < 86400000U) {
                s->starts[kept++] = s->starts[i];
                if (mmj_elapsed(now_ms, s->starts[i]) < 3600000U) hourly++;
            }
        }
        s->start_count = (uint8_t)kept;
    }
    if (music) {
        if (!have_last || mmj_elapsed(now_ms, s->last_music) > MMJ_GAP_MS) {
            s->run_start = now_ms;
            s->nod_sent = 0;
        }
        s->last_music = now_ms;
        s->has_music = 1;
    }
    if (s->state == 2) {
        if (!music && mmj_elapsed(now_ms, s->last_music) >= MMJ_END_SILENCE_MS) { s->state = 0; s->last_dance_end = now_ms; s->has_dance_end = 1; return MMJ_ACTION_END; }
        return MMJ_ACTION_NONE;
    }
    if (s->state == 1) {
        if (music && !s->dance_sent && mmj_elapsed(now_ms, s->nod_at) >= MMJ_NOD_TO_DANCE_MS) {
            if (s->start_count < MMJ_MAX_PER_DAY && hourly < MMJ_MAX_PER_HOUR) {
                s->state = 2; s->dance_sent = 1; s->starts[s->start_count++] = now_ms;
                return MMJ_ACTION_DANCE;
            }
        }
        if (!music && have_last && mmj_elapsed(now_ms, s->last_music) >= MMJ_END_SILENCE_MS) { s->state = 0; return MMJ_ACTION_END; }
        return MMJ_ACTION_NONE;
    }
    if (music && !s->nod_sent && (!s->has_dance_end || mmj_elapsed(now_ms, s->last_dance_end) >= MMJ_MIN_GAP_MS) &&
        (!s->has_nod || mmj_elapsed(now_ms, s->last_nod) >= MMJ_MIN_GAP_MS) &&
        s->start_count < MMJ_MAX_PER_DAY && hourly < MMJ_MAX_PER_HOUR &&
        mmj_elapsed(now_ms, s->run_start) >= MMJ_DETECT_MS) {
        s->state = 1; s->nod_sent = 1; s->nod_at = now_ms; s->last_nod = now_ms; s->has_nod = 1; s->dance_sent = 0;
        return MMJ_ACTION_NOD;
    }
    return MMJ_ACTION_NONE;
}

#endif
