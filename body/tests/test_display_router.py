"""BOT-SC-SCREEN-01: the body-neutral router that decides which surface shows what."""

from __future__ import annotations

from maipai_body.robot.display import Content, ContentKind, Placement, Surface, choose_placements


def _content(
    kind: ContentKind,
    has_image: bool = False,
    has_text: bool = False,
    has_icon: bool = False,
    hold_s: float = 10.0,
) -> Content:
    return Content(
        kind=kind,
        has_image=has_image,
        has_text=has_text,
        has_icon=has_icon,
        hold_s=hold_s,
    )


# StackChan-like body: the whole face is the screen, so it is shared with the
# animated face and showing content hides it.
STACKCHAN = [
    Surface(
        name="face",
        kind="face",
        shows_images=True,
        shows_text=True,
        shows_icon=True,
        shared_with_face=True,
    ),
]

# A body with a separate dial (icons only), an lcd (images and text) and a
# face that can also show everything.
DIAL = Surface(
    name="dial",
    kind="dial",
    shows_images=False,
    shows_text=False,
    shows_icon=True,
    shared_with_face=False,
)
LCD = Surface(
    name="lcd",
    kind="lcd",
    shows_images=True,
    shows_text=True,
    shows_icon=False,
    shared_with_face=False,
)
FACE = Surface(
    name="face",
    kind="face",
    shows_images=True,
    shows_text=True,
    shows_icon=True,
    shared_with_face=True,
)
FULL = [DIAL, LCD, FACE]

# Same set as FULL but listed lcd-first: placement order must follow the
# order of `surfaces`, not the order of the rules.
FULL_LCD_FIRST = [LCD, DIAL, FACE]

DIAL_ONLY = [DIAL]


class TestCameraActive:
    def test_nowhere_without_a_dial(self) -> None:
        # Rule (a): the face must not be taken over by an indicator.
        content = _content("camera_active", has_icon=True, hold_s=2.0)
        assert choose_placements(content, STACKCHAN) == []

    def test_goes_to_the_dial(self) -> None:
        content = _content("camera_active", has_icon=True, hold_s=2.0)
        assert choose_placements(content, FULL) == [
            Placement("dial", takes_over_face=False, hold_s=2.0)
        ]

    def test_indicator_without_an_icon_goes_nowhere(self) -> None:
        # Rule (d): a surface that cannot show what the content carries is
        # never chosen.
        assert choose_placements(_content("camera_active"), FULL) == []


class TestImageContent:
    def test_photo_prefers_the_lcd_and_keeps_the_face(self) -> None:
        # Rule (b): no face takeover on the lcd.
        content = _content("photo", has_image=True, hold_s=20.0)
        assert choose_placements(content, FULL) == [
            Placement("lcd", takes_over_face=False, hold_s=20.0)
        ]

    def test_photo_without_an_image_goes_nowhere(self) -> None:
        assert choose_placements(_content("photo"), FULL) == []

    def test_photo_with_no_image_capable_surface_goes_nowhere(self) -> None:
        content = _content("photo", has_image=True)
        assert choose_placements(content, DIAL_ONLY) == []

    def test_photo_on_stackchan_takes_over_the_face_capped_at_15s(self) -> None:
        content = _content("photo", has_image=True, hold_s=60.0)
        assert choose_placements(content, STACKCHAN) == [
            Placement("face", takes_over_face=True, hold_s=15.0)
        ]

    def test_weather_on_stackchan_takes_over_the_face_at_most_15s(self) -> None:
        content = _content("weather", has_image=True, has_text=True, hold_s=30.0)
        assert choose_placements(content, STACKCHAN) == [
            Placement("face", takes_over_face=True, hold_s=15.0)
        ]

    def test_camera_feed_on_stackchan_takes_over_the_face_capped_at_30s(self) -> None:
        content = _content("camera_feed", has_image=True, hold_s=60.0)
        assert choose_placements(content, STACKCHAN) == [
            Placement("face", takes_over_face=True, hold_s=30.0)
        ]


class TestAlertAndStatus:
    def test_alert_splits_icon_to_dial_and_text_to_lcd(self) -> None:
        # Rule (c): both placements, at most one per surface (rule (e)).
        content = _content("alert", has_text=True, has_icon=True)
        assert choose_placements(content, FULL) == [
            Placement("dial", takes_over_face=False, hold_s=10.0),
            Placement("lcd", takes_over_face=False, hold_s=10.0),
        ]

    def test_order_follows_the_surfaces_order(self) -> None:
        # Rule (f): deterministic order is the order of `surfaces`.
        content = _content("alert", has_text=True, has_icon=True)
        assert choose_placements(content, FULL_LCD_FIRST) == [
            Placement("lcd", takes_over_face=False, hold_s=10.0),
            Placement("dial", takes_over_face=False, hold_s=10.0),
        ]

    def test_alert_with_only_a_face_takes_it_over_capped_at_8s(self) -> None:
        content = _content("alert", has_text=True, hold_s=30.0)
        assert choose_placements(content, STACKCHAN) == [
            Placement("face", takes_over_face=True, hold_s=8.0)
        ]

    def test_alert_skips_the_face_when_a_dial_can_show_the_icon(self) -> None:
        content = _content("alert", has_icon=True)
        assert choose_placements(content, [DIAL, FACE]) == [
            Placement("dial", takes_over_face=False, hold_s=10.0)
        ]

    def test_status_goes_nowhere_on_stackchan(self) -> None:
        # Rule (c): status never hides the face.
        assert choose_placements(_content("status", has_text=True), STACKCHAN) == []

    def test_status_with_only_an_icon_goes_to_the_dial(self) -> None:
        content = _content("status", has_icon=True)
        assert choose_placements(content, FULL) == [
            Placement("dial", takes_over_face=False, hold_s=10.0)
        ]

    def test_status_with_text_and_icon_uses_dial_and_lcd(self) -> None:
        content = _content("status", has_text=True, has_icon=True)
        assert choose_placements(content, FULL) == [
            Placement("dial", takes_over_face=False, hold_s=10.0),
            Placement("lcd", takes_over_face=False, hold_s=10.0),
        ]

    def test_alert_with_no_text_and_no_icon_goes_nowhere(self) -> None:
        # Rule (d): the face cannot show what the content does not carry.
        assert choose_placements(_content("alert"), STACKCHAN) == []

    def test_status_with_no_text_and_no_icon_goes_nowhere(self) -> None:
        assert choose_placements(_content("status"), FULL) == []


class TestOnePlacementPerSurface:
    def test_only_the_first_icon_dial_is_chosen(self) -> None:
        # Rule (e): at most one placement per surface, in list order.
        dial_b = Surface(
            name="dial-b",
            kind="dial",
            shows_images=False,
            shows_text=False,
            shows_icon=True,
            shared_with_face=False,
        )
        content = _content("alert", has_icon=True)
        assert choose_placements(content, [DIAL, dial_b]) == [
            Placement("dial", takes_over_face=False, hold_s=10.0)
        ]
