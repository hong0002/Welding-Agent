"""Read-only mesh reader for the audited RB10 static DAE/STL visual assets.

COLLADA 1.4 matrix elements serialize rows of a column-vector transform:
https://www.khronos.org/files/collada_spec_1_4.pdf
No texture downloads, controllers, animations or external resource resolution.
"""
from pathlib import Path
import xml.etree.ElementTree as ET
import numpy as np


def load_visual_mesh(path):
    path = Path(path)
    if path.suffix.lower() == '.stl':
        raw = path.read_bytes(); count = int.from_bytes(raw[80:84], 'little')
        if len(raw) != 84 + 50*count or not count:
            raise ValueError('Unsupported binary STL layout')
        dtype = np.dtype([('normal','<f4',(3,)),('vertices','<f4',(3,3)),('attr','<u2')])
        vertices = np.frombuffer(raw,dtype=dtype,count=count,offset=84)['vertices'].reshape(-1,3).astype(float)
        return vertices, [3]*count, list(range(len(vertices)))
    if path.suffix.lower() != '.dae':
        raise ValueError('Only audited DAE/STL visual meshes supported')
    tree = ET.parse(path).getroot()
    for element in tree.iter():
        element.tag = element.tag.split('}')[-1]
    if tree.findtext('asset/up_axis') != 'Z_UP' or tree.find('library_controllers/*') is not None or tree.find('library_animations/*') is not None:
        raise ValueError('Preview supports static Z_UP visual assets only')
    unit = float(tree.find('asset/unit').get('meter'))
    if not np.isfinite(unit) or unit <= 0:
        raise ValueError('Invalid mesh units')
    geometries = {g.get('id'):g for g in tree.findall('library_geometries/geometry')}
    scene_ref = tree.find('scene/instance_visual_scene').get('url')
    scene = next(v for v in tree.findall('library_visual_scenes/visual_scene') if '#'+v.get('id')==scene_ref)
    all_vertices, all_indices, counts = [], [], []
    offset = 0

    def node_mesh(node, parent):
        nonlocal offset
        local = np.eye(4)
        for element in node:
            if element.tag == 'matrix':
                matrix = np.fromstring(element.text,sep=' ').reshape(4,4)
                if not np.isfinite(matrix).all() or not np.allclose(matrix[3],[0,0,0,1]):
                    raise ValueError('Invalid COLLADA transform')
                local = local @ matrix
            elif element.tag in {'rotate','translate','scale','lookat','skew','instance_node','instance_controller'}:
                raise ValueError('Unaudited COLLADA node transform')
        transform = parent @ local
        for instance in node.findall('instance_geometry'):
            ref = instance.get('url')
            if not ref.startswith('#'):
                raise ValueError('External COLLADA resource forbidden')
            mesh = geometries[ref[1:]].find('mesh')
            sources = {}
            for source in mesh.findall('source'):
                accessor = source.find('technique_common/accessor')
                array = source.find('float_array')
                if accessor is None or array is None:
                    continue
                stride = int(accessor.get('stride','1')); start = int(accessor.get('offset','0')); count = int(accessor.get('count'))
                values = np.fromstring(array.text,sep=' ')
                if len(values) != int(array.get('count')) or start+stride*count > len(values):
                    raise ValueError('Invalid COLLADA source/accessor')
                sources[source.get('id')] = values[start:start+stride*count].reshape(count,stride)
            vertices_refs = {v.get('id'):v.find("input[@semantic='POSITION']").get('source')[1:] for v in mesh.findall('vertices')}
            source_offsets = {}
            for primitive in mesh:
                if primitive.tag not in {'source','vertices','triangles'}:
                    raise ValueError('Only native triangulated visual meshes supported')
                if primitive.tag != 'triangles':
                    continue
                inputs = primitive.findall('input'); stride = max(int(i.get('offset','0')) for i in inputs)+1
                position = next(i for i in inputs if i.get('semantic') in {'VERTEX','POSITION'})
                source_id = position.get('source')[1:]
                if position.get('semantic')=='VERTEX':source_id=vertices_refs[source_id]
                vertices = sources[source_id]
                if vertices.shape[1]!=3 or not np.isfinite(vertices).all():
                    raise ValueError('Invalid visual XYZ')
                numbers = np.fromstring(primitive.findtext('p'),sep=' ',dtype=np.int64)
                triangle_count = int(primitive.get('count'))
                if len(numbers)!=triangle_count*3*stride:
                    raise ValueError('Invalid triangulated index count')
                indices = numbers.reshape(-1,stride)[:,int(position.get('offset','0'))]
                if indices.min()<0 or indices.max()>=len(vertices):
                    raise ValueError('Visual mesh index out of range')
                world = (vertices @ transform[:3,:3].T + transform[:3,3])*unit
                if source_id not in source_offsets:
                    source_offsets[source_id] = offset
                    all_vertices.append(world);offset+=len(vertices)
                all_indices.extend((indices+source_offsets[source_id]).tolist())
                counts.extend([3]*triangle_count)
        for child in node.findall('node'):
            node_mesh(child,transform)
    for node in scene.findall('node'):
        node_mesh(node,np.eye(4))
    if not counts:
        raise ValueError('Visual asset contains no triangles')
    return np.concatenate(all_vertices), counts, all_indices
