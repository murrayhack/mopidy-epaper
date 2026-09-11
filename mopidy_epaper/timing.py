"""When to tick.

Its own module, and free of Mopidy, so the decision is testable anywhere —
``frontend`` imports ``mopidy.core``, which pulls in GStreamer's bindings and
cannot be imported off a configured Pi.
"""


def tick_interval(config, plugged):
    """Seconds to wait before the next refresh.

    Faster on mains, where the only cost is panel refreshes, and slower on
    battery, where every tick is a snapshot, a socket read and a partial
    refresh of a panel that is not cheap to drive.

    Note this multiplies the full refreshes too: ``full_refresh_every`` counts
    partials, so halving the interval halves the time between the full-screen
    flashes that clear ghosting. Raise it alongside this, or the panel flashes
    far more often than it used to.
    """
    charging = config.get("update_interval_charging")
    if charging and plugged:
        return charging
    return config["update_interval"]
