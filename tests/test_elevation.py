"""Profile queries and the hysteresis gain filter."""

from __future__ import annotations

import pytest

from backpacking.errors import CorridorError
from backpacking.trail.elevation import (
    Climb,
    ElevationProfile,
    ElevationSample,
    grade_histogram,
)
from backpacking.units import Distance

# A clean saw tooth: up 1000, down 600, up 800, down 1200.
SAWTOOTH = [
    (0.0, 6000.0),
    (2.0, 7000.0),
    (4.0, 6400.0),
    (6.5, 7200.0),
    (10.0, 6000.0),
]

# The same shape with a few feet of altimeter jitter laid on top.
NOISY = [
    (0.0, 6000.0),
    (0.5, 6006.0),
    (1.0, 5998.0),
    (1.5, 6007.0),
    (2.0, 6000.0),
    (2.5, 6004.0),
    (3.0, 5997.0),
]


@pytest.fixture
def sawtooth() -> ElevationProfile:
    return ElevationProfile.from_pairs(SAWTOOTH)


class TestConstruction:
    def test_samples_are_sorted(self) -> None:
        profile = ElevationProfile.from_pairs([(5.0, 100.0), (0.0, 50.0), (2.0, 75.0)])
        assert [s.mile for s in profile.samples] == [0.0, 2.0, 5.0]

    def test_two_samples_are_the_minimum(self) -> None:
        with pytest.raises(CorridorError, match="at least two samples"):
            ElevationProfile.from_pairs([(0.0, 100.0)])

    def test_duplicate_miles_are_refused(self) -> None:
        with pytest.raises(CorridorError, match="duplicate mile"):
            ElevationProfile.from_pairs([(0.0, 100.0), (0.0, 120.0)])

    def test_a_negative_mile_is_refused(self) -> None:
        with pytest.raises(CorridorError, match="must not be negative"):
            ElevationSample(-1.0, Distance.feet(100))

    def test_length_and_bounds(self, sawtooth: ElevationProfile) -> None:
        assert len(sawtooth) == 5
        assert sawtooth.start_mile == pytest.approx(0.0)
        assert sawtooth.end_mile == pytest.approx(10.0)

    def test_repr(self, sawtooth: ElevationProfile) -> None:
        assert repr(sawtooth) == "ElevationProfile(5 samples, 0.0-10.0 mi)"


class TestElevationAt:
    def test_at_a_sample(self, sawtooth: ElevationProfile) -> None:
        assert sawtooth.elevation_at(4.0).in_feet == pytest.approx(6400.0)

    def test_between_samples(self, sawtooth: ElevationProfile) -> None:
        assert sawtooth.elevation_at(1.0).in_feet == pytest.approx(6500.0)
        assert sawtooth.elevation_at(3.0).in_feet == pytest.approx(6700.0)

    def test_clamps_below_the_start(self, sawtooth: ElevationProfile) -> None:
        assert sawtooth.elevation_at(-5.0).in_feet == pytest.approx(6000.0)

    def test_clamps_above_the_end(self, sawtooth: ElevationProfile) -> None:
        assert sawtooth.elevation_at(99.0).in_feet == pytest.approx(6000.0)


class TestGainAndLoss:
    def test_clean_profile_gain_is_the_sum_of_the_ascents(self, sawtooth: ElevationProfile) -> None:
        assert sawtooth.gain().in_feet == pytest.approx(1800.0)

    def test_clean_profile_loss_is_the_sum_of_the_descents(self, sawtooth: ElevationProfile) -> None:
        assert sawtooth.loss().in_feet == pytest.approx(1800.0)

    def test_net_change_matches_the_endpoints(self, sawtooth: ElevationProfile) -> None:
        net = sawtooth.gain().in_feet - sawtooth.loss().in_feet
        assert net == pytest.approx(0.0)

    def test_the_threshold_removes_altimeter_jitter(self) -> None:
        noisy = ElevationProfile.from_pairs(NOISY)
        assert noisy.gain(threshold_ft=10.0).in_feet == pytest.approx(0.0)

    def test_raw_gain_shows_how_much_noise_was_removed(self) -> None:
        noisy = ElevationProfile.from_pairs(NOISY)
        assert noisy.raw_gain().in_feet == pytest.approx(19.0)
        assert noisy.raw_gain().in_feet > noisy.gain().in_feet

    def test_a_zero_threshold_matches_the_raw_sum(self, sawtooth: ElevationProfile) -> None:
        assert sawtooth.gain(threshold_ft=0.0).in_feet == pytest.approx(
            sawtooth.raw_gain().in_feet
        )

    def test_a_negative_threshold_is_refused(self, sawtooth: ElevationProfile) -> None:
        with pytest.raises(CorridorError, match="must not be negative"):
            sawtooth.gain(threshold_ft=-1.0)

    def test_a_huge_threshold_collapses_to_the_net_change(self) -> None:
        profile = ElevationProfile.from_pairs([(0.0, 6000.0), (5.0, 6400.0), (10.0, 6900.0)])
        assert profile.gain(threshold_ft=5000.0).in_feet == pytest.approx(900.0)


class TestSliceAndResample:
    def test_slice_endpoints_are_interpolated(self, sawtooth: ElevationProfile) -> None:
        piece = sawtooth.slice(1.0, 3.0)
        assert piece.start_mile == pytest.approx(1.0)
        assert piece.end_mile == pytest.approx(3.0)
        assert piece.elevation_at(1.0).in_feet == pytest.approx(6500.0)
        assert piece.elevation_at(3.0).in_feet == pytest.approx(6700.0)

    def test_slice_keeps_the_interior_samples(self, sawtooth: ElevationProfile) -> None:
        piece = sawtooth.slice(1.0, 5.0)
        assert [s.mile for s in piece.samples] == [1.0, 2.0, 4.0, 5.0]

    def test_a_reversed_slice_is_refused(self, sawtooth: ElevationProfile) -> None:
        with pytest.raises(CorridorError, match="must advance"):
            sawtooth.slice(5.0, 2.0)

    def test_resample_spaces_evenly(self, sawtooth: ElevationProfile) -> None:
        even = sawtooth.resample(1.0)
        assert [s.mile for s in even.samples] == [float(i) for i in range(11)]

    def test_resample_always_lands_on_the_end(self) -> None:
        profile = ElevationProfile.from_pairs([(0.0, 100.0), (2.5, 200.0)])
        even = profile.resample(1.0)
        assert even.samples[-1].mile == pytest.approx(2.5)

    def test_resample_preserves_the_shape(self, sawtooth: ElevationProfile) -> None:
        even = sawtooth.resample(0.25)
        assert even.elevation_at(3.0).in_feet == pytest.approx(6700.0, abs=1.0)

    def test_a_non_positive_step_is_refused(self, sawtooth: ElevationProfile) -> None:
        with pytest.raises(CorridorError, match="step must be positive"):
            sawtooth.resample(0.0)


class TestClimbs:
    def test_the_sawtooth_yields_four_runs(self, sawtooth: ElevationProfile) -> None:
        found = sawtooth.climbs(min_change_ft=300.0)
        assert [(c.start_mile, c.end_mile) for c in found] == [
            (0.0, 2.0),
            (2.0, 4.0),
            (4.0, 6.5),
            (6.5, 10.0),
        ]

    def test_directions_alternate(self, sawtooth: ElevationProfile) -> None:
        found = sawtooth.climbs(min_change_ft=300.0)
        assert [c.is_ascent for c in found] == [True, False, True, False]

    def test_a_high_threshold_drops_the_small_runs(self, sawtooth: ElevationProfile) -> None:
        found = sawtooth.climbs(min_change_ft=900.0)
        assert all(abs(c.change.in_feet) >= 900.0 for c in found)
        assert len(found) < 4

    def test_climb_geometry(self) -> None:
        climb = Climb(
            start_mile=4.0,
            end_mile=6.5,
            start_elevation=Distance.feet(6400),
            end_elevation=Distance.feet(7200),
        )
        assert climb.length.in_miles == pytest.approx(2.5)
        assert climb.change.in_feet == pytest.approx(800.0)
        assert climb.feet_per_mile == pytest.approx(320.0)
        assert climb.is_ascent
        assert climb.average_grade == pytest.approx(0.0606, abs=0.001)
        assert repr(climb) == "Climb(4.0-6.5 mi, up 800 ft)"

    def test_a_descent_reports_downwards(self) -> None:
        climb = Climb(0.0, 2.0, Distance.feet(7000), Distance.feet(6000))
        assert not climb.is_ascent
        assert climb.average_grade < 0.0
        assert repr(climb) == "Climb(0.0-2.0 mi, down 1000 ft)"


class TestSteepestMile:
    def test_finds_the_hardest_mile(self) -> None:
        profile = ElevationProfile.from_pairs(
            [(0.0, 6000.0), (3.0, 6300.0), (4.0, 7500.0), (8.0, 7600.0)]
        )
        start, gain = profile.steepest_mile()
        assert start == pytest.approx(3.0, abs=0.11)
        assert gain == pytest.approx(1200.0, abs=60.0)

    def test_a_flat_profile_has_no_climb(self) -> None:
        profile = ElevationProfile.from_pairs([(0.0, 6000.0), (5.0, 6000.0)])
        _, gain = profile.steepest_mile()
        assert gain == pytest.approx(0.0)


class TestGradeHistogram:
    def test_a_steady_climb_lands_in_one_bin(self) -> None:
        profile = ElevationProfile.from_pairs([(0.0, 0.0), (10.0, 2640.0)])
        tally = grade_histogram(profile, [-0.10, -0.03, 0.03, 0.10])
        assert tally["+3%..+10%"] == pytest.approx(10.0, abs=0.2)
        assert sum(tally.values()) == pytest.approx(10.0, abs=0.2)

    def test_flat_ground_lands_in_the_middle_bin(self) -> None:
        profile = ElevationProfile.from_pairs([(0.0, 6000.0), (4.0, 6000.0)])
        tally = grade_histogram(profile, [-0.03, 0.03])
        assert tally["-3%..+3%"] == pytest.approx(4.0, abs=0.2)

    def test_a_steep_descent_falls_into_the_bottom_bin(self) -> None:
        profile = ElevationProfile.from_pairs([(0.0, 8000.0), (2.0, 5000.0)])
        tally = grade_histogram(profile, [-0.10, 0.10])
        assert tally["<-10%"] == pytest.approx(2.0, abs=0.2)

    def test_labels_cover_both_open_ends(self) -> None:
        profile = ElevationProfile.from_pairs([(0.0, 6000.0), (4.0, 6100.0)])
        tally = grade_histogram(profile, [-0.05, 0.05])
        assert set(tally) == {"<-5%", "-5%..+5%", ">+5%"}

    def test_edges_must_ascend(self) -> None:
        profile = ElevationProfile.from_pairs([(0.0, 0.0), (1.0, 100.0)])
        with pytest.raises(CorridorError, match="must ascend"):
            grade_histogram(profile, [0.10, -0.10])

    def test_at_least_one_edge_is_required(self) -> None:
        profile = ElevationProfile.from_pairs([(0.0, 0.0), (1.0, 100.0)])
        with pytest.raises(CorridorError, match="at least one bin edge"):
            grade_histogram(profile, [])
