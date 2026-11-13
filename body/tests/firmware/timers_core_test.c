/* Host test for the on-unit timer core (patch 090): cc -std=c99 -Wall -Werror -I<dir with the header>. */
#include <stdio.h>
#include <stdlib.h>
#include "maipai_timers_core.h"

static int failures;
#define CHECK(cond)                                                      \
    do {                                                                 \
        if (!(cond)) {                                                   \
            printf("FAIL line %d: %s\n", __LINE__, #cond);               \
            failures++;                                                  \
        }                                                                \
    } while (0)

#define T0 1800000000u /* a valid clock */

static void test_timer_fires_once(void)
{
    mt_state_t st; mt_init(&st);
    mt_fired_t f[4]; int dropped;
    int id = mt_add_timer(&st, T0, 100, 60, "tea", 0);
    CHECK(id == 1);
    CHECK(mt_tick(&st, T0 + 59, 159, f, 4, &dropped) == 0);
    CHECK(mt_tick(&st, T0 + 60, 160, f, 4, &dropped) == 1);
    CHECK(f[0].id == 1 && f[0].kind == MT_KIND_TIMER && !f[0].late && strcmp(f[0].label, "tea") == 0);
    CHECK(mt_tick(&st, T0 + 61, 161, f, 4, &dropped) == 0);
    CHECK(mt_count(&st) == 0);
}

static void test_limits(void)
{
    mt_state_t st; mt_init(&st);
    CHECK(mt_add_timer(&st, T0, 0, 0, "", 0) == MT_ERR_ARGUMENT);
    CHECK(mt_add_timer(&st, T0, 0, 86401, "", 0) == MT_ERR_TOO_LONG);
    CHECK(mt_add_timer(&st, T0, 0, 86400, "", 0) > 0);
    for (int i = 0; i < 7; i++) CHECK(mt_add_timer(&st, T0, 0, 10, "", 0) > 0);
    CHECK(mt_count(&st) == 8);
    CHECK(mt_add_timer(&st, T0, 0, 10, "", 0) == MT_ERR_FULL);
    CHECK(mt_cancel(&st, 3) == MT_OK);
    CHECK(mt_cancel(&st, 3) == MT_ERR_NOT_FOUND);
    CHECK(mt_add_timer(&st, T0, 0, 10, "", 0) > 0);
    CHECK(mt_cancel_all(&st) == 8);
}

static void test_label_is_clean(void)
{
    mt_state_t st; mt_init(&st);
    mt_add_timer(&st, T0, 0, 5, "a\"b\\c<d>\nTea time, ok", 0);
    CHECK(strcmp(st.e[0].label, "abcdTea time, ok") == 0);
    mt_add_timer(&st, T0, 0, 5, "123456789012345678901234567890", 0);
    CHECK(strlen(st.e[1].label) == MT_LABEL_MAX);
}

static void test_alarm_next_occurrence(void)
{
    mt_state_t st; mt_init(&st);
    /* 07:00:00 local now; alarm at 07:30 is in 30 minutes, 06:30 is in 23.5 hours, 07:00 is in a day */
    CHECK(mt_add_alarm(&st, T0, 7 * 3600, 7, 30, "", 0) > 0);
    CHECK(st.e[0].due == T0 + 1800);
    CHECK(mt_add_alarm(&st, T0, 7 * 3600, 6, 30, "", 0) > 0);
    CHECK(st.e[1].due == T0 + 84600);
    CHECK(mt_add_alarm(&st, T0, 7 * 3600, 7, 0, "", 0) > 0);
    CHECK(st.e[2].due == T0 + 86400);
    CHECK(mt_add_alarm(&st, T0, 0, 24, 0, "", 0) == MT_ERR_ARGUMENT);
    CHECK(mt_add_alarm(&st, T0, 0, 7, 60, "", 0) == MT_ERR_ARGUMENT);
    CHECK(mt_add_alarm(&st, 5, 0, 7, 0, "", 0) == MT_ERR_NO_CLOCK);
}

static void test_no_clock_timer_runs_on_boot_time_and_is_not_saved(void)
{
    mt_state_t st; mt_init(&st);
    mt_fired_t f[2]; int dropped;
    CHECK(mt_add_timer(&st, 0, 1000, 30, "x", 0) > 0);
    CHECK(mt_add_timer(&st, T0, 1000, 30, "kept", 0) > 0);
    CHECK(mt_tick(&st, 0, 1029, f, 2, &dropped) == 0);
    uint8_t buf[MT_BLOB_MAX];
    size_t n = mt_save(&st, buf, sizeof(buf));
    mt_state_t back;
    CHECK(mt_load(&back, buf, n) == MT_OK);
    CHECK(mt_count(&back) == 1 && strcmp(back.e[0].label, "kept") == 0);
    CHECK(mt_tick(&st, 0, 1030, f, 2, &dropped) == 1 && strcmp(f[0].label, "x") == 0);
}

static void test_survives_reboot(void)
{
    mt_state_t st; mt_init(&st);
    mt_add_timer(&st, T0, 50, 600, "pasta", 1);
    mt_add_alarm(&st, T0, 3600, 2, 0, "wake", 0);
    uint8_t buf[MT_BLOB_MAX];
    size_t n = mt_save(&st, buf, sizeof(buf));
    CHECK(n > 0 && n <= sizeof(buf));
    mt_state_t back;
    CHECK(mt_load(&back, buf, n) == MT_OK);
    CHECK(mt_count(&back) == 2);
    CHECK(back.next_id == st.next_id);
    mt_fired_t f[4]; int dropped;
    /* the unit was off for 500 s: not due yet; then 100 s more: due on time, not late */
    CHECK(mt_tick(&back, T0 + 500, 5, f, 4, &dropped) == 0);
    CHECK(mt_tick(&back, T0 + 600, 105, f, 4, &dropped) == 1);
    CHECK(f[0].silent == 1 && strcmp(f[0].label, "pasta") == 0 && !f[0].late);
    CHECK(mt_count(&back) == 1);
}

static void test_missed_while_off(void)
{
    mt_state_t st; mt_init(&st);
    mt_add_timer(&st, T0, 0, 60, "late", 0);
    mt_add_timer(&st, T0, 0, 700, "gone", 0);
    mt_fired_t f[4]; int dropped;
    /* back on 90 s after the first came due: late but inside the grace, so it rings */
    CHECK(mt_tick(&st, T0 + 60 + 90, 3, f, 4, &dropped) == 1 && f[0].late && dropped == 0);
    CHECK(strcmp(f[0].label, "late") == 0);
    /* back on more than the grace after the second: dropped without ringing */
    CHECK(mt_tick(&st, T0 + 700 + MT_MISSED_GRACE_S + 1, 3, f, 4, &dropped) == 0);
    CHECK(dropped == 1 && mt_count(&st) == 0);
}

static void test_corrupt_blob_loads_nothing(void)
{
    mt_state_t st; mt_init(&st);
    mt_add_timer(&st, T0, 0, 60, "a", 0);
    uint8_t buf[MT_BLOB_MAX];
    size_t n = mt_save(&st, buf, sizeof(buf));
    mt_state_t back;
    uint8_t bad[MT_BLOB_MAX];
    memcpy(bad, buf, n); bad[9] ^= 0x40;
    CHECK(mt_load(&back, bad, n) < 0 && mt_count(&back) == 0 && back.next_id == 1);
    memcpy(bad, buf, n); bad[0] = 2; /* a newer version */
    CHECK(mt_load(&back, bad, n) < 0 && mt_count(&back) == 0);
    CHECK(mt_load(&back, buf, n - 1) < 0);
    CHECK(mt_load(&back, buf, 0) < 0);
    CHECK(mt_save(&st, buf, 10) == 0);
    /* an empty save loads an empty state */
    mt_state_t empty; mt_init(&empty);
    n = mt_save(&empty, buf, sizeof(buf));
    CHECK(mt_load(&back, buf, n) == MT_OK && mt_count(&back) == 0);
}

static void test_ring_and_snooze(void)
{
    mt_state_t st; mt_init(&st);
    mt_ring_t r; mt_ring_init(&r);
    mt_fired_t f = {7, MT_KIND_TIMER, 0, 0, "eggs"};
    CHECK(mt_ring_start(&r, &f, 1000) == 1);
    CHECK(mt_ring_poll(&r, 1000) == MT_POLL_CHIME);
    CHECK(mt_ring_poll(&r, 1500) == MT_POLL_NONE);
    CHECK(mt_ring_poll(&r, 9000) == MT_POLL_CHIME);
    mt_fired_t g = {8, MT_KIND_TIMER, 0, 0, "b"};
    CHECK(mt_ring_start(&r, &g, 9100) == 0 && r.extra == 1);
    CHECK(mt_ring_poll(&r, 1000 + MT_RING_MAX_MS) == MT_POLL_TIMEOUT);
    CHECK(mt_ring_end(&r, 61000) == 1);
    CHECK(mt_ring_end(&r, 61001) == 0);
    int id = mt_snooze(&st, &r, T0, 0, 62000, 0);
    CHECK(id > 0 && st.e[0].due == T0 + MT_SNOOZE_DEFAULT_S && strcmp(st.e[0].label, "eggs") == 0);
    CHECK(mt_snooze(&st, &r, T0, 0, 62000, 0) == MT_ERR_NOT_FOUND); /* once per ring */
    /* too late for a snooze */
    mt_ring_start(&r, &f, 100000); mt_ring_end(&r, 100500);
    CHECK(mt_snooze(&st, &r, T0, 0, 100500 + MT_SNOOZE_WINDOW_MS + 1, 60) == MT_ERR_NOT_FOUND);
    /* snooze while ringing ends the ring, and is capped */
    mt_ring_start(&r, &f, 200000);
    id = mt_snooze(&st, &r, T0, 0, 200100, 99999);
    CHECK(id > 0 && !r.active && st.e[1].due == T0 + MT_SNOOZE_MAX_S);
}

static void test_silent_ring_never_chimes(void)
{
    mt_ring_t r; mt_ring_init(&r);
    mt_fired_t f = {1, MT_KIND_ALARM, 0, 1, "q"};
    mt_ring_start(&r, &f, 0);
    CHECK(mt_ring_poll(&r, 0) == MT_POLL_NONE);
    CHECK(mt_ring_poll(&r, 30000) == MT_POLL_NONE);
    CHECK(mt_ring_poll(&r, MT_RING_MAX_MS) == MT_POLL_TIMEOUT);
}

static void test_pulse_is_the_standards_short_pulse(void)
{
    CHECK(mt_pulse_level(0) == 255);
    CHECK(mt_pulse_level(249) == 255);
    CHECK(mt_pulse_level(250) == 0);
    CHECK(mt_pulse_level(1999) == 0);
    CHECK(mt_pulse_level(0) == mt_pulse_level(2000));
}

int main(void)
{
    test_timer_fires_once();
    test_limits();
    test_label_is_clean();
    test_alarm_next_occurrence();
    test_no_clock_timer_runs_on_boot_time_and_is_not_saved();
    test_survives_reboot();
    test_missed_while_off();
    test_corrupt_blob_loads_nothing();
    test_ring_and_snooze();
    test_silent_ring_never_chimes();
    test_pulse_is_the_standards_short_pulse();
    if (failures) { printf("%d failure(s)\n", failures); return 1; }
    printf("timers core: all passed\n");
    return 0;
}
