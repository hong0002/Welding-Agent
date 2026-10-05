import sys as _release_sys
from pathlib import Path as _ReleasePath
_release_sys.path.insert(0, str(_ReleasePath(__file__).resolve().parents[1]))
from backend.services.project_paths import native_parent
"""Operator-only read-only CAD extraction; never imported by the web/runtime.

Run with Isaac's python.exe -I -S -B, not python.bat or SimulationApp. Outputs
are restricted to a fresh Welding-Agent-owned audit directory. No stage is saved.
"""
import hashlib
import json
import os
from pathlib import Path
import sys


def main():
    project = Path(__file__).resolve().parents[1]
    output = Path(sys.argv[1]).resolve()
    if not output.is_relative_to(project / ".cache/bpr-tool-clearance") or output.exists():
        raise ValueError("A fresh owned audit directory is required")
    isaac = Path("D:/isaacsim")
    libraries = isaac / "extscache/omni.usd.libs-1.0.3+00c488ae.wx64.r.cp312"
    # Keep DLL directory handles alive. Isolated/no-site Python excludes all
    # Isaac sitecustomize/extension/app bootstrapping and inherited PYTHONPATH.
    handles = [os.add_dll_directory(str(p)) for p in (
        libraries / "bin", isaac / "kit/kernel/plugins", isaac / "kit")]
    sys.path.insert(0, str(libraries))
    from pxr import Usd, UsdGeom, Gf

    source = native_parent(project) / "simulator/ATU01035_welding_tool.usd"
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    stage = Usd.Stage.Open(str(source))
    if not stage:
        raise ValueError("USD reader did not open the tool")
    cache = UsdGeom.XformCache(Usd.TimeCode.Default())
    hierarchy, meshes = [], []
    # CAD converters can instance their geometry: default Traverse omits the
    # instance-proxy children. Traverse proxies, retaining their composed xforms.
    for prim in Usd.PrimRange(stage.GetPseudoRoot(), Usd.TraverseInstanceProxies()):
        xform = UsdGeom.Xformable(prim)
        if xform:
            hierarchy.append(dict(path=str(prim.GetPath()), type=str(prim.GetTypeName()),
                instance=prim.IsInstance(), instance_proxy=prim.IsInstanceProxy(),
                reset_xform_stack=xform.GetResetXformStack(),
                operations=[dict(name=str(op.GetOpName()), value=str(op.Get()))
                            for op in xform.GetOrderedXformOps()],
                local_to_asset_row_matrix=[list(row) for row in cache.GetLocalToWorldTransform(prim)]))
        if not prim.IsA(UsdGeom.Mesh):
            continue
        mesh = UsdGeom.Mesh(prim)
        points = mesh.GetPointsAttr().Get()
        matrix = cache.GetLocalToWorldTransform(prim)
        meshes.append(dict(path=str(prim.GetPath()),
            local_points=[list(p) for p in points],
            asset_points=[list(matrix.Transform(Gf.Vec3d(*p))) for p in points],
            face_counts=list(mesh.GetFaceVertexCountsAttr().Get()),
            face_indices=list(mesh.GetFaceVertexIndicesAttr().Get()),
            holes=list(mesh.GetHoleIndicesAttr().Get() or []),
            subdivision=str(mesh.GetSubdivisionSchemeAttr().Get()),
            orientation=str(mesh.GetOrientationAttr().Get()),
            purpose=str(mesh.GetPurposeAttr().Get()),
            visibility=str(UsdGeom.Imageable(prim).ComputeVisibility()),
            double_sided=mesh.GetDoubleSidedAttr().Get(),
            points_time_samples=mesh.GetPointsAttr().GetTimeSamples()))
    forbidden = [m for m in sys.modules if m == "isaacsim" or m.startswith("omni")
                 or "simulation_app" in m.lower()]
    if forbidden:
        raise RuntimeError("Unexpected simulator/application module was loaded")
    after = hashlib.sha256(source.read_bytes()).hexdigest()
    if digest != after:
        raise ValueError("Source changed")
    if not meshes:
        raise ValueError("No mesh was extracted; prims=" + str(hierarchy))
    layers = [dict(path=layer.realPath,
        sha256=hashlib.sha256(Path(layer.realPath).read_bytes()).hexdigest())
        for layer in stage.GetUsedLayers() if layer.realPath]
    report = dict(source=str(source), source_sha256_before=digest,
        source_sha256_after=after, source_unchanged=True,
        python=sys.executable, python_version=sys.version, usd_version=list(Usd.GetVersion()),
        library_root=str(libraries), isolated=bool(sys.flags.isolated),
        no_site=bool(sys.flags.no_site), dont_write_bytecode=bool(sys.dont_write_bytecode),
        forbidden_modules_loaded=forbidden, simulation_app_called=False,
        stage_save_or_export_called=False, physics_called=False,
        default_prim=str(stage.GetDefaultPrim().GetPath()),
        stage_meters_per_unit=UsdGeom.GetStageMetersPerUnit(stage),
        stage_up_axis=str(UsdGeom.GetStageUpAxis(stage)),
        used_layers=layers, hierarchy=hierarchy, meshes=meshes)
    output.mkdir(parents=True)
    with (output / "usd_geometry.json").open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
    print(json.dumps(dict(output=str(output), mesh_count=len(meshes),
        vertices=sum(len(m["asset_points"]) for m in meshes),
        faces=sum(len(m["face_counts"]) for m in meshes),
        source_unchanged=True, application_modules_loaded=False)))


if __name__ == "__main__":
    main()
