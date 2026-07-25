"""Unit tests for the pure-Python trajectory math.

Runs outside of Maya:

    python -m unittest tests.test_trajectory
"""

from __future__ import annotations

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from paint_projectile import trajectory as traj  # noqa: E402


class SolveBallisticTests(unittest.TestCase):

    def test_reachable_target_low_arc_lands(self):
        # Target 10 units away horizontally, at same height.
        start = (0.0, 0.0, 0.0)
        target = (10.0, 0.0, 0.0)
        v0 = traj.solve_ballistic(start, target, speed=15.0, gravity=9.8)
        # Simulate a fine-grained flight and confirm we pass near the target.
        positions = traj.generate_positions(start, v0, gravity=9.8,
                                            num_frames=241, fps=240.0)
        # Closest approach in the XZ plane should be tiny.
        best = min(math.hypot(p[0] - target[0], p[2] - target[2])
                   for p in positions
                   if abs(p[1] - target[1]) < 0.1)
        self.assertLess(best, 0.1)

    def test_unreachable_target_falls_back_to_direct_aim(self):
        # Way too far for the given speed.
        start = (0.0, 0.0, 0.0)
        target = (1000.0, 0.0, 0.0)
        v0 = traj.solve_ballistic(start, target, speed=5.0, gravity=9.8)
        # Direct-aim: velocity direction points at the target.
        length = math.sqrt(sum(v * v for v in v0))
        self.assertAlmostEqual(length, 5.0, places=5)
        self.assertGreater(v0[0], 0.0)
        self.assertAlmostEqual(v0[1], 0.0, places=5)

    def test_zero_gravity_direct_aim(self):
        start = (0.0, 0.0, 0.0)
        target = (3.0, 4.0, 0.0)
        v0 = traj.solve_ballistic(start, target, speed=10.0, gravity=0.0)
        # Should point directly at target with magnitude=speed.
        self.assertAlmostEqual(v0[0], 6.0, places=5)
        self.assertAlmostEqual(v0[1], 8.0, places=5)
        self.assertAlmostEqual(v0[2], 0.0, places=5)

    def test_vertical_target(self):
        start = (0.0, 0.0, 0.0)
        target = (0.0, 5.0, 0.0)
        v0 = traj.solve_ballistic(start, target, speed=12.0, gravity=9.8)
        self.assertAlmostEqual(v0[0], 0.0)
        self.assertAlmostEqual(v0[2], 0.0)
        self.assertAlmostEqual(v0[1], 12.0)


class GeneratePositionsTests(unittest.TestCase):

    def test_first_sample_is_start(self):
        positions = traj.generate_positions((1.0, 2.0, 3.0), (0.0, 0.0, 0.0),
                                             gravity=9.8, num_frames=5)
        self.assertEqual(positions[0], (1.0, 2.0, 3.0))

    def test_gravity_pulls_down(self):
        positions = traj.generate_positions((0.0, 0.0, 0.0), (0.0, 0.0, 0.0),
                                             gravity=9.8, num_frames=25, fps=24.0)
        # After 1 second of pure gravity: y = -0.5 * 9.8 * 1^2 = -4.9
        # Frame 24 corresponds to t = 1s.
        self.assertAlmostEqual(positions[24][1], -4.9, places=5)

    def test_empty_range(self):
        self.assertEqual(traj.generate_positions((0, 0, 0), (0, 0, 0),
                                                  gravity=9.8, num_frames=0), [])


class VelocityTests(unittest.TestCase):

    def test_uniform_motion(self):
        # Straight-line 1 unit per frame at 24fps -> 24 units/sec.
        positions = [(float(i), 0.0, 0.0) for i in range(5)]
        vels = traj.central_difference_velocity(positions, dt=1.0 / 24.0)
        for v in vels:
            self.assertAlmostEqual(v[0], 24.0, places=4)
            self.assertAlmostEqual(v[1], 0.0)
            self.assertAlmostEqual(v[2], 0.0)

    def test_single_frame(self):
        self.assertEqual(traj.central_difference_velocity([(1.0, 2.0, 3.0)], 1.0),
                         [(0.0, 0.0, 0.0)])


class FpsMappingTests(unittest.TestCase):

    def test_known_units(self):
        self.assertEqual(traj.frames_per_second_from_maya_unit("film"), 24.0)
        self.assertEqual(traj.frames_per_second_from_maya_unit("ntsc"), 30.0)
        self.assertEqual(traj.frames_per_second_from_maya_unit("pal"), 25.0)

    def test_numeric_units(self):
        self.assertAlmostEqual(traj.frames_per_second_from_maya_unit("120fps"), 120.0)

    def test_unknown_fallback(self):
        self.assertEqual(traj.frames_per_second_from_maya_unit("totally-made-up"), 24.0)


if __name__ == "__main__":
    unittest.main()
