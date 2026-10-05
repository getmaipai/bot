# Synthetic camera frames

Cartoon faces drawn by `generate.py` from numpy primitives: a flat
background, an ellipse for the head, two dots, a line. Provenance is
this repo's own code, nothing downloaded, no photograph of anyone,
no household photos, no public-domain image to attribute. Licence:
same as the repo.

| File | Content |
| --- | --- |
| `face_center.npy` | one synthetic face, centred |
| `face_left.npy` | the same face, left quarter |
| `face_right.npy` | the same face, right quarter |
| `no_face.npy` | the background only |

Each is `(120, 160, 3)` uint8 in BGR order, the shape `Camera.get_frame()`
returns, loaded by `load_face_fixture(name)` in `fake.py`. They exercise
the fake's frame script and the camera seam; a real face detector will
not be expected to find a face in a cartoon, so nothing here stands in
for a recognition fixture.

Regenerate with `python generate.py`; the output is byte-identical on
every run.
