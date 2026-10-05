"""Inspect the converted welding tool USD without launching the simulator."""

from pathlib import Path

from isaacsim import SimulationApp

simulation_app = SimulationApp({"headless": True})

from pxr import Usd, UsdGeom


USD_PATH = Path(__file__).resolve().parent / "ATU01035_welding_tool.usd"
stage = Usd.Stage.Open(str(USD_PATH))
if stage is None:
    raise RuntimeError(f"Could not open {USD_PATH}")

print(f"RB5_REPORT stage={stage.GetRootLayer().realPath}", flush=True)
print(f"RB5_REPORT up_axis={UsdGeom.GetStageUpAxis(stage)}", flush=True)
print(f"RB5_REPORT meters_per_unit={UsdGeom.GetStageMetersPerUnit(stage)}", flush=True)

bbox_cache = UsdGeom.BBoxCache(
    Usd.TimeCode.Default(),
    [UsdGeom.Tokens.default_, UsdGeom.Tokens.render, UsdGeom.Tokens.proxy],
)
default_prim = stage.GetDefaultPrim()
print(f"RB5_REPORT default_prim={default_prim.GetPath()}", flush=True)
root_range = bbox_cache.ComputeWorldBound(default_prim).ComputeAlignedRange()
print(f"RB5_REPORT root_min={tuple(root_range.GetMin())}", flush=True)
print(f"RB5_REPORT root_max={tuple(root_range.GetMax())}", flush=True)
print(f"RB5_REPORT root_size={tuple(root_range.GetSize())}", flush=True)

xform_cache = UsdGeom.XformCache(Usd.TimeCode.Default())
closest = None
for prim in Usd.PrimRange.Stage(stage, Usd.TraverseInstanceProxies()):
    print(f"RB5_REPORT prim={prim.GetPath()} type={prim.GetTypeName()} active={prim.IsActive()}", flush=True)
    if prim.IsA(UsdGeom.Boundable):
        aligned_range = bbox_cache.ComputeWorldBound(prim).ComputeAlignedRange()
        print(f"RB5_REPORT min={tuple(aligned_range.GetMin())}", flush=True)
        print(f"RB5_REPORT max={tuple(aligned_range.GetMax())}", flush=True)
        print(f"RB5_REPORT size={tuple(aligned_range.GetSize())}", flush=True)
    if prim.IsA(UsdGeom.Mesh):
        mesh = UsdGeom.Mesh(prim)
        world = xform_cache.GetLocalToWorldTransform(prim)
        for point in mesh.GetPointsAttr().Get() or []:
            world_point = world.Transform(point)
            distance = world_point.GetLength()
            if closest is None or distance < closest[0]:
                closest = (distance, tuple(world_point), str(prim.GetPath()))

print(f"RB5_REPORT closest_mesh_point_to_origin={closest}", flush=True)

simulation_app.close()
