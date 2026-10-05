"""Offline mapping tests: never instantiate Isaac or call an external model."""
import math
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest

from backend.urdf_import_compat import config_arguments


OPTIONS = dict(merge_fixed_joints=False, convex_decomp=False,
               import_inertia_tensor=True, fix_base=True, distance_scale=1.0,
               make_default_prim=False)


def test_native_options_and_evidenced_gains_are_preserved(tmp_path):
    urdf = tmp_path / 'rbpodo_description/robots/rb10.urdf'
    drives = {name: dict(type='acceleration', stiffness=625., damping=0., max_force=10.)
              for name in ('base', 'shoulder', 'elbow', 'wrist1', 'wrist2', 'wrist3')}
    config = config_arguments(urdf, tmp_path / 'owned', OPTIONS, drives)
    assert config['fix_base'] is True
    assert config['merge_fixed_joints'] is False
    assert config['collision_type'] == 'Convex Hull'
    assert config['run_asset_transformer'] is False
    assert config['run_multi_physics_conversion'] is False
    assert config['link_density'] is None
    assert config['usd_path'] == str((tmp_path / 'owned').resolve())
    assert config['ros_package_paths'][0]['path'] == str(urdf.parent.parent.resolve())
    for name in drives:
        assert config['joint_drive_type'][name] == 'acceleration'
        assert config['override_joint_stiffness'][name] * math.pi / 180. == pytest.approx(625.)
        assert config['override_joint_damping'][name] == 0.
    assert 'distance_scale' not in config  # No extra scaling operation.


@pytest.mark.parametrize('change', [dict(distance_scale=1000), dict(import_inertia_tensor=False), dict(make_default_prim=True)])
def test_no_silent_mapping_fallback(tmp_path, change):
    with pytest.raises(ValueError):
        config_arguments(tmp_path / 'rb10.urdf', tmp_path, OPTIONS | change, {})


def test_helper_has_no_scene_or_model_policy():
    source = Path('backend/urdf_import_compat.py').read_text(encoding='utf-8')
    assert 'SimulationApp(' not in source
    assert 'source_to_scene' not in source
    assert 'openai' not in source
    assert 'set_camera_view' not in source


def test_importer_api_references_owned_output_without_changing_stage_default(tmp_path, monkeypatch):
    """Fake USD/importer transport; no actual Isaac imports or playback."""
    from backend import urdf_import_compat as compat
    urdf = tmp_path / 'native/rbpodo_description/robots/rb10.urdf'
    urdf.parent.mkdir(parents=True)
    urdf.write_text('<robot name="rb10"><joint name="base" type="revolute"/></robot>')
    monkeypatch.setenv('WELD_SIM_URDF_OUTPUT_DIR', str(tmp_path / 'owned'))
    observed = {}
    drive = dict(type='acceleration', stiffness=625., damping=0., max_force=10.)
    monkeypatch.setattr(compat, 'read_native_drives', lambda path, joints: {'base': drive})
    class Attribute:
        def Set(self, value): pass
    class Prim:
        def GetName(self): return 'root_joint'
        def GetPath(self): return SimpleNamespace(pathString='/rb10/root_joint')
        def HasAPI(self, api): return True
        def ApplyAPI(self, api): observed['physics_schema'] = api
        def CreateAttribute(self, *args): return Attribute()
    class Reference:
        def AddReference(self, path, prim): observed['reference'] = (path, prim)
    class Robot:
        def GetReferences(self): return Reference()
    class Stage:
        def DefinePrim(self, path, type_name): observed['destination'] = path; return Robot()
        # No SetDefaultPrim method: calling it would fail the regression.
    class Importer:
        def __init__(self, config): observed['config'] = config
        def import_urdf(self): return str(tmp_path / 'owned/rb10.usda')
    importer_module = ModuleType('isaacsim.asset.importer.urdf')
    importer_module.URDFImporter = Importer
    importer_module.URDFImporterConfig = lambda **kwargs: kwargs
    monkeypatch.setitem(sys.modules, importer_module.__name__, importer_module)
    pxr = ModuleType('pxr')
    pxr.Usd = SimpleNamespace(Stage=SimpleNamespace(Open=lambda path: SimpleNamespace(
        GetDefaultPrim=lambda: SimpleNamespace(GetName=lambda: 'rb10', GetPath=lambda: '/rb10'))),
        PrimRange=lambda robot: [Prim()])
    pxr.Sdf = SimpleNamespace(ValueTypeNames=SimpleNamespace(Bool='bool', Int='int'))
    pxr.UsdGeom = SimpleNamespace()
    pxr.UsdPhysics = SimpleNamespace(ArticulationRootAPI='articulation', RevoluteJoint='joint')
    monkeypatch.setitem(sys.modules, 'pxr', pxr)
    omni = ModuleType('omni'); omni.__path__ = []
    omni.usd = ModuleType('omni.usd')
    omni.usd.get_context = lambda: SimpleNamespace(get_stage=lambda: Stage())
    monkeypatch.setitem(sys.modules, 'omni', omni)
    monkeypatch.setitem(sys.modules, 'omni.usd', omni.usd)
    assert compat.import_urdf_isaac61(urdf, None, OPTIONS) == '/rb10/root_joint'
    assert observed['destination'] == '/rb10'
    assert observed['reference'] == (str(tmp_path / 'owned/rb10.usda'), '/rb10')
    assert observed['physics_schema'] == 'PhysxArticulationAPI'
    assert observed['config']['usd_path'] == str(tmp_path / 'owned')
