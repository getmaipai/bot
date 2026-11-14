/* Host test for the away-from-home fallback choices (patch 146): cc -std=c99 -Wall -Werror -I<dir with the header>. */
#include <stdio.h>
#include <string.h>
#include "maipai_fallback_core.h"

static int failures;
#define CHECK(cond)                                                      \
    do {                                                                 \
        if (!(cond)) {                                                   \
            printf("FAIL line %d: %s\n", __LINE__, #cond);               \
            failures++;                                                  \
        }                                                                \
    } while (0)

static void test_ssid_gate(void)
{
    CHECK(mf_ssid_allowed("maipai-trip", "maipai"));
    CHECK(mf_ssid_allowed("MaiPai-Trip", "maipai"));      /* case-insensitive */
    CHECK(mf_ssid_allowed("maipai", "maipai"));
    CHECK(!mf_ssid_allowed("BuddysWiFi", "maipai"));      /* a friend's router never gets the token */
    CHECK(!mf_ssid_allowed("xmaipai-trip", "maipai"));    /* a prefix, not a substring */
    CHECK(!mf_ssid_allowed("", "maipai"));
    CHECK(!mf_ssid_allowed(NULL, "maipai"));
    CHECK(mf_ssid_allowed("anything", ""));                /* an empty prefix allows every network (development) */
    CHECK(mf_ssid_allowed(NULL, ""));
}

static void test_pick(void)
{
    char out[16];
    /* the laptop picked another subnet: the gateway comes first, then the configured 192.168.2.1 */
    CHECK(mf_pick_host(0, "192.168.3.1", "192.168.2.1", "198.51.100.7", out, sizeof(out)) && strcmp(out, "192.168.3.1") == 0);
    CHECK(mf_pick_host(1, "192.168.3.1", "192.168.2.1", "198.51.100.7", out, sizeof(out)) && strcmp(out, "192.168.2.1") == 0);
    CHECK(mf_pick_host(2, "192.168.3.1", "192.168.2.1", "198.51.100.7", out, sizeof(out)) && strcmp(out, "192.168.3.1") == 0);
    /* the usual case: the gateway IS 192.168.2.1: one candidate, no duplicate */
    CHECK(mf_pick_host(0, "192.168.2.1", "192.168.2.1", "198.51.100.7", out, sizeof(out)) && strcmp(out, "192.168.2.1") == 0);
    CHECK(mf_pick_host(1, "192.168.2.1", "192.168.2.1", "198.51.100.7", out, sizeof(out)) && strcmp(out, "192.168.2.1") == 0);
    /* no gateway yet: the configured host alone */
    CHECK(mf_pick_host(0, "", "192.168.2.1", "198.51.100.7", out, sizeof(out)) && strcmp(out, "192.168.2.1") == 0);
    CHECK(mf_pick_host(0, "0.0.0.0", "192.168.2.1", "198.51.100.7", out, sizeof(out)) && strcmp(out, "192.168.2.1") == 0);
    /* the gateway is the home host itself: skipped (it is already the first attempt) */
    CHECK(mf_pick_host(0, "192.168.2.1", "", "192.168.2.1", out, sizeof(out)) == 0);
    CHECK(mf_pick_host(0, "192.168.2.1", "192.168.2.9", "192.168.2.1", out, sizeof(out)) && strcmp(out, "192.168.2.9") == 0);
    /* nothing usable, a short buffer, a negative attempt */
    CHECK(mf_pick_host(0, "", "", "10.0.0.1", out, sizeof(out)) == 0);
    CHECK(mf_pick_host(0, "192.168.3.1", "", "10.0.0.1", out, 4) == 0);
    CHECK(mf_pick_host(-5, "192.168.3.1", "192.168.2.1", "10.0.0.1", out, sizeof(out)) && strcmp(out, "192.168.3.1") == 0);
}

int main(void)
{
    test_ssid_gate();
    test_pick();
    if (failures) {
        printf("%d check(s) failed\n", failures);
        return 1;
    }
    printf("fallback core: all checks passed\n");
    return 0;
}
