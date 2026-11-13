/* Host test for the face touch classifier (patch 105): cc -std=c99 -Wall -Werror -I<dir with the header>. */
#include <stdio.h>
#include <string.h>
#include "maipai_touch_core.h"

static int failures;
#define CHECK(cond)                                                      \
    do {                                                                 \
        if (!(cond)) {                                                   \
            printf("FAIL line %d: %s\n", __LINE__, #cond);               \
            failures++;                                                  \
        }                                                                \
    } while (0)

/* A finger goes down at (x0,y0), strays to (sx,sy) on the way, and lifts at (x1,y1) after held_ms. */
static mtc_action_t touch(int x0, int y0, int sx, int sy, int x1, int y1, uint32_t held_ms)
{
    mtc_trace_t t;
    mtc_begin(&t, x0, y0, 1000);
    mtc_move(&t, sx, sy, 1000 + held_ms / 2);
    mtc_move(&t, x1, y1, 1000 + held_ms);
    return mtc_action_on_release(&t);
}
static mtc_action_t still(int x, int y, uint32_t held_ms) { return touch(x, y, x, y, x, y, held_ms); }

static void test_regions_tile_the_screen(void)
{
    int counts[6] = {0};
    for (int y = 0; y < MTC_HEIGHT; y++) {
        for (int x = 0; x < MTC_WIDTH; x++) {
            mtc_region_t r = mtc_region_at(x, y);
            CHECK(r >= MTC_REGION_EDGE && r <= MTC_REGION_REST);
            counts[r]++;
        }
    }
    for (int i = 0; i < 6; i++) CHECK(counts[i] > 0);
    CHECK(counts[MTC_REGION_EYE_LEFT] == counts[MTC_REGION_EYE_RIGHT]);
    /* the eyes as drawn (x 56..108 and 212..264, y 86..108 for the dot) sit inside their regions */
    CHECK(mtc_region_at(82, 97) == MTC_REGION_EYE_LEFT);
    CHECK(mtc_region_at(238, 97) == MTC_REGION_EYE_RIGHT);
    CHECK(mtc_region_at(160, 159) == MTC_REGION_MOUTH);
    CHECK(mtc_region_at(160, 40) == MTC_REGION_FOREHEAD);     /* above the eyes */
    CHECK(mtc_region_at(160, 90) == MTC_REGION_FOREHEAD);     /* between the eyes */
    CHECK(mtc_region_at(82, 40) == MTC_REGION_FOREHEAD);
    CHECK(mtc_region_at(60, 190) == MTC_REGION_REST);         /* a cheek */
    CHECK(mtc_region_at(260, 190) == MTC_REGION_REST);
}

static void test_reserved_edges(void)
{
    /* the margins are all edge, the first pixel inside is not */
    CHECK(mtc_region_at(160, 0) == MTC_REGION_EDGE);
    CHECK(mtc_region_at(160, MTC_EDGE_TOP - 1) == MTC_REGION_EDGE);
    CHECK(mtc_region_at(160, MTC_EDGE_TOP) == MTC_REGION_FOREHEAD);
    CHECK(mtc_region_at(0, 100) == MTC_REGION_EDGE);
    CHECK(mtc_region_at(MTC_EDGE_SIDE - 1, 100) == MTC_REGION_EDGE);
    CHECK(mtc_region_at(MTC_EDGE_SIDE, 100) == MTC_REGION_EYE_LEFT);
    CHECK(mtc_region_at(MTC_WIDTH - 1, 100) == MTC_REGION_EDGE);
    CHECK(mtc_region_at(MTC_WIDTH - MTC_EDGE_SIDE, 100) == MTC_REGION_EDGE);
    CHECK(mtc_region_at(MTC_WIDTH - MTC_EDGE_SIDE - 1, 100) == MTC_REGION_EYE_RIGHT);
    CHECK(mtc_region_at(160, MTC_HEIGHT - 1) == MTC_REGION_EDGE);
    CHECK(mtc_region_at(160, MTC_HEIGHT - MTC_EDGE_BOTTOM) == MTC_REGION_EDGE);
    CHECK(mtc_region_at(160, MTC_HEIGHT - MTC_EDGE_BOTTOM - 1) == MTC_REGION_MOUTH);
    /* a touch that starts in an edge zone is never a toggle, however still or long */
    CHECK(still(160, 5, 100) == MTC_ACTION_NONE);
    CHECK(still(160, 5, 700) == MTC_ACTION_NONE);
    CHECK(still(5, 100, 100) == MTC_ACTION_NONE);
    CHECK(still(160, 235, 700) == MTC_ACTION_NONE);
    /* a drag from the top bezel into the forehead (quick settings) toggles nothing */
    CHECK(touch(160, 10, 160, 40, 160, 60, 300) == MTC_ACTION_NONE);
    CHECK(touch(160, 10, 160, 10, 160, 10, 700) == MTC_ACTION_NONE);
}

static void test_eyes_toggle_vision_on_a_tap(void)
{
    CHECK(still(82, 97, 80) == MTC_ACTION_VISION);
    CHECK(still(238, 97, 80) == MTC_ACTION_VISION);
    CHECK(still(82, 97, MTC_TAP_MAX_MS) == MTC_ACTION_VISION);
    CHECK(still(82, 97, MTC_TAP_MAX_MS + 1) == MTC_ACTION_NONE);  /* dead band */
    CHECK(still(82, 97, MTC_HOLD_MS - 1) == MTC_ACTION_NONE);
    CHECK(still(82, 97, MTC_HOLD_MS) == MTC_ACTION_NONE);          /* a held eye does nothing */
    CHECK(still(82, 97, 2000) == MTC_ACTION_NONE);
}

static void test_mouth_and_forehead_take_a_tap_only(void)
{
    CHECK(still(160, 159, 80) == MTC_ACTION_MUTE);                 /* a plain tap on the mouth */
    CHECK(still(160, 159, MTC_TAP_MAX_MS) == MTC_ACTION_MUTE);
    CHECK(still(160, 159, MTC_TAP_MAX_MS + 1) == MTC_ACTION_NONE); /* the dead band */
    CHECK(still(160, 159, MTC_HOLD_MS - 1) == MTC_ACTION_NONE);
    CHECK(still(160, 159, MTC_HOLD_MS) == MTC_ACTION_NONE);        /* a hold does nothing now */
    CHECK(still(160, 159, 3000) == MTC_ACTION_NONE);
    CHECK(still(160, 90, 80) == MTC_ACTION_QUIET);                 /* a plain tap between the eyes */
    CHECK(still(160, 90, MTC_HOLD_MS) == MTC_ACTION_NONE);
    CHECK(still(120, 40, 80) == MTC_ACTION_QUIET);                 /* above the left eye */
    CHECK(still(60, 190, MTC_HOLD_MS) == MTC_ACTION_NONE);         /* the rest of the face toggles nothing */
    CHECK(still(60, 190, 80) == MTC_ACTION_NONE);
}

static void test_a_stray_finger_is_a_drag(void)
{
    /* inside the limit */
    CHECK(touch(82, 97, 86, 99, 82, 97, 80) == MTC_ACTION_VISION);
    CHECK(touch(160, 159, 165, 164, 160, 159, 80) == MTC_ACTION_MUTE);
    /* strays 11 px on the way and comes back: a drag, even though it ends where it began */
    CHECK(touch(82, 97, 93, 97, 82, 97, 80) == MTC_ACTION_NONE);
    CHECK(touch(160, 159, 160, 170, 160, 159, MTC_HOLD_MS + 100) == MTC_ACTION_NONE);
    /* a swipe across the face (volume, stop) */
    CHECK(touch(60, 97, 130, 97, 200, 97, 250) == MTC_ACTION_NONE);
    CHECK(touch(160, 100, 160, 140, 160, 190, 250) == MTC_ACTION_NONE);
    /* released in another region is no toggle even when the stray is small: eye border */
    {
        mtc_trace_t t;
        mtc_begin(&t, 108, 97, 0);  /* eye region (x < 112) */
        mtc_move(&t, 114, 97, 40);  /* now in the forehead gap */
        CHECK(mtc_classify(&t) == MTC_KIND_DRAG);
        CHECK(mtc_action_on_release(&t) == MTC_ACTION_NONE);
    }
}

static void test_a_hold_never_acts_while_the_finger_is_down(void)
{
    mtc_trace_t t;
    mtc_begin(&t, 160, 159, 5000);
    mtc_move(&t, 161, 160, 5000 + MTC_HOLD_MS);
    CHECK(mtc_action_while_down(&t, 5000 + MTC_HOLD_MS) == MTC_ACTION_NONE); /* the mouth */
    mtc_begin(&t, 160, 90, 0);
    CHECK(mtc_action_while_down(&t, 900) == MTC_ACTION_NONE);               /* the forehead */
    mtc_begin(&t, 82, 97, 0);
    CHECK(mtc_action_while_down(&t, 900) == MTC_ACTION_NONE);               /* an eye */
    mtc_begin(&t, 60, 190, 0);
    CHECK(mtc_action_while_down(&t, 900) == MTC_ACTION_NONE);               /* the rest */
}

static void test_only_the_rest_of_the_face_listens(void)
{
    CHECK(mtc_region_listens(MTC_REGION_REST));
    CHECK(!mtc_region_listens(MTC_REGION_MOUTH));
    CHECK(!mtc_region_listens(MTC_REGION_FOREHEAD));
    CHECK(!mtc_region_listens(MTC_REGION_EYE_LEFT));
    CHECK(!mtc_region_listens(MTC_REGION_EYE_RIGHT));
    CHECK(!mtc_region_listens(MTC_REGION_EDGE));
}

int main(void)
{
    test_regions_tile_the_screen();
    test_reserved_edges();
    test_eyes_toggle_vision_on_a_tap();
    test_mouth_and_forehead_take_a_tap_only();
    test_a_stray_finger_is_a_drag();
    test_a_hold_never_acts_while_the_finger_is_down();
    test_only_the_rest_of_the_face_listens();
    if (failures) {
        printf("%d failure(s)\n", failures);
        return 1;
    }
    printf("all passed\n");
    return 0;
}
