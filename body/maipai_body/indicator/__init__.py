"""EYES-02: what the eyes show, decided in one place.

``looks.py`` is the one look table; ``director.py`` turns the presence
funnel's shown state plus the live-capture facts into looks on whatever
``Indicator`` the body has; ``live.py`` is the tap that makes a mic open or
a camera read impossible to hide from the eyes. ``indicator`` is the
bot-internal HAL name; the spec capability id is ``eyes`` (``light_ring``
on the MaiPai build).
"""
