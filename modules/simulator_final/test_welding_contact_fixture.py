import unittest

import numpy as np
from scipy.spatial.transform import Rotation

from welding_contact_fixture import contact_geometry, register_path, rigid_fit, build_contact_scene
from welding_scene_layout import fixture_supported


class ContactFixtureTests(unittest.TestCase):
    @staticmethod
    def boxes(gap=0.):
        import trimesh
        first = trimesh.creation.box(extents=[20, 40, 4])
        second = first.copy()
        second.apply_translation([20 + gap, 0, 0])
        mesh = trimesh.util.concatenate([first, second])
        return mesh.vertices, [3] * len(mesh.faces), mesh.faces.ravel().tolist()

    def test_all_dataset_joint_and_material_families(self):
        for joint in ('B', 'C', 'E', 'L', 'T'):
            for material in ('PP', 'PR', 'PS', 'RR', 'RS', 'SS'):
                self.assertTrue(fixture_supported(f'{joint}_{material}_03_0001'))
        self.assertFalse(fixture_supported('unknown_03_0001'))

    def test_contact_is_on_actual_shared_boundary(self):
        vertices, counts, indices = self.boxes()
        original = vertices.copy()
        contact, gap, _ = contact_geometry(vertices, counts, indices)
        self.assertAlmostEqual(gap, 0.)
        np.testing.assert_allclose(contact[:, 0], 10., atol=1e-4)
        self.assertGreater(np.ptp(contact[:, 1]), 39.)
        np.testing.assert_array_equal(vertices, original)

    def test_cad_clearance_reported_without_closing_gap(self):
        vertices, counts, indices = self.boxes(gap=5.)
        contact, gap, _ = contact_geometry(vertices, counts, indices)
        self.assertAlmostEqual(gap, 5.)
        np.testing.assert_allclose(contact[:, 0], 12.5, atol=1e-4)

    def test_scene_preserves_cad_up_and_raw_path_shape(self):
        vertices, counts, indices = self.boxes()
        source = np.column_stack((np.linspace(50., 75., 8), np.full(8, 120.), np.full(8, 400.), np.zeros((8, 3))))
        poses, arrays, report = build_contact_scene(vertices, counts, indices, 'B_PP_test', source)
        rotation = np.array(report['obj_to_world_rotation'])
        np.testing.assert_allclose(rotation @ [0, 0, 1], [0, 0, 1], atol=1e-12)
        self.assertAlmostEqual(np.linalg.norm(poses[-1,:3]-poses[0,:3]), 25.)
        np.testing.assert_array_equal(arrays['source_tcp_pose_xyz_mm_rpy_deg'], source)
        self.assertTrue(report['original_cad_up_preserved'])

    def test_proper_rigid_fit_preserves_prediction_errors(self):
        source = np.array([[0., 0, 0], [10, 0, 0], [10, 20, 0], [15, 23, 5]])
        expected = Rotation.from_euler('xyz', [24, -35, 76], degrees=True).as_matrix()
        target = source @ expected.T + [100, -40, 600]
        rotation, translation = rigid_fit(source, target)
        np.testing.assert_allclose(source @ rotation.T + translation, target, atol=1e-10)
        self.assertAlmostEqual(np.linalg.det(rotation), 1.)
        prediction = source + np.array([[1, 2, 3], [4, -2, 0], [2, 2, 5], [0, 0, 10]])
        predicted_world = prediction @ rotation.T + translation
        np.testing.assert_allclose(np.linalg.norm(prediction-source, axis=1),
                                   np.linalg.norm(predicted_world-target, axis=1), atol=1e-10)

    def test_horizontal_round_butt_stands_without_stretching_short_gt(self):
        import trimesh
        first = trimesh.creation.annulus(r_min=47, r_max=50, height=300, sections=64)
        second = first.copy()
        second.apply_translation([0, 0, 300])
        assembly = trimesh.util.concatenate([first, second])
        assembly.apply_transform(trimesh.transformations.rotation_matrix(np.pi/2, [0, 1, 0]))
        angle = np.linspace(0, np.pi, 30)
        source = np.c_[5*np.cos(angle)+500, 5*np.sin(angle)-180, np.full(30, 450), np.zeros((30, 3))]
        poses, arrays, report = build_contact_scene(assembly.vertices, [3]*len(assembly.faces),
                                                   assembly.faces.ravel().tolist(), 'B_RR_M_test', source)
        world = arrays['workpiece_vertices_world_m']
        np.testing.assert_allclose(np.ptp(world, axis=0)[2], .6, atol=1e-8)
        rim = arrays['cad_contact_curve_world_m']
        self.assertLess(np.ptp(rim[:, 2]), 1e-8)
        self.assertGreater(np.ptp(rim[:, 0]), .099)
        self.assertGreater(np.ptp(rim[:, 1]), .099)
        np.testing.assert_allclose(rim[0], rim[-1])
        np.testing.assert_allclose(np.linalg.norm(np.diff(poses[:, :3], axis=0), axis=1),
                                   np.linalg.norm(np.diff(source[:, :3], axis=0), axis=1), atol=1e-8)
        rigid = arrays['source_to_scene']
        np.testing.assert_allclose(poses[:, :3]*.001, source[:, :3]*.001 @ rigid[:3, :3].T+rigid[:3, 3])
        self.assertLess(report['source_path_to_full_rim_length_ratio'], .1)
        self.assertFalse(report['original_cad_up_preserved'])

    def test_length_mismatch_is_not_scaled_or_hidden(self):
        source = np.column_stack((np.linspace(-30, 30, 25), np.zeros((25, 2))))
        contact = np.column_stack((np.linspace(-10, 10, 41), np.zeros((41, 2))))
        fitted, rotation, _, residual, _ = register_path(source, contact)
        self.assertGreater(residual.max(), 19.)
        self.assertAlmostEqual(np.linalg.norm(fitted[-1]-fitted[0]), 60.)
        np.testing.assert_allclose(rotation @ rotation.T, np.eye(3), atol=1e-10)


if __name__ == '__main__':
    unittest.main()
