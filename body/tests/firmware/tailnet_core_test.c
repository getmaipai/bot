/* Host test for the tailnet client's pure choices (patch 147): cc -std=c99 -Wall -Werror -I<dir with the header>. */
#include <stdio.h>
#include <string.h>
#include "maipai_tailnet_core.h"

static int failures;
#define CHECK(cond)                                                      \
    do {                                                                 \
        if (!(cond)) {                                                   \
            printf("FAIL line %d: %s\n", __LINE__, #cond);               \
            failures++;                                                  \
        }                                                                \
    } while (0)

static void test_guard(void)
{
    mt_guard_t g;
    memset(&g, 0xff, sizeof(g));              /* garbage RTC memory after a power cycle */
    CHECK(mt_guard_boot(&g, 1) == 1);          /* a crash with no recorded start counts for nothing */
    CHECK(g.crashes == 0);
    mt_guard_started(&g);
    CHECK(mt_guard_boot(&g, 1) == 1 && g.crashes == 1);   /* crashed boot 1 */
    mt_guard_started(&g);
    CHECK(mt_guard_boot(&g, 1) == 1 && g.crashes == 2);   /* crashed boot 2 */
    mt_guard_started(&g);
    CHECK(mt_guard_boot(&g, 1) == 0 && g.crashes == 3);   /* crashed boot 3: the client is switched off */
    /* a clean restart in between resets the count */
    memset(&g, 0, sizeof(g));
    mt_guard_boot(&g, 0);
    mt_guard_started(&g);
    CHECK(mt_guard_boot(&g, 1) == 1 && g.crashes == 1);
    mt_guard_started(&g);
    CHECK(mt_guard_boot(&g, 0) == 1 && g.crashes == 0);   /* a software restart is not a crash */
    /* a boot that proved itself stable clears the count */
    mt_guard_started(&g);
    mt_guard_stable(&g);
    CHECK(mt_guard_boot(&g, 1) == 1 && g.crashes == 0);   /* started=0: a later crash is not the client's */
}

static void test_ip(void)
{
    char out[16];
    mt_ip_to_str(0x64710000u | 0x043d, out);               /* 100.113.4.61 */
    CHECK(strcmp(out, "100.113.4.61") == 0);
    CHECK(mt_parse_ip("100.113.4.61") == 0x6471043du);
    CHECK(mt_parse_ip("100.113.4") == 0);
    CHECK(mt_parse_ip("100.113.4.256") == 0);
    CHECK(mt_parse_ip("100.113.4.61x") == 0);
    CHECK(mt_parse_ip("") == 0);
    CHECK(mt_parse_ip(NULL) == 0);
    CHECK(mt_is_tailnet_ip(mt_parse_ip("100.113.4.61")));
    CHECK(mt_is_tailnet_ip(mt_parse_ip("100.64.0.1")));
    CHECK(mt_is_tailnet_ip(mt_parse_ip("100.127.255.254")));
    CHECK(!mt_is_tailnet_ip(mt_parse_ip("100.128.0.1")));  /* just outside 100.64.0.0/10 */
    CHECK(!mt_is_tailnet_ip(mt_parse_ip("100.63.255.255")));
    CHECK(!mt_is_tailnet_ip(mt_parse_ip("192.168.2.1")));
}

static void test_pick(void)
{
    char out[16];
    /* tailnet up: it comes first, then the gateway, then the configured host */
    CHECK(mt_pick_host(0, "100.113.4.61", "192.168.3.1", "192.168.2.1", "192.0.2.10", out, sizeof(out)) && strcmp(out, "100.113.4.61") == 0);
    CHECK(mt_pick_host(1, "100.113.4.61", "192.168.3.1", "192.168.2.1", "192.0.2.10", out, sizeof(out)) && strcmp(out, "192.168.3.1") == 0);
    CHECK(mt_pick_host(2, "100.113.4.61", "192.168.3.1", "192.168.2.1", "192.0.2.10", out, sizeof(out)) && strcmp(out, "192.168.2.1") == 0);
    CHECK(mt_pick_host(3, "100.113.4.61", "192.168.3.1", "192.168.2.1", "192.0.2.10", out, sizeof(out)) && strcmp(out, "100.113.4.61") == 0);  /* rotates */
    /* tailnet down (empty): the LAN candidates only */
    CHECK(mt_pick_host(0, "", "192.168.3.1", "192.168.2.1", "192.0.2.10", out, sizeof(out)) && strcmp(out, "192.168.3.1") == 0);
    /* a stranger's network (no LAN candidates) with the tailnet up: only the tailnet */
    CHECK(mt_pick_host(0, "100.113.4.61", "", "", "192.0.2.10", out, sizeof(out)) && strcmp(out, "100.113.4.61") == 0);
    CHECK(mt_pick_host(5, "100.113.4.61", "", "", "192.0.2.10", out, sizeof(out)) && strcmp(out, "100.113.4.61") == 0);
    /* a stranger's network and no tailnet: nothing, so the token goes nowhere */
    CHECK(!mt_pick_host(0, "", "", "", "192.0.2.10", out, sizeof(out)));
    CHECK(!mt_pick_host(0, NULL, NULL, NULL, "192.0.2.10", out, sizeof(out)));
    /* the home host and duplicates are skipped; 0.0.0.0 too */
    CHECK(mt_pick_host(0, "192.0.2.10", "192.168.3.1", "192.168.3.1", "192.0.2.10", out, sizeof(out)) && strcmp(out, "192.168.3.1") == 0);
    CHECK(mt_pick_host(1, "192.0.2.10", "192.168.3.1", "192.168.3.1", "192.0.2.10", out, sizeof(out)) && strcmp(out, "192.168.3.1") == 0);
    CHECK(!mt_pick_host(0, "0.0.0.0", "", "", "192.0.2.10", out, sizeof(out)));
    /* a negative attempt is treated as 0; a too-small output buffer is refused */
    CHECK(mt_pick_host(-3, "100.113.4.61", "", "", "", out, sizeof(out)) && strcmp(out, "100.113.4.61") == 0);
    CHECK(!mt_pick_host(0, "100.113.4.61", "", "", "", out, 4));
}

int main(void)
{
    test_guard();
    test_ip();
    test_pick();
    if (failures != 0) {
        printf("%d checks failed\n", failures);
        return 1;
    }
    printf("all checks passed\n");
    return 0;
}
