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
#define MMJ_SESSION_GAP_MS 60000U
#define MMJ_BREAK_MS 90000U
#define MMJ_BLOCK_USB_MS 300000U
#define MMJ_BLOCK_BATTERY_MS 120000U

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

typedef enum { MMJ_ACTION_NONE, MMJ_ACTION_NOD, MMJ_ACTION_DANCE, MMJ_ACTION_BREAK, MMJ_ACTION_END } mmj_action_t;

/* The unit's own music session (no hub), the same cycles as the host's music_dance.py: the slow start (the nod,
 * then the dance 20 s later), a dance block (5 minutes charging, 2 minutes on battery: mmj_session_set_block_ms),
 * a 90 s break, the dance again, and so on for as long as the music goes on. A gap of 60 s ends the session. No
 * hourly or daily caps. The caller stops the dance on BREAK and END. */
typedef struct {
    uint32_t run_start, last_music, nod_at, block_at, break_at, last_end, block_ms;
    uint8_t state; /* 0 idle, 1 nod and watch, 2 dancing, 3 break */
    uint8_t has_music, has_end;
} mmj_session_t;

static inline uint32_t mmj_elapsed(uint32_t now, uint32_t then) { return now - then; }
static inline void mmj_session_set_block_ms(mmj_session_t *s, uint32_t ms) { s->block_ms = ms; }
static inline void mmj_session_init(mmj_session_t *s) {
    s->run_start = s->last_music = s->nod_at = s->block_at = s->break_at = s->last_end = 0;
    s->block_ms = MMJ_BLOCK_BATTERY_MS;
    s->state = s->has_music = s->has_end = 0;
}
/* Call once per second with this second's verdict. */
static inline mmj_action_t mmj_session_step(mmj_session_t *s, uint32_t now_ms, int music) {
    uint32_t silence;
    if (music) {
        if (!s->has_music || mmj_elapsed(now_ms, s->last_music) > MMJ_GAP_MS) s->run_start = now_ms;
        s->last_music = now_ms;
        s->has_music = 1;
    }
    silence = s->has_music ? mmj_elapsed(now_ms, s->last_music) : 0xFFFFFFFFU;
    switch (s->state) {
    case 0:
        if (music && (!s->has_end || mmj_elapsed(now_ms, s->last_end) >= MMJ_MIN_GAP_MS) &&
            mmj_elapsed(now_ms, s->run_start) >= MMJ_DETECT_MS) {
            s->state = 1; s->nod_at = now_ms;
            return MMJ_ACTION_NOD;
        }
        return MMJ_ACTION_NONE;
    case 1:
        if (silence >= MMJ_END_SILENCE_MS) { s->state = 0; s->last_end = now_ms; s->has_end = 1; return MMJ_ACTION_END; }
        if (music && mmj_elapsed(now_ms, s->nod_at) >= MMJ_NOD_TO_DANCE_MS) {
            s->state = 2; s->block_at = now_ms;
            return MMJ_ACTION_DANCE;
        }
        return MMJ_ACTION_NONE;
    case 2:
        if (silence >= MMJ_SESSION_GAP_MS) { s->state = 0; s->last_end = now_ms; s->has_end = 1; return MMJ_ACTION_END; }
        if (silence >= MMJ_END_SILENCE_MS || mmj_elapsed(now_ms, s->block_at) >= s->block_ms) {
            s->state = 3; s->break_at = now_ms;
            return MMJ_ACTION_BREAK;
        }
        return MMJ_ACTION_NONE;
    default: /* 3: break */
        if (silence >= MMJ_SESSION_GAP_MS) { s->state = 0; s->last_end = now_ms; s->has_end = 1; return MMJ_ACTION_END; }
        if (music && mmj_elapsed(now_ms, s->break_at) >= MMJ_BREAK_MS) {
            s->state = 2; s->block_at = now_ms;
            return MMJ_ACTION_DANCE;
        }
        return MMJ_ACTION_NONE;
    }
}

#endif
