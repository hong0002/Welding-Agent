"""Synthetic CPU geometry only: no USD/Isaac import or process execution."""
import numpy as np
import pytest
from backend.services.offline_mesh_clearance import (
    TriangleSurface, surface_clearance, triangle_pairs, solid_angle_inside,
)


BASE=np.array([[0.,0.,0.],[2.,0.,0.],[0.,2.,0.]])


@pytest.mark.parametrize('second,expected',[
    (BASE+[0,0,3],3.),
    (np.array([[.25,.25,-1],[.25,.25,1],[1.,.25,0]]),0.),
    (BASE+[3,0,0],1.),
    (BASE+[.25,.25,0],0.),
    (np.array([[.25,.25,1],[.5,.25,1],[.25,.5,1]]),1.),
    (np.array([[.25,.25,1],[.25,.25,1],[.25,.25,1]]),1.),
])
def test_analytic_triangle_distance_and_symmetry(second,expected):
    for a,b in ((BASE,second),(second,BASE)):
        distances,ca,cb=triangle_pairs(a[None],b[None])
        assert np.sqrt(distances[0])==pytest.approx(expected,abs=1e-12)
        assert np.linalg.norm(ca[0]-cb[0])==pytest.approx(expected,abs=1e-12)


def test_edge_crossing_not_detectable_by_vertex_distances_alone():
    # Two coplanar skinny triangles form a crossing, all six vertices outside.
    a=np.array([[-2,-.1,0],[2,-.1,0],[2,.1,0]])
    b=np.array([[-.1,-2,0],[-.1,2,0],[.1,2,0]])
    assert triangle_pairs(a[None],b[None])[0][0]==pytest.approx(0,abs=1e-24)


def test_bvh_global_minimum_and_collision_count():
    verts=np.concatenate([BASE+[10*i,0,0] for i in range(24)])
    faces=np.arange(len(verts)).reshape(-1,3)
    a=TriangleSurface(verts,faces)
    b=TriangleSurface(BASE+[230,0,2],np.array([[0,1,2]]))
    report=surface_clearance(a,b)
    assert report['minimum_surface_distance_m']==pytest.approx(2)
    assert report['closest_triangle_a']==23
    assert report['intersecting_triangle_pair_count']==0
    b=TriangleSurface(BASE+[230,0,0],np.array([[0,1,2]]))
    report=surface_clearance(a,b)
    assert report['intersecting_triangle_pair_count']==1
    assert report['physical_clearance_threshold_m'] is None
    assert report['runtime_approved'] is False


def test_rigid_translation_does_not_change_surface_distance():
    a,b=BASE,BASE+[0,0,.00003]
    for offset in ([0,0,0],[.85,.175,.50]):
        r=surface_clearance(TriangleSurface(a+offset,np.array([[0,1,2]])),
                            TriangleSurface(b+offset,np.array([[0,1,2]])))
        assert r['minimum_surface_distance_m']==pytest.approx(.00003,abs=1e-15)
        assert r['intersecting_triangle_pair_count']==0


def test_closed_tetrahedron_winding_and_reversed_orientation():
    v=np.array([[0,0,0],[1,0,0],[0,1,0],[0,0,1.]])
    f=np.array([[0,2,1],[0,1,3],[0,3,2],[1,2,3]])
    p=np.array([[.1,.1,.1],[2,2,2]])
    w=solid_angle_inside(p,v[f])
    assert abs(w[0])==pytest.approx(1)
    assert abs(w[1])<1e-12
    assert solid_angle_inside(p,v[f[:,::-1]])==pytest.approx(-w)


def test_invalid_mesh_rejected():
    with pytest.raises(ValueError): TriangleSurface(BASE,np.array([[0,1,5]]))
    with pytest.raises(ValueError): TriangleSurface(BASE*np.nan,np.array([[0,1,2]]))
