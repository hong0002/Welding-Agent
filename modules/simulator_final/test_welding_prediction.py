"""Frame/units and actual-surface checks for XYZ-only VLA playback."""
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from welding_prediction import prediction_targets
from welding_path_marks import surface_band, polyline_distance, segment_distance


class PredictionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.source = np.array([[100., 200., 300., 0., 0., 0.],
                                [120., 200., 300., 0., 0., 90.]])
        self.gt = np.array([[.1, .2, .3], [.11, .2, .3], [.12, .2, .3]])
        self.predicted = self.gt + [0., .01, .002]
        self.transform = np.array([[0., -1., 0., .8], [1., 0., 0., .1],
                                   [0., 0., 1., .2], [0., 0., 0., 1.]])
        self.scene = np.array([[600., 200., 500., 10., 20., 30.],
                               [600., 220., 500., 40., 50., 60.]])
        self.metadata = dict(episode_id='L_PR_test', source_units='mm', scale_to_meters=.001,
                             coordinate_frame='source_robot_frame_unaligned_with_isaac')
        self.write_export()

    def write_export(self):
        (self.directory/'metadata.json').write_text(json.dumps(self.metadata))
        np.savez(self.directory/'trajectory.npz', predicted_path_m=self.predicted,
                 ground_truth_path_m=self.gt)

    def load(self):
        return prediction_targets(self.directory, 'L_PR_test', self.source, self.scene, self.transform)

    def test_identical_transform_preserves_prediction_error(self):
        poses, arrays, report = self.load()
        expected = self.predicted @ self.transform[:3, :3].T + self.transform[:3, 3]
        np.testing.assert_allclose(poses[:, :3] * .001, expected)
        np.testing.assert_allclose(poses[:, 3:], np.tile(self.scene[0, 3:], (3, 1)))
        np.testing.assert_allclose(np.linalg.norm(arrays['predicted_world_xyz_m'] -
                                                 arrays['ground_truth_world_xyz_m'], axis=1),
                                   np.linalg.norm(self.predicted-self.gt, axis=1))
        # In particular, do not snap the first predicted point onto GT.
        self.assertGreater(report['ade_mm'], 10)

    def test_arc_length_export_of_nonuniform_h5_is_accepted(self):
        self.source = np.array([[100, 200, 300, 0, 0, 0],
                                [102, 200, 300, 0, 0, 0],
                                [120, 200, 300, 0, 0, 0]], dtype=float)
        # Export midpoint is 110 mm, not the index-resampled midpoint 102 mm.
        _, _, report = self.load()
        self.assertEqual(report['gt_h5_resampling'], 'arc_length')
        self.assertLess(report['gt_h5_frame_error_mm_max'], 1e-6)

    def test_nonuniform_corner_keypoints_are_accepted_as_same_polyline(self):
        self.source = np.array([
            [0, 0, 0, 0, 0, 0], [2, 0, 0, 0, 0, 0], [5, 0, 0, 0, 0, 0],
            [5, 3, 0, 0, 0, 0], [5, 7, 0, 0, 0, 0], [5, 10, 0, 0, 0, 0],
            [15, 10, 0, 0, 0, 0], [25, 10, 0, 0, 0, 0],
        ], dtype=float)
        self.gt = np.array([[0, 0, 0], [5, 0, 0], [5, 10, 0], [25, 10, 0]], dtype=float) * .001
        self.predicted = self.gt.copy()
        self.write_export()
        _, _, report = self.load()
        self.assertEqual(report['gt_h5_resampling'], 'polyline_geometry')
        self.assertLess(report['gt_h5_frame_error_mm_max'], 1e-6)

    def test_wrong_frame_or_units_is_rejected(self):
        self.metadata['source_units'] = 'm'
        self.write_export()
        with self.assertRaisesRegex(ValueError, 'units/frame'):
            self.load()

    def test_wrong_gt_is_rejected(self):
        self.gt += .01
        self.write_export()
        with self.assertRaisesRegex(ValueError, 'does not match'):
            self.load()

    def test_nonfinite_prediction_is_rejected(self):
        self.predicted[1, 0] = np.nan
        self.write_export()
        with self.assertRaisesRegex(ValueError, 'finite'):
            self.load()

    def test_off_target_surface_is_available_without_painting_air(self):
        vertices = np.array([[-.03,-.03,0], [.03,-.03,0], [.03,.03,0], [-.03,.03,0]])
        gt = np.array([[-.02,0,0], [.02,0,0]])
        predicted = gt + [0,.02,0]
        triangles, _ = surface_band(vertices, [4], np.array([0,1,2,3]), gt,
                                    additional_paths=[predicted])
        centers = triangles.mean(axis=1)
        planned = polyline_distance(centers, gt) <= .007
        painted = polyline_distance(centers, predicted) <= .007
        self.assertTrue(np.any(painted & ~planned))
        self.assertFalse(np.any(segment_distance(centers, predicted[0]+[0,0,.03],
                                                 predicted[1]+[0,0,.03]) <= .007))


if __name__ == '__main__':
    unittest.main()
