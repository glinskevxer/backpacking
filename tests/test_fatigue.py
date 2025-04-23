"""Fatigue accumulation, recovery and conditioning over a long trip."""

from __future__ import annotations

import pytest

from backpacking.errors import PaceModelError
from backpacking.pace.fatigue import (
    MAX_CONDITIONING,
    MAX_FATIGUE,
    NEUTRAL_EFFORT_HOURS,
    FatigueState,
    advance,
    project,
    sustainable_effort,
    take_zero,
)
from backpacking.pace.models import HikerProfile


class TestFatigueState:
    def test_a_fresh_hiker_is_rested_and_unslowed(self) -> None:
        state = FatigueState()
        assert state.is_rested
        assert state.speed_factor == pytest.approx(1.0)
        assert state.day == 0

    def test_fatigue_reduces_the_speed_factor(self) -> None:
        assert FatigueState(fatigue=0.2).speed_factor == pytest.approx(0.8)

    def test_conditioning_raises_it_back(self) -> None:
        assert FatigueState(fatigue=0.2, conditioning=0.1).speed_factor == pytest.approx(0.9)

    def test_the_factor_is_floored(self) -> None:
        assert FatigueState(fatigue=MAX_FATIGUE).speed_factor >= 0.5

    def test_out_of_range_fatigue_is_refused(self) -> None:
        with pytest.raises(PaceModelError, match="fatigue out of range"):
            FatigueState(fatigue=0.9)

    def test_out_of_range_conditioning_is_refused(self) -> None:
        with pytest.raises(PaceModelError, match="conditioning out of range"):
            FatigueState(conditioning=0.9)

    def test_a_negative_day_is_refused(self) -> None:
        with pytest.raises(PaceModelError, match="must not be negative"):
            FatigueState(day=-1)

    def test_repr_reads_as_percentages(self) -> None:
        state = FatigueState(day=6, fatigue=0.12, conditioning=0.07)
        assert repr(state) == "FatigueState(day 6, fatigue 12%, conditioning 7%)"


class TestAdvance:
    def test_a_neutral_day_leaves_fatigue_alone(self, hiker: HikerProfile) -> None:
        after = advance(FatigueState(fatigue=0.1), hiker, NEUTRAL_EFFORT_HOURS)
        assert after.fatigue == pytest.approx(0.1)

    def test_a_long_day_builds_fatigue(self, hiker: HikerProfile) -> None:
        after = advance(FatigueState(), hiker, 11.0)
        assert after.fatigue > 0.0
        assert after.fatigue == pytest.approx(4.0 * 0.022)

    def test_a_short_day_sheds_fatigue(self, hiker: HikerProfile) -> None:
        after = advance(FatigueState(fatigue=0.2), hiker, 4.0)
        assert after.fatigue < 0.2

    def test_fatigue_never_goes_below_zero(self, hiker: HikerProfile) -> None:
        after = advance(FatigueState(fatigue=0.01), hiker, 0.0)
        assert after.fatigue == pytest.approx(0.0)

    def test_fatigue_is_capped(self, hiker: HikerProfile) -> None:
        state = FatigueState()
        for _ in range(60):
            state = advance(state, hiker, 13.0)
        assert state.fatigue == pytest.approx(MAX_FATIGUE)

    def test_the_day_counter_advances(self, hiker: HikerProfile) -> None:
        after = advance(FatigueState(day=4, consecutive_days=4), hiker, 8.0)
        assert after.day == 5
        assert after.consecutive_days == 5

    def test_conditioning_builds_towards_the_ceiling(self, hiker: HikerProfile) -> None:
        state = FatigueState()
        for _ in range(hiker.conditioning_days):
            state = advance(state, hiker, NEUTRAL_EFFORT_HOURS)
        assert state.conditioning == pytest.approx(MAX_CONDITIONING)

    def test_conditioning_does_not_overshoot(self, hiker: HikerProfile) -> None:
        state = FatigueState()
        for _ in range(60):
            state = advance(state, hiker, NEUTRAL_EFFORT_HOURS)
        assert state.conditioning == pytest.approx(MAX_CONDITIONING)

    def test_a_hiker_who_arrives_conditioned_starts_at_the_ceiling(self) -> None:
        ready = HikerProfile(conditioning_days=0)
        assert advance(FatigueState(), ready, 8.0).conditioning == pytest.approx(MAX_CONDITIONING)

    def test_negative_effort_is_refused(self, hiker: HikerProfile) -> None:
        with pytest.raises(PaceModelError, match="must not be negative"):
            advance(FatigueState(), hiker, -1.0)


class TestZeroDays:
    def test_a_zero_sheds_a_lot_of_fatigue(self, hiker: HikerProfile) -> None:
        after = take_zero(FatigueState(fatigue=0.20), hiker)
        assert after.fatigue == pytest.approx(0.06)

    def test_a_zero_cannot_push_fatigue_negative(self, hiker: HikerProfile) -> None:
        assert take_zero(FatigueState(fatigue=0.05), hiker).fatigue == pytest.approx(0.0)

    def test_a_zero_keeps_conditioning(self, hiker: HikerProfile) -> None:
        after = take_zero(FatigueState(conditioning=0.08), hiker)
        assert after.conditioning == pytest.approx(0.08)

    def test_a_zero_resets_the_consecutive_run(self, hiker: HikerProfile) -> None:
        after = take_zero(FatigueState(consecutive_days=9), hiker)
        assert after.consecutive_days == 0
        assert after.day == 1

    def test_a_zero_recovers_more_than_an_easy_day(self, hiker: HikerProfile) -> None:
        start = FatigueState(fatigue=0.22)
        assert take_zero(start, hiker).fatigue < advance(start, hiker, 3.0).fatigue


class TestProject:
    def test_one_state_per_day(self, hiker: HikerProfile) -> None:
        states = project(hiker, [8.0] * 12)
        assert len(states) == 12
        assert [s.day for s in states] == list(range(1, 13))

    def test_a_hard_block_leaves_the_hiker_slower(self, hiker: HikerProfile) -> None:
        states = project(hiker, [11.0] * 8)
        assert states[-1].speed_factor < states[0].speed_factor

    def test_a_zero_in_the_middle_shows_up_as_recovery(self, hiker: HikerProfile) -> None:
        states = project(hiker, [11.0] * 10, zero_days={6})
        assert states[5].fatigue < states[4].fatigue

    def test_taking_a_zero_leaves_the_hiker_fresher_at_the_end(
        self, hiker: HikerProfile
    ) -> None:
        without = project(hiker, [11.0] * 4)
        with_rest = project(hiker, [11.0] * 4, zero_days={3})
        assert with_rest[-1].fatigue < without[-1].fatigue

    def test_a_steady_moderate_block_stays_rested(self, hiker: HikerProfile) -> None:
        states = project(hiker, [6.5] * 14)
        assert states[-1].is_rested
        assert states[-1].speed_factor > 1.0


class TestSustainableEffort:
    def test_a_fresh_hiker_can_use_the_whole_budget(self, hiker: HikerProfile) -> None:
        assert sustainable_effort(hiker, FatigueState()) == pytest.approx(9.0)

    def test_a_tired_hiker_gets_less(self, hiker: HikerProfile) -> None:
        tired = sustainable_effort(hiker, FatigueState(fatigue=0.25))
        assert tired < 9.0
        assert tired >= NEUTRAL_EFFORT_HOURS - 0.01

    def test_a_wrecked_hiker_falls_back_to_neutral(self, hiker: HikerProfile) -> None:
        assert sustainable_effort(hiker, FatigueState(fatigue=MAX_FATIGUE)) == pytest.approx(
            NEUTRAL_EFFORT_HOURS
        )

    def test_night_hiking_raises_the_ceiling(self) -> None:
        owl = HikerProfile(night_hiking=True)
        day = HikerProfile(night_hiking=False)
        assert sustainable_effort(owl, FatigueState()) > sustainable_effort(day, FatigueState())
