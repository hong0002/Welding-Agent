import struct
import numpy as np
import pytest
from backend.services.preview_mesh import load_visual_mesh


def dae(tmp_path):
    path=tmp_path/'visual.dae'
    path.write_text('''<COLLADA xmlns="http://www.collada.org/2005/11/COLLADASchema">
    <asset><unit meter="0.001"/><up_axis>Z_UP</up_axis></asset>
    <library_geometries><geometry id="g"><mesh>
      <source id="p"><float_array count="9">0 0 0 1000 0 0 0 1000 0</float_array>
        <technique_common><accessor stride="3" count="3"/></technique_common></source>
      <vertices id="v"><input semantic="POSITION" source="#p"/></vertices>
      <triangles count="1"><input semantic="NORMAL" offset="0" source="#n"/>
        <input semantic="VERTEX" offset="1" source="#v"/><p>9 0 9 1 9 2</p></triangles>
      <triangles count="1"><input semantic="VERTEX" offset="0" source="#v"/><p>2 1 0</p></triangles>
    </mesh></geometry></library_geometries>
    <library_visual_scenes><visual_scene id="s"><node>
      <matrix>0 -1 0 2000 1 0 0 3000 0 0 1 4000 0 0 0 1</matrix>
      <instance_geometry url="#g"/>
    </node></visual_scene></library_visual_scenes><scene><instance_visual_scene url="#s"/></scene>
    </COLLADA>''')
    return path


def test_dae_node_matrix_units_interleaved_indices_material_batches(tmp_path):
    path=dae(tmp_path);before=path.read_bytes();v,c,i=load_visual_mesh(path)
    np.testing.assert_array_equal(v,[[2,3,4],[2,4,4],[1,3,4]])
    assert c==[3,3] and i==[0,1,2,2,1,0]
    assert path.read_bytes()==before  # No source rewrite.


@pytest.mark.parametrize('change',['up','controller','external','indices'])
def test_unaudited_visual_contract_rejected(tmp_path,change):
    path=dae(tmp_path);text=path.read_text()
    if change=='up':text=text.replace('Z_UP','Y_UP')
    if change=='controller':text=text.replace('<asset>','<library_controllers><controller/></library_controllers><asset>')
    if change=='external':text=text.replace('url="#g"','url="https://example.invalid/mesh"')
    if change=='indices':text=text.replace('9 2','9 8')
    path.write_text(text)
    with pytest.raises(ValueError):load_visual_mesh(path)


def test_binary_stl_supported_separately(tmp_path):
    path=tmp_path/'collision.stl'
    path.write_bytes(b'fixture'.ljust(80,b' ')+struct.pack('<I',1)+struct.pack('<12fH',0,0,1,0,0,0,1,0,0,0,1,0,0))
    v,c,i=load_visual_mesh(path)
    np.testing.assert_array_equal(v,[[0,0,0],[1,0,0],[0,1,0]])
    assert c==[3] and i==[0,1,2]
