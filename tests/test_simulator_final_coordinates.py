import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
from scipy.spatial import cKDTree
from scipy.spatial.transform import Rotation

from backend.apply_simulator_final_coordinate_fix import patched_source
from backend.contact_registration_determinism import (
    canonical_principal_basis, deterministic_nearest, deterministic_rigid_fit,
    registration_preference, prefer_registration,
)
from backend.simulator_final_experience import build_experience


FIXTURE=Path(__file__).parent/'fixtures/simulator_final'


def test_pca_signs_do_not_depend_on_svd_hemisphere():
    points=np.random.default_rng(8).normal(size=(24,3))*[9,3,1]
    expected=canonical_principal_basis(points)
    original=np.linalg.svd
    for signs in ([1,-1,1],[-1,1,-1],[-1,-1,-1]):
        def changed(*args,**kwargs):
            u,s,vt=original(*args,**kwargs)
            return u,s,np.diag(signs)@vt
        with patch('numpy.linalg.svd',side_effect=changed):
            np.testing.assert_allclose(canonical_principal_basis(points),expected,atol=1e-14)
    assert np.linalg.det(expected)==pytest.approx(1.)


def test_full_rank_fit_keeps_the_same_least_squares_transform():
    source=np.random.default_rng(4).normal(size=(20,3))
    wanted=Rotation.from_euler('xyz',[.4,-.7,.2]).as_matrix()
    target=source@wanted.T+[2,-4,8]
    rotation,translation=deterministic_rigid_fit(source,target)
    np.testing.assert_allclose(rotation,wanted,atol=1e-13)
    np.testing.assert_allclose(translation,[2,-4,8],atol=1e-13)


def test_collinear_update_preserves_unconstrained_roll():
    source=np.c_[np.zeros(16),np.zeros(16),np.linspace(-8,8,16)]
    target=source+[5,3,1]
    rotation,translation=deterministic_rigid_fit(source,target)
    np.testing.assert_allclose(rotation,np.eye(3),atol=1e-13)
    np.testing.assert_allclose(translation,[5,3,1],atol=1e-13)


def test_point_correspondence_tie_is_independent_of_contact_order():
    contact=np.array([[-1.,0,0],[1.,0,0],[10,0,0]])
    for order in ([0,1,2],[1,2,0],[2,0,1]):
        tree=cKDTree(contact[order])
        distance,indices=deterministic_nearest(tree,np.array([[0.,0,0],[9.,0,0]]))
        np.testing.assert_array_equal(tree.data[indices],[[1,0,0],[10,0,0]])
        np.testing.assert_allclose(distance,[1,1])


def test_tie_policy_does_not_override_a_better_fit():
    best=(.1,None,None,(9,))
    assert not prefer_registration(.11,(100,),best)
    assert prefer_registration(.1+1e-14,(10,),best)
    assert prefer_registration(.09,(-100,),best)


def test_audited_native_registration_preserves_py312_reference(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]/'backend'))
    data=json.loads((FIXTURE/'registration.json').read_text())
    source,contact=np.asarray(data['source'])[:,:3],np.asarray(data['contact'])
    namespace={}
    exec(patched_source((FIXTURE/'native_registration.py.txt').read_text()),namespace)
    fitted,rotation,translation,residual,_=namespace['register_path'](source,contact)
    reference=source@np.asarray(data['rotation']).T+data['translation']
    np.testing.assert_allclose(fitted,reference,atol=1e-8,rtol=0)
    np.testing.assert_allclose(rotation,np.asarray(data['rotation']),atol=2e-10,rtol=0)
    assert residual.max()<1.01
    assert np.linalg.det(rotation)==pytest.approx(1.,abs=1e-12)
    np.testing.assert_array_equal(source,np.asarray(data['source'])[:,:3])


def test_app_profile_only_removes_unused_sensor_dependencies(tmp_path):
    root=tmp_path/'isaac';apps=root/'apps';apps.mkdir(parents=True)
    base='[dependencies]\n"isaacsim.sensors.rtx" = {}\n"isaacsim.sensors.experimental.rtx" = {}\n"omni.hydra.rtx" = {}\n[settings]\nphysics.mode = "native"\n'
    python='[dependencies]\n"isaacsim.exp.base" = {}\n[settings.app.exts.folders]\n\'++\' = ["${app}", "${app}/../exts"]\n'
    (apps/'isaacsim.exp.base.kit').write_text(base)
    (apps/'isaacsim.exp.base.python.kit').write_text(python)
    profile=build_experience(root,tmp_path/'owned')
    native=(profile.parent/'weld.exp.base.kit').read_text()
    assert '"omni.hydra.rtx" = {}' in native
    assert 'physics.mode = "native"' in native
    assert '"isaacsim.sensors.rtx" = {}' not in native
    assert (apps/'isaacsim.exp.base.kit').read_text()==base
