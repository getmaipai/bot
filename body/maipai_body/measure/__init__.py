"""Bench measurement tooling for the design's section 12 rows (M-R1 to M-R5).

Pure, injectable pieces (statistics, trace analysis, probes' parsers) live
here so the deterministic suite proves them without a unit or a
simulator; the runnable scripts in ``body/scripts/measure_*.py`` are thin
drivers over them. Nothing in this package records a number on its own:
every figure comes from a script run against the simulator or the unit.
"""
