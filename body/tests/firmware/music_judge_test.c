#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "maipai_music_judge.h"

static const char *names[] = {"below_level_gate", "weak_beat", "no_tempo", "tempo_out_of_range", "too_flat", "speech_like_modulation", "speech_like_pauses", "self_hearing_blank", "music"};
static int failures;
#define CHECK(x) do { if (!(x)) { printf("FAIL line %d: %s\n", __LINE__, #x); failures++; } } while (0)

int main(int argc, char **argv) {
    FILE *fp;
    int lv,bpm,tc,fl,mo,ps,muted,sens,relaxed,expect,reason;
    if (argc != 2 || !(fp = fopen(argv[1], "r"))) return 2;
    while (fscanf(fp, "%d %d %d %d %d %d %d %d %d %d", &lv,&bpm,&tc,&fl,&mo,&ps,&muted,&sens,&relaxed,&expect) == 10) {
        char gotname[64]; mmj_feat_t f = {lv,bpm,tc,fl,mo,ps,muted};
        mmj_verdict_t v = mmj_judge(&f, (mmj_sens_t)sens, relaxed);
        reason = (int)v.reason;
        if (fscanf(fp, "%63s", gotname) != 1) { failures++; break; }
        CHECK(v.music == expect);
        CHECK(reason >= 0 && reason <= MMJ_MUSIC);
        CHECK(strcmp(names[reason], gotname) == 0);
    }
    fclose(fp);
    {
        mmj_session_t s; mmj_session_init(&s);
        CHECK(mmj_session_step(&s, 1000, 1) == MMJ_ACTION_NONE);
        CHECK(mmj_session_step(&s, 2000, 1) == MMJ_ACTION_NONE);
        CHECK(mmj_session_step(&s, 3000, 1) == MMJ_ACTION_NONE);
        CHECK(mmj_session_step(&s, 4000, 1) == MMJ_ACTION_NONE);
        CHECK(mmj_session_step(&s, 5000, 1) == MMJ_ACTION_NOD);
        CHECK(mmj_session_step(&s, 25000, 1) == MMJ_ACTION_DANCE);
        CHECK(mmj_session_step(&s, 33999, 0) == MMJ_ACTION_NONE);
        CHECK(mmj_session_step(&s, 34000, 0) == MMJ_ACTION_END);
    }
    if (failures) { printf("%d failure(s)\n", failures); return 1; }
    printf("all passed\n"); return 0;
}
