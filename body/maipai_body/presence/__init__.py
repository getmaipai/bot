"""RM-06: presence and tracking, and the arbitration priority tracking sits inside.

``dev.md``'s presence funnel is BODY-05's own item (a MaiPai-build
package, ``body/presence/``, unbuilt: it needs BODY-02's owned-build
drivers first). This module is this body's own inputs to that funnel
(the daemon's face tracking, the array's direction of arrival and
speech flag, the IMU's tip and freefall observations) plus the
arbitration rule the design record's section 6 states for this body:
"consented tracking sits below inhibit, reflex and service, above
expression and idle." A generic ``BODY-05``-shaped funnel state
machine (speaking, thinking, listening, idle) needs a turn-aware
runtime to mean anything and is not this item's job.
"""
