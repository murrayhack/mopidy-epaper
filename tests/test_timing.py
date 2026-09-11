"""The tick rate.

Kept out of ``frontend`` precisely so these run anywhere: that module imports
``mopidy.core``, which needs GStreamer's Python bindings.
"""

import pytest

from mopidy_epaper.timing import tick_interval


def interval(update_interval=5, update_interval_charging=None, plugged=False):
    config = {
        "update_interval": update_interval,
        "update_interval_charging": update_interval_charging,
    }
    return tick_interval(config, plugged)


def test_battery_uses_the_normal_interval():
    assert interval(update_interval=5, update_interval_charging=1) == 5


def test_mains_uses_the_charging_interval():
    assert interval(update_interval=5, update_interval_charging=1, plugged=True) == 1


def test_unset_charging_interval_changes_nothing():
    """The default: one rate, whatever the power source."""
    assert interval(update_interval=5, plugged=True) == 5
    assert interval(update_interval=5, plugged=False) == 5


def test_the_rate_follows_the_charger():
    """The frontend calls this every time round the loop, so plugging in
    speeds the panel up there and then rather than needing a restart."""
    config = dict(update_interval=5, update_interval_charging=1)

    assert interval(**config, plugged=False) == 5
    assert interval(**config, plugged=True) == 1


@pytest.mark.parametrize("charging", [0, None])
def test_a_falsy_charging_interval_falls_back(charging):
    """0 is not a valid interval, and must not become a busy loop."""
    assert interval(update_interval=5, update_interval_charging=charging, plugged=True) == 5
