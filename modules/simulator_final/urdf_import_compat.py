"""Isaac 6.1 URDF API compatibility, without scene/trajectory policy changes.

Lazy Isaac imports keep offline tests lightweight. The native robot's previously
exported USD supplies drive defaults; these are evidence, not tuned new gains.
This file is also copied unchanged beside simulator_final's native entrypoint.
"""
from __future__ import annotations

import math
import os
from pathlib import Path
import tempfile
import xml.etree.ElementTree as ET


def config_arguments(urdf_path, output_directory, options, drives):
    """Map the supported native options to the installed 3.11.10 dataclass."""
    if options['distance_scale'] != 1.0 or not options['import_inertia_tensor']:
        raise ValueError('This native compatibility mapping requires meter scale and source inertia')
    if options['make_default_prim']:
        raise ValueError('This native compatibility mapping does not replace the stage default prim')
    urdf = Path(urdf_path).resolve()
    # New gains use Nm/rad; the existing USD records Nm/degree. Its importer
    # applies the inverse conversion, restoring exactly the previous USD gains.
    return dict(
        urdf_path=str(urdf), usd_path=str(Path(output_directory).resolve()),
        merge_fixed_joints=options['merge_fixed_joints'], merge_mesh=False,
        fix_base=options['fix_base'], collision_from_visuals=False,
        collision_type='Convex Decomposition' if options['convex_decomp'] else 'Convex Hull',
        allow_self_collision=False, link_density=None,
        ros_package_paths=[dict(name='rbpodo_description', path=str(urdf.parent.parent))],
        joint_drive_type={name: value['type'] for name, value in drives.items()},
        joint_target_type='position',
        override_joint_stiffness={name: value['stiffness'] * 180.0 / math.pi for name, value in drives.items()},
        override_joint_damping={name: value['damping'] * 180.0 / math.pi for name, value in drives.items()},
        # The native renderer uses PhysX and a single robot reference, not the
        # new importer's optional multi-engine asset package/variant restructuring.
        run_asset_transformer=False, run_multi_physics_conversion=False,
    )


def read_native_drives(reference_path, joint_names):
    from pxr import Usd, UsdPhysics

    reference = Usd.Stage.Open(str(reference_path))
    result = {}
    for prim in reference.Traverse():
        if prim.GetName() not in joint_names or not prim.IsA(UsdPhysics.RevoluteJoint):
            continue
        drive = UsdPhysics.DriveAPI(prim, 'angular')
        result[prim.GetName()] = dict(type=str(drive.GetTypeAttr().Get()),
            stiffness=float(drive.GetStiffnessAttr().Get()),
            damping=float(drive.GetDampingAttr().Get()), max_force=float(drive.GetMaxForceAttr().Get()))
    if set(result) != set(joint_names):
        raise RuntimeError('Native drive evidence is incomplete')
    return result


def import_urdf_isaac61(urdf_path, destination_prim, existing_native_options):
    """Convert into owned storage, reference into the current stage, return root.

    No SimulationApp is created here. No source URDF/mesh/tool or native scene
    evidence is overwritten. Native caller keeps all placement and playback code.
    """
    from isaacsim.asset.importer.urdf import URDFImporter, URDFImporterConfig
    import omni.usd
    from pxr import Sdf, Usd, UsdGeom, UsdPhysics

    urdf = Path(urdf_path).resolve()
    native_root = urdf.parents[2]
    xml = ET.parse(urdf).getroot()
    joints = [joint.attrib['name'] for joint in xml.findall('joint') if joint.attrib['type'] == 'revolute']
    drives = read_native_drives(native_root / 'rb10_trajectory_with_ATU01035.usda', joints)
    output = os.environ.get('WELD_SIM_URDF_OUTPUT_DIR') or tempfile.mkdtemp(prefix='weld_urdf_isaac61_')
    config = URDFImporterConfig(**config_arguments(urdf, output, existing_native_options, drives))
    usd_path = URDFImporter(config).import_urdf()
    asset = Usd.Stage.Open(usd_path)
    default = asset.GetDefaultPrim()
    stage = omni.usd.get_context().get_stage()
    destination_prim = destination_prim or '/' + default.GetName()
    robot = stage.DefinePrim(destination_prim, 'Xform')
    robot.GetReferences().AddReference(str(usd_path), default.GetPath())
    roots = []
    for prim in Usd.PrimRange(robot):
        if prim.HasAPI(UsdPhysics.ArticulationRootAPI):
            # Keep the native PhysX backend. The new converter's Newton metadata
            # does not select a different simulator engine for this renderer.
            prim.ApplyAPI('PhysxArticulationAPI')
            prim.CreateAttribute('physxArticulation:enabledSelfCollisions', Sdf.ValueTypeNames.Bool).Set(False)
            prim.CreateAttribute('physxArticulation:solverPositionIterationCount', Sdf.ValueTypeNames.Int).Set(32)
            prim.CreateAttribute('physxArticulation:solverVelocityIterationCount', Sdf.ValueTypeNames.Int).Set(1)
            roots.append(prim.GetPath().pathString)
        if prim.GetName() in drives and prim.IsA(UsdPhysics.RevoluteJoint):
            UsdPhysics.DriveAPI(prim, 'angular').GetMaxForceAttr().Set(drives[prim.GetName()]['max_force'])
    if len(roots) != 1:
        raise RuntimeError('URDF import did not produce one native articulation root')
    # Setting the asset's default prim is a converter detail. Do not set the
    # receiving stage's default prim (native make_default_prim=False).
    print('[URDF_COMPAT] Isaac 6.1 importer; fixed base; meter scale; native drives; root=' + roots[0], flush=True)
    return roots[0]
