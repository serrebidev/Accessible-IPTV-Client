"""Deterministic tests for the app-level responsiveness gate (#106)."""

import threading

from responsiveness import WorkGate


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def test_newer_work_supersedes_older_ticket_in_same_lane():
    gate = WorkGate()
    first = gate.begin("search")
    assert first.is_current()
    second = gate.begin("search")
    assert second.is_current()
    assert first.cancelled
    assert not first.checkpoint()
    assert second.generation == first.generation + 1


def test_lanes_are_independent():
    gate = WorkGate()
    search = gate.begin("search")
    gate.begin("epg")
    gate.begin("playlist")
    assert search.is_current()
    assert gate.generation("now_playing") == 0


def test_stale_worker_publishes_nothing_after_being_superseded():
    gate = WorkGate()
    published = []
    stale = gate.begin("search")

    def worker(ticket, rows):
        for row in rows:
            if not ticket.checkpoint():
                return
            published.append(row)

    # The worker gets through two rows, then a newer query supersedes it.
    worker(stale, ["a", "b"])
    gate.begin("search")
    worker(stale, ["c", "d"])
    assert published == ["a", "b"]


def test_current_work_completes_and_publishes_everything():
    gate = WorkGate()
    ticket = gate.begin("playlist")
    published = [row for row in range(10) if ticket.checkpoint()]
    assert published == list(range(10))
    assert ticket.is_current()


def test_interaction_makes_current_work_yield_until_window_passes():
    clock = FakeClock()
    gate = WorkGate(clock=clock, interaction_window=0.35)
    ticket = gate.begin("epg")
    assert not gate.should_yield(ticket)
    gate.note_interaction()
    assert gate.interaction_active()
    assert gate.should_yield(ticket)
    clock.advance(0.5)
    assert not gate.interaction_active()
    assert not gate.should_yield(ticket)


def test_stale_work_yields_regardless_of_interaction():
    clock = FakeClock()
    gate = WorkGate(clock=clock)
    stale = gate.begin("now_playing")
    gate.begin("now_playing")
    assert gate.should_yield(stale)


def test_concurrent_begins_leave_exactly_one_current_ticket():
    gate = WorkGate()
    tickets = []

    def begin_many():
        for _ in range(50):
            tickets.append(gate.begin("search"))

    threads = [threading.Thread(target=begin_many) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    current = [ticket for ticket in tickets if ticket.is_current()]
    assert len(current) == 1
    assert current[0].generation == 200
    assert gate.generation("search") == 200
