import unittest
import numpy as np

from welding_scene_layout import tee_plate_round, fixture_supported, densify_poses


class TeeFixtureTests(unittest.TestCase):
    def test_plate_above_pipe_is_rotated_underneath_without_deformation(self):
        plate=np.array([[x,y,z] for z in (50.,53.) for y in (-50.,50.) for x in (-50.,50.)])
        theta=np.arange(8)*np.pi/4
        pipe=np.array([[25*np.cos(t),25*np.sin(t),z] for z in (-50.,50.) for t in theta])
        vertices=np.concatenate((plate,pipe))
        # Connectivity is sufficient for part detection; no rendering in this test.
        counts=[8,16];indices=list(range(24))
        upright,rotation,anchor,center,radius=tee_plate_round(vertices,counts,indices)
        self.assertAlmostEqual(np.linalg.det(rotation),1.)
        np.testing.assert_allclose(rotation@rotation.T,np.eye(3),atol=1e-12)
        self.assertAlmostEqual(upright[:8,2].max(),upright[8:,2].min())
        self.assertLess(upright[:8,2].mean(),upright[8:,2].mean())
        np.testing.assert_allclose(np.linalg.norm(upright[:,None]-upright,axis=2),
                                   np.linalg.norm(vertices[:,None]-vertices,axis=2))
        self.assertAlmostEqual(radius,25.)
        np.testing.assert_allclose(anchor-center,[0.,-25.,0.],atol=1e-10)

    def test_densification_preserves_corners_and_original_parameters(self):
        poses = np.array([[0, 0, 0, 0, 0, 0], [12, 0, 0, 0, 0, 9],
                          [12, 7, 0, 0, 0, 9]], dtype=float)
        dense, parameters = densify_poses(poses)
        np.testing.assert_allclose(dense[np.isclose(parameters, 1)][0], poses[1])
        np.testing.assert_allclose(dense[[0, -1]], poses[[0, -1]])
        self.assertLessEqual(np.linalg.norm(np.diff(dense[:, :3], axis=0), axis=1).max(), 5.)
        self.assertAlmostEqual(np.linalg.norm(np.diff(dense[:, :3], axis=0), axis=1).sum(), 19.)

    def test_menu_and_preparation_share_supported_families(self):
        self.assertTrue(fixture_supported('T_PR_06_0003'))
        self.assertTrue(fixture_supported('L_PR_03_0001'))
        self.assertTrue(fixture_supported('T_RR_03_0001'))
        self.assertFalse(fixture_supported('X_RR_03_0001'))


if __name__=='__main__': unittest.main()
