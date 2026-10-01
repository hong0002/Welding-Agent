"""Synthetic offline mesh/XYZ tests; no external process, models, IK or Isaac."""
import numpy as np
import pytest

from backend.services.bpr_geometry_diagnostics import apply_rigid, candidate_transform, contact_line, seam_distances


def mesh(gap=0):
    theta=np.linspace(0,2*np.pi,16,endpoint=False)
    tube=np.array([[25*np.cos(t),25*np.sin(t),z] for z in (-50,50) for t in theta])
    plate=np.array([[x,y,z] for x in (-1.5,1.5) for y in (-125-gap,-25-gap) for z in (-50,50)])
    return np.vstack((tube,plate)),[np.arange(len(tube)),np.arange(len(tube),len(tube)+8)]


def test_contact_line_is_diagnostic_and_keeps_inputs_unchanged():
    vertices,components=mesh(); before=vertices.copy()
    contact=contact_line(vertices,components)
    assert np.allclose(contact.anchor_mm,[0,-25,0]) and np.allclose(contact.axis,[0,0,1])
    assert (contact.low_mm,contact.high_mm)==pytest.approx((-50,50)) and abs(contact.contact_gap_mm)<1e-12
    assert not contact.runtime_approved and np.array_equal(vertices,before)
    assert not contact.anchor_mm.flags.writeable


def test_gap_is_reported_without_false_readiness():
    vertices,components=mesh(2)
    contact=contact_line(vertices,components)
    assert contact.contact_gap_mm==pytest.approx(2) and not contact.runtime_approved


@pytest.mark.parametrize('sign',[-1,1])
def test_two_candidate_rolls_preserve_rigid_distances_and_nine_points(sign):
    vertices,components=mesh(); contact=contact_line(vertices,components)
    source=np.column_stack((np.linspace(655,679,150),np.linspace(-5,-8,150),np.linspace(304,235,150)))
    transform=candidate_transform(source,[0,1,0],contact,sign,[.85,.15,.50])
    assert np.isclose(np.linalg.det(transform[:3,:3]),1)
    gt=np.column_stack([np.interp(np.linspace(0,149,9),np.arange(150),source[:,j]) for j in range(3)])*.001
    prediction=gt+np.array([.04,.08,-.03]); gt_before=gt.copy(); pred_before=prediction.copy()
    transformed_gt,transformed_pred=apply_rigid(gt,transform),apply_rigid(prediction,transform)
    assert transformed_gt.shape==transformed_pred.shape==(9,3)
    assert np.allclose(np.linalg.norm(transformed_pred-transformed_gt,axis=1),np.linalg.norm(prediction-gt,axis=1),atol=1e-14)
    offset=np.array([.85,.15,.50])-contact.anchor_mm*.001
    diagnostic=seam_distances((apply_rigid(source*.001,transform)-offset)*1000,contact)
    assert diagnostic['max_mm']<1e-9 and diagnostic['weld_pass_threshold_mm'] is None
    assert not diagnostic['runtime_approved']
    assert np.array_equal(gt,gt_before) and np.array_equal(prediction,pred_before)


@pytest.mark.parametrize('change',['scale','reflection','nan','translation_row'])
def test_invalid_rigid_transform_rejected(change):
    transform=np.eye(4)
    if change=='scale':transform[0,0]=2
    if change=='reflection':transform[0,0]=-1
    if change=='nan':transform[0,3]=np.nan
    if change=='translation_row':transform[3,0]=.1
    with pytest.raises(ValueError):apply_rigid(np.zeros((9,3)),transform)


def test_invalid_source_basis_and_multiple_bodies_rejected():
    vertices,components=mesh(); contact=contact_line(vertices,components)
    with pytest.raises(ValueError):contact_line(vertices,[*components,np.arange(8)])
    with pytest.raises(ValueError):candidate_transform(np.zeros((9,3)),[0,1,0],contact,-1,[.85,.15,.5])
    with pytest.raises(ValueError):candidate_transform([[0,0,0],[0,1,0]],[0,1,0],contact,-1,[.85,.15,.5])
