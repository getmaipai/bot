# Rung 1 keyword spotter fixtures

SYNTHESIZED speech, not recordings. `scripts/make_kws_fixtures.py` says every
phrase of the closed command list and a near-miss list through two Piper
voices (`en_US-amy-low`, `en_US-ryan-medium`, k2-fsa/sherpa-onnx `tts-models`
release) and writes 16 kHz mono 16-bit wavs plus `manifest.json`. No person
spoke these and no household audio is here.

They let `tests/test_kws_real_model.py` run the real spotter end to end. They
say nothing about a real microphone, a real room or a real voice: that is
`scripts/measure_kws.py` on the unit, and it is UNVERIFIED.
