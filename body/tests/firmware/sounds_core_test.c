/* Host test for the unit's sound logic (patch 115): cc -std=c99 -Wall -Werror -I<dir with the header>. */
#include <stdio.h>
#include <stdlib.h>
#include "maipai_sounds_core.h"

static int failures;
#define CHECK(cond)                                                      \
    do {                                                                 \
        if (!(cond)) {                                                   \
            printf("FAIL line %d: %s\n", __LINE__, #cond);               \
            failures++;                                                  \
        }                                                                \
    } while (0)

static void test_names(void)
{
    CHECK(ms_sound_from_name("needs_you") == MS_SND_NEEDS_YOU);
    CHECK(ms_sound_from_name("low_battery") == MS_SND_LOW_BATTERY);
    CHECK(ms_sound_from_name("shutter") == MS_SND_SHUTTER);
    CHECK(ms_sound_from_name("nope") == -1);
    CHECK(ms_sound_from_name("") == -1);
    CHECK(ms_sound_from_name(NULL) == -1);
    for (int i = 0; i < MS_SND_COUNT; i++) {
        CHECK(ms_sound_from_name(MS_SOUND_NAMES[i]) == i);
    }
    CHECK(ms_sound_is_asset(MS_SND_SHUTTER) && !ms_sound_is_asset(MS_SND_SUCCESS));
}

static void test_quiet_window(void)
{
    CHECK(ms_in_window(22 * 60, 7 * 60, 23 * 60));  /* wraps midnight */
    CHECK(ms_in_window(22 * 60, 7 * 60, 3 * 60));
    CHECK(!ms_in_window(22 * 60, 7 * 60, 12 * 60));
    CHECK(!ms_in_window(22 * 60, 7 * 60, 7 * 60));  /* the end is open */
    CHECK(ms_in_window(22 * 60, 7 * 60, 22 * 60));  /* the start is closed */
    CHECK(ms_in_window(1 * 60, 5 * 60, 2 * 60));    /* a plain window */
    CHECK(!ms_in_window(1 * 60, 5 * 60, 6 * 60));
    CHECK(!ms_in_window(600, 600, 600));            /* empty */
    CHECK(!ms_in_window(-1, -1, 100));              /* none set */
    CHECK(!ms_in_window(22 * 60, 7 * 60, -1));      /* the clock is not set: unknown is not night */
    ms_policy_t p; ms_policy_default(&p);
    CHECK(!ms_is_night(&p, 3 * 60, 1));             /* no hours set */
    p.quiet_from = 22 * 60; p.quiet_to = 7 * 60;
    CHECK(ms_is_night(&p, 23 * 60, 0));
    CHECK(!ms_is_night(&p, 12 * 60, 0));
    p.dark = 1;
    CHECK(ms_is_night(&p, 12 * 60, 1));             /* the sensor night counts while the host is up */
    CHECK(!ms_is_night(&p, 12 * 60, 0));            /* and is not trusted with the host down */
}

static void test_gate(void)
{
    ms_policy_t p; ms_policy_default(&p);
    CHECK(ms_decide(&p, MS_SND_PLUG_IN, 0, 0, 0) == MS_OK);
    CHECK(ms_decide(&p, -1, 0, 0, 0) == MS_NO_SUCH_SOUND);
    CHECK(ms_decide(&p, MS_SND_COUNT, 0, 0, 0) == MS_NO_SUCH_SOUND);
    /* night: only the privacy and safety cues */
    CHECK(ms_decide(&p, MS_SND_PLUG_IN, 0, 1, 0) == MS_NIGHT);
    CHECK(ms_decide(&p, MS_SND_CHARGED, 0, 1, 0) == MS_NIGHT);
    CHECK(ms_decide(&p, MS_SND_UNPLUG, 0, 1, 0) == MS_NIGHT);
    CHECK(ms_decide(&p, MS_SND_OFFLINE, 0, 1, 0) == MS_NIGHT);
    CHECK(ms_decide(&p, MS_SND_SUCCESS, 0, 1, 0) == MS_NIGHT);
    CHECK(ms_decide(&p, MS_SND_SHUTTER, 0, 1, 0) == MS_OK);
    CHECK(ms_decide(&p, MS_SND_GOODBYE, 0, 1, 0) == MS_OK);
    CHECK(ms_decide(&p, MS_SND_LOW_BATTERY, 0, 1, 0) == MS_OK);
    CHECK(ms_decide(&p, MS_SND_EXCLAMATION, 0, 1, 0) == MS_OK);
    CHECK(ms_decide(&p, MS_SND_POPUP, 0, 1, 0) == MS_OK);
    CHECK(ms_decide(&p, MS_SND_NEEDS_YOU, 0, 1, 0) == MS_NIGHT); /* waiting for approval: day only */
    CHECK(ms_decide(&p, MS_SND_NEEDS_YOU, 1, 1, 0) == MS_OK);    /* first setup: the unit cannot work */
    /* robot.sounds.night on: the night rule goes away */
    p.night_ok = 1;
    CHECK(ms_decide(&p, MS_SND_PLUG_IN, 0, 1, 0) == MS_OK);
    p.night_ok = 0;
    /* sounds off: only a picture and the first-setup cue remain */
    p.enabled = 0;
    CHECK(ms_decide(&p, MS_SND_PLUG_IN, 0, 0, 0) == MS_DISABLED);
    CHECK(ms_decide(&p, MS_SND_LOW_BATTERY, 0, 0, 0) == MS_DISABLED);
    CHECK(ms_decide(&p, MS_SND_SHUTTER, 0, 0, 0) == MS_OK);
    CHECK(ms_decide(&p, MS_SND_NEEDS_YOU, 1, 0, 0) == MS_OK);
    CHECK(ms_decide(&p, MS_SND_NEEDS_YOU, 0, 0, 0) == MS_DISABLED);
    p.enabled = 1;
    /* the hard mute silences everything, a picture too, and the self-test cannot override it */
    p.muted = 1;
    CHECK(ms_decide(&p, MS_SND_SHUTTER, 0, 0, 0) == MS_MUTED);
    CHECK(ms_decide(&p, MS_SND_GOODBYE, 0, 1, 0) == MS_MUTED);
    CHECK(ms_decide(&p, MS_SND_PLUG_IN, 0, 0, 1) == MS_MUTED);
    p.muted = 0;
    /* the self-test skips "off" and the night rule */
    p.enabled = 0;
    CHECK(ms_decide(&p, MS_SND_PLUG_IN, 0, 1, 1) == MS_OK);
    CHECK(strcmp(ms_reason_word(MS_MUTED), "muted") == 0);
    CHECK(strcmp(ms_reason_word(MS_NIGHT), "night") == 0);
}

static void feed(ms_power_t* p, int ext, int chg, int n, ms_power_event_t* first)
{
    *first = MS_PWR_NONE;
    for (int i = 0; i < n; i++) {
        ms_power_event_t e = ms_power_update(p, ext, chg);
        if (e != MS_PWR_NONE && *first == MS_PWR_NONE) {
            *first = e;
        }
    }
}

static void test_charger(void)
{
    ms_power_t p; ms_power_init(&p);
    ms_power_event_t e;
    feed(&p, 0, 0, 1, &e);
    CHECK(e == MS_PWR_NONE);                       /* the first poll only learns */
    feed(&p, 1, 1, MS_PWR_CONFIRM - 1, &e);
    CHECK(e == MS_PWR_NONE);                       /* not confirmed yet */
    feed(&p, 1, 1, 1, &e);
    CHECK(e == MS_PWR_PLUG);
    feed(&p, 1, 1, 10, &e);
    CHECK(e == MS_PWR_NONE);                       /* once only */
    feed(&p, 1, 0, MS_PWR_CONFIRM, &e);
    CHECK(e == MS_PWR_FULL);                       /* charging stopped with the cable still in */
    feed(&p, 1, 0, 10, &e);
    CHECK(e == MS_PWR_NONE);                       /* and only once */
    feed(&p, 0, 0, MS_PWR_CONFIRM, &e);
    CHECK(e == MS_PWR_UNPLUG);
    /* a flapping read never chimes */
    ms_power_init(&p);
    feed(&p, 0, 0, 1, &e);
    for (int i = 0; i < 20; i++) {
        CHECK(ms_power_update(&p, i % 2, i % 2) == MS_PWR_NONE);
    }
    /* a cable plugged into a full battery: plug, but never "charged" */
    ms_power_init(&p);
    feed(&p, 0, 0, 1, &e);
    feed(&p, 1, 0, MS_PWR_CONFIRM, &e);
    CHECK(e == MS_PWR_PLUG);
    feed(&p, 1, 0, 10, &e);
    CHECK(e == MS_PWR_NONE);
    /* booting on a cable: silence, then full after charging */
    ms_power_init(&p);
    feed(&p, 1, 1, 1, &e);
    CHECK(e == MS_PWR_NONE);
    feed(&p, 1, 0, MS_PWR_CONFIRM, &e);
    CHECK(e == MS_PWR_FULL);
    /* unplugged while charging: unplug, no "full" afterwards */
    ms_power_init(&p);
    feed(&p, 1, 1, 1, &e);
    feed(&p, 0, 0, MS_PWR_CONFIRM, &e);
    CHECK(e == MS_PWR_UNPLUG);
    feed(&p, 0, 0, 10, &e);
    CHECK(e == MS_PWR_NONE);
}

static void test_link(void)
{
    ms_link_t l; ms_link_init(&l);
    const uint32_t T = 4000000000u; /* near the 32-bit wrap */
    CHECK(ms_link_state(&l, T, 1, 1) == MS_LINK_UP);
    CHECK(ms_link_state(&l, T, 0, 0) == MS_LINK_NO_WIFI);
    ms_link_down(&l, T);
    CHECK(ms_link_state(&l, T + 3000, 1, 0) == MS_LINK_CONNECTING);
    CHECK(ms_link_state(&l, T + 10000, 1, 0) == MS_LINK_NO_HOST);
    ms_link_mark_offline(&l);
    ms_link_down(&l, T + 15000);                      /* a second down while down changes nothing */
    CHECK(l.down_since_ms == T);
    ms_link_hello_failed(&l);
    CHECK(ms_link_state(&l, T + 20000, 1, 0) == MS_LINK_NO_HOST);
    ms_link_hello_failed(&l);
    CHECK(ms_link_state(&l, T + 20000, 1, 0) == MS_LINK_REFUSED);
    CHECK(ms_link_state(&l, T + 20000, 0, 0) == MS_LINK_NO_WIFI); /* no Wi-Fi outranks it */
    /* back after 70 s (the clock wraps in the middle): the chime and the clip */
    ms_link_return_t r = ms_link_up(&l, T + 70000u);
    CHECK(r.back_online && r.back_clip && r.outage_ms == 70000u);
    CHECK(l.hello_fails == 0 && !l.down);
    /* back after 30 s: the chime only */
    ms_link_down(&l, 1000);
    ms_link_mark_offline(&l);
    r = ms_link_up(&l, 31000);
    CHECK(r.back_online && !r.back_clip);
    /* a blip: nothing */
    ms_link_down(&l, 50000);
    r = ms_link_up(&l, 53000);
    CHECK(!r.back_online && !r.back_clip && r.outage_ms == 3000);
    /* up without ever being down */
    r = ms_link_up(&l, 60000);
    CHECK(!r.back_online && r.outage_ms == 0);
}

static void test_groups_and_files(void)
{
    int total = 0;
    for (int g = 0; g < MS_GRP_COUNT; g++) {
        total += MS_GROUP_SIZE[g];
    }
    CHECK(total == 16);
    CHECK(ms_group_for_link(MS_LINK_NO_WIFI) == MS_GRP_NO_WIFI);
    CHECK(ms_group_for_link(MS_LINK_CONNECTING) == MS_GRP_CONNECTING);
    CHECK(ms_group_for_link(MS_LINK_NO_HOST) == MS_GRP_NO_HOST);
    CHECK(ms_group_for_link(MS_LINK_REFUSED) == MS_GRP_REFUSED);
    CHECK(ms_group_for_link(MS_LINK_UP) == -1);
    char name[40];
    CHECK(ms_phrase_file(name, sizeof(name), MS_GRP_NO_HOST, 3) && strcmp(name, "ph_no_host_4.ogg") == 0);
    CHECK(ms_phrase_file(name, sizeof(name), MS_GRP_BACK, 0) && strcmp(name, "ph_back_1.ogg") == 0);
    CHECK(!ms_phrase_file(name, sizeof(name), MS_GRP_BACK, 2));
    CHECK(!ms_phrase_file(name, sizeof(name), 9, 0));
    CHECK(!ms_phrase_file(name, sizeof(name), -1, 0));
}

static void test_phrases_cycle_and_limit(void)
{
    ms_phrases_t ph; ms_phrases_init(&ph);
    uint32_t t = 100000;
    /* the no_host group has four phrases: a round robin, never the same twice in a row */
    int last = -1;
    int seen[4] = {0, 0, 0, 0};
    for (int i = 0; i < 8; i++) {
        ms_phrase_t p = ms_phrase_pick(&ph, MS_LINK_NO_HOST, t, 0, 0, -1);
        CHECK(p.kind == MS_PH_CLIP && p.group == MS_GRP_NO_HOST);
        CHECK(p.variant != last);
        seen[p.variant]++;
        last = p.variant;
        t += 61000; /* a minute apart: never limited */
    }
    CHECK(seen[0] == 2 && seen[1] == 2 && seen[2] == 2 && seen[3] == 2);

    /* one per 10 s */
    ms_phrases_init(&ph);
    t = 5000;
    CHECK(ms_phrase_pick(&ph, MS_LINK_NO_WIFI, t, 0, 0, -1).kind == MS_PH_CLIP);
    CHECK(ms_phrase_pick(&ph, MS_LINK_NO_WIFI, t + 9999, 0, 0, -1).kind == MS_PH_TONE);
    CHECK(ms_phrase_pick(&ph, MS_LINK_NO_WIFI, t + 10000, 0, 0, -1).kind == MS_PH_CLIP);
    /* the tone did not use up the limit, and did not advance the cycle */
    /* three a minute: clips at 0, 10, 20 s, then the tone until 60 s after the first */
    ms_phrases_init(&ph);
    t = 1000;
    CHECK(ms_phrase_pick(&ph, MS_LINK_NO_HOST, t, 0, 0, -1).kind == MS_PH_CLIP);
    CHECK(ms_phrase_pick(&ph, MS_LINK_NO_HOST, t + 10000, 0, 0, -1).kind == MS_PH_CLIP);
    CHECK(ms_phrase_pick(&ph, MS_LINK_NO_HOST, t + 20000, 0, 0, -1).kind == MS_PH_CLIP);
    CHECK(ms_phrase_pick(&ph, MS_LINK_NO_HOST, t + 30000, 0, 0, -1).kind == MS_PH_TONE);
    CHECK(ms_phrase_pick(&ph, MS_LINK_NO_HOST, t + 59999, 0, 0, -1).kind == MS_PH_TONE);
    CHECK(ms_phrase_pick(&ph, MS_LINK_NO_HOST, t + 60000, 0, 0, -1).kind == MS_PH_CLIP);
    /* and again the next window holds only what is recent */
    CHECK(ms_phrase_pick(&ph, MS_LINK_NO_HOST, t + 70000, 0, 0, -1).kind == MS_PH_CLIP);
    CHECK(ms_phrase_pick(&ph, MS_LINK_NO_HOST, t + 80000, 0, 0, -1).kind == MS_PH_CLIP);
    CHECK(ms_phrase_pick(&ph, MS_LINK_NO_HOST, t + 90000, 0, 0, -1).kind == MS_PH_TONE);
}

static void test_phrases_night_mute_state(void)
{
    ms_phrases_t ph; ms_phrases_init(&ph);
    /* night: the tone only, and the limit is untouched */
    ms_phrase_t p = ms_phrase_pick(&ph, MS_LINK_NO_HOST, 1000, 1, 0, -1);
    CHECK(p.kind == MS_PH_TONE && ph.played == 0);
    /* muted: nothing at all */
    p = ms_phrase_pick(&ph, MS_LINK_NO_HOST, 1000, 0, 1, -1);
    CHECK(p.kind == MS_PH_NONE);
    /* the link is up: nothing to say */
    p = ms_phrase_pick(&ph, MS_LINK_UP, 1000, 0, 0, -1);
    CHECK(p.kind == MS_PH_NONE);
    /* each state maps to its own group */
    p = ms_phrase_pick(&ph, MS_LINK_NO_WIFI, 100000, 0, 0, -1);
    CHECK(p.kind == MS_PH_CLIP && p.group == MS_GRP_NO_WIFI);
    p = ms_phrase_pick(&ph, MS_LINK_REFUSED, 200000, 0, 0, -1);
    CHECK(p.kind == MS_PH_CLIP && p.group == MS_GRP_REFUSED);
    p = ms_phrase_pick(&ph, MS_LINK_CONNECTING, 300000, 0, 0, -1);
    CHECK(p.kind == MS_PH_CLIP && p.group == MS_GRP_CONNECTING);
    /* "I'm back" is asked for by group, whatever the state */
    p = ms_phrase_pick(&ph, MS_LINK_UP, 400000, 0, 0, MS_GRP_BACK);
    CHECK(p.kind == MS_PH_CLIP && p.group == MS_GRP_BACK);
    p = ms_phrase_pick(&ph, MS_LINK_UP, 500000, 0, 0, MS_GRP_BACK);
    CHECK(p.kind == MS_PH_CLIP && p.group == MS_GRP_BACK && p.variant == 1); /* the other of the two */
    /* every clip has a file name inside the asset name limit */
    char name[40];
    for (int g = 0; g < MS_GRP_COUNT; g++) {
        for (int v = 0; v < MS_GROUP_SIZE[g]; v++) {
            CHECK(ms_phrase_file(name, sizeof(name), g, v));
            CHECK(strlen(name) < 32);
        }
    }
}

int main(void)
{
    test_names();
    test_quiet_window();
    test_gate();
    test_charger();
    test_link();
    test_groups_and_files();
    test_phrases_cycle_and_limit();
    test_phrases_night_mute_state();
    if (failures != 0) {
        printf("%d check(s) failed\n", failures);
        return 1;
    }
    printf("all passed\n");
    return 0;
}
