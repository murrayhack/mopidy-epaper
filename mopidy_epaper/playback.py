"""The playback snapshot the screens render.

One immutable value carried through the frontend, the UI and the layout,
instead of seven loose arguments threaded through each of them. Adding a field
means changing this class, wherever it is drawn, and where it is read in
``frontend._refresh`` — not every signature in between.
"""

import dataclasses


@dataclasses.dataclass(frozen=True)
class Playback:
    """What is playing, at one moment.

    ``track`` is duck-typed against :class:`mopidy.models.Track`; nothing here
    imports Mopidy.
    """

    track: object = None
    state: str = "stopped"
    position_ms: int = None
    volume: int = None
    #: 1-based position in the queue, and its length.
    number: int = None
    total: int = 0
    muted: bool = False

    @property
    def length_ms(self):
        return getattr(self.track, "length", None)
