"""Pull the hub's live biometric face-print snapshot into the gallery."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

import numpy as np
import requests

from maipai_body.vision.gallery import FaceGallery, FacePrint

logger = logging.getLogger("maipai_body.link.prints")


class PrintSyncError(RuntimeError):
    """The print-sync request failed at the transport layer."""


class PrintSync:
    """Keep a local gallery aligned with the hub's authoritative snapshot."""

    def __init__(
        self,
        gallery: FaceGallery,
        hub_credentials: Callable[[], tuple[str, str]],
        stop_event: threading.Event,
        *,
        interval_s: float = 60.0,
        session: requests.Session | None = None,
    ) -> None:
        self._gallery = gallery
        self._hub_credentials = hub_credentials
        self._stop_event = stop_event
        self._interval_s = interval_s
        self._session = session or requests.Session()

    def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                cookie, base_url = self._hub_credentials()
            except Exception:
                logger.warning(
                    "failed to refresh hub credentials; keeping current face prints", exc_info=True
                )
            else:
                try:
                    response = self._session.get(
                        f"{base_url}/api/biometric-prints/sync",
                        headers={"Cookie": f"session={cookie}"},
                        timeout=5,
                    )
                except requests.RequestException:
                    logger.warning(
                        "face print sync connection failed; keeping current prints", exc_info=True
                    )
                else:
                    if response.status_code in (401, 403):
                        logger.info(
                            "hub rejected face print sync (%s); clearing the gallery",
                            response.status_code,
                        )
                        self._gallery.replace_all([])
                    elif not 200 <= response.status_code < 300:
                        logger.warning(
                            "face print sync returned HTTP %s; keeping current prints",
                            response.status_code,
                        )
                    else:
                        try:
                            payload = response.json()
                            prints = [
                                FacePrint(
                                    id=entry["id"],
                                    person_id=entry["person_id"],
                                    model_id=entry["model_id"],
                                    model_sha256=entry["model_sha256"],
                                    embedding=np.array(entry["embedding"], dtype=np.float32),
                                )
                                for entry in payload["prints"]
                            ]
                        except (KeyError, TypeError, ValueError):
                            logger.warning(
                                "invalid face print sync response; keeping current prints",
                                exc_info=True,
                            )
                        else:
                            self._gallery.replace_all(prints)
            if self._stop_event.wait(self._interval_s):
                return
