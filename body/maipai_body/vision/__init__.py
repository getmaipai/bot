"""The still-image call's bot-side half (design-vision-still-image-
2026-09-28.md): capture one consented frame and hand it to whatever
hub route eventually asks for it. Nothing here talks to the hub - the
turn-loop wiring and the hub route both wait on the Stack's `vision`
role having a model behind it, the design note's own named blocker.
"""
