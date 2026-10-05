"""MOVES-01: the recorded moves package (design record section 11).

Plays Pollen's recorded emotions (Apache-2.0), fetched on demand at a
pinned revision with a checksum and never vendored, through the HAL
seam, only on a person's ask or at the plan's ``react`` slot. Never from
a cue: nothing in ``maipai_body.expression`` imports this package (a
test asserts it), and nothing here reads an emotion or a sentiment.

Like ``expression/``, this lives in ``body/`` because no runtime or
package host exists in this repo yet; it moves under ``packages/``
(``platforms: [bot]``, category Robot body, ``requires:
["moves_recorded"]``) the day one can host it.
"""
