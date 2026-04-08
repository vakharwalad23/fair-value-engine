from src.subscription.slot_tracker import SlotTracker

def test_initial_state():
    tracker = SlotTracker(total_slots=15000)
    assert tracker.used == 0
    assert tracker.total == 15000
    assert tracker.available == 15000

def test_add_remove():
    tracker = SlotTracker(total_slots=15000)
    tracker.add("42528", tier=1)
    tracker.add("42529", tier=1)
    tracker.add("50001", tier=2)
    assert tracker.used == 3
    assert tracker.per_tier() == {1: 2, 2: 1, 3: 0}
    tracker.remove("42528")
    assert tracker.used == 2

def test_forecast():
    tracker = SlotTracker(total_slots=15000)
    tracker.add("42528", tier=1)
    result = tracker.forecast(5)
    assert result["slots_needed"] == 5
    assert result["slots_after"] == 15000 - 1 - 5
    assert result["fits"] is True

def test_forecast_over_capacity():
    tracker = SlotTracker(total_slots=10)
    for i in range(8):
        tracker.add(str(i), tier=1)
    result = tracker.forecast(5)
    assert result["fits"] is False
