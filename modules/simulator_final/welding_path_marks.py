"""Translucent planned weld band and accumulated measured torch-tip paint.

The overlays follow the actual workpiece surface. They are visual annotations,
not a heat/material deposition simulation. Object geometry is left unchanged.
"""
import numpy as np
from scipy.spatial import cKDTree


def surface_band(vertices, counts, indices, path, radius=.007, resolution=.002, additional_paths=()):
    """Triangulate/subdivide only faces close to the planned path."""
    triangles=[]; offset=0
    for count in counts:
        face=indices[offset:offset+count];offset+=count
        for j in range(1,int(count)-1):
            triangles.append(vertices[[face[0],face[j],face[j+1]]])
    pending=np.asarray(triangles,dtype=float)
    paths=[np.asarray(path), *additional_paths]
    combined=np.concatenate(paths)
    tree=cKDTree(combined)
    # Account for sparse input waypoints when selecting the surface patch.
    spacing=max(float(np.linalg.norm(np.diff(p,axis=0),axis=1).max())/2 for p in paths)
    low=combined.min(axis=0)-radius-spacing
    high=combined.max(axis=0)+radius+spacing
    completed=[]
    for _ in range(32):
        if not len(pending):break
        pending=pending[np.all(pending.max(axis=1)>=low,axis=1)&np.all(pending.min(axis=1)<=high,axis=1)]
        if not len(pending):break
        centers=pending.mean(axis=1)
        extent=np.linalg.norm(pending-centers[:,None,:],axis=2).max(axis=1)
        pending=pending[tree.query(centers)[0] <= radius+spacing+extent]
        if not len(pending):break
        longest=np.maximum.reduce([np.linalg.norm(pending[:,0]-pending[:,1],axis=1),
                                   np.linalg.norm(pending[:,1]-pending[:,2],axis=1),
                                   np.linalg.norm(pending[:,2]-pending[:,0],axis=1)])
        small=longest<=resolution
        completed.append(pending[small]);pending=pending[~small]
        if not len(pending):break
        # Bisect only the longest edge: do not explode thin cylindrical faces
        # into tens of thousands of near-zero-area triangles.
        edge_lengths=np.stack([np.linalg.norm(pending[:,0]-pending[:,1],axis=1),
                               np.linalg.norm(pending[:,1]-pending[:,2],axis=1),
                               np.linalg.norm(pending[:,2]-pending[:,0],axis=1)],axis=1)
        edge=edge_lengths.argmax(axis=1); rows=np.arange(len(pending))
        a=pending[rows,edge];b=pending[rows,(edge+1)%3];c=pending[rows,(edge+2)%3]
        middle=(a+b)/2
        pending=np.concatenate((np.stack((a,middle,c),axis=1),np.stack((middle,b,c),axis=1)))
    else:
        raise ValueError('Weld band subdivision did not converge')
    tris=np.concatenate(completed) if completed else np.empty((0,3,3))
    if len(tris):
        centers=tris.mean(axis=1)
        distances=np.minimum.reduce([polyline_distance(centers,p) for p in paths])
        tris=tris[distances <= radius]
    normals=np.cross(tris[:,1]-tris[:,0],tris[:,2]-tris[:,0])
    norm=np.linalg.norm(normals,axis=1)
    valid=norm>1e-12
    return tris[valid],normals[valid]/norm[valid,None]


def segment_distance(points, a, b):
    direction=b-a
    length=float(np.dot(direction,direction))
    if length<1e-20:return np.linalg.norm(points-a,axis=1)
    t=np.clip((points-a)@direction/length,0,1)
    return np.linalg.norm(points-(a+t[:,None]*direction),axis=1)


def polyline_distance(points, path):
    distances=np.full(len(points),np.inf)
    for a,b in zip(path[:-1],path[1:]):
        distances=np.minimum(distances,segment_distance(points,a,b))
    return distances


class WeldMarks:
    def __init__(self,stage,solution,planned_path):
        from pxr import Sdf, UsdGeom, UsdShade
        self.stage=stage
        self.points=[]
        self.previous=None
        additional_paths=([np.asarray(solution['predicted_world_xyz_m'])]
                          if 'predicted_world_xyz_m' in solution else [])
        self.triangles,self.normals=surface_band(
            np.asarray(solution['workpiece_vertices_world_m']),
            solution['workpiece_face_counts'],solution['workpiece_face_indices'],planned_path,
            additional_paths=additional_paths)
        self.centers=self.triangles.mean(axis=1)
        self.planned=polyline_distance(self.centers,planned_path)<=.007
        self.painted=np.zeros(len(self.triangles),dtype=bool)
        self.planned_material=self.material('Planned',(0.05,.95,.15),.35)
        self.actual_material=self.material('Actual',(1.,.025,.015),1.)
        # Fixed topology with per-face color/opacity avoids coplanar overlays.
        # OBJ winding can face inward; offset on both sides of each surface.
        surface_material=self.material('Surface',(1.,1.,1.),1.)
        shader=UsdShade.Shader.Get(stage,str(surface_material.GetPath())+'/Shader')
        for name,type_name,output,input_name in (
                ('displayColor','float3',Sdf.ValueTypeNames.Float3,'diffuseColor'),
                ('displayOpacity','float',Sdf.ValueTypeNames.Float,'opacity')):
            reader=UsdShade.Shader.Define(stage,str(surface_material.GetPath())+'/'+name)
            reader.CreateIdAttr('UsdPrimvarReader_'+type_name)
            reader.CreateInput('varname',Sdf.ValueTypeNames.Token).Set(name)
            reader.CreateOutput('result',output)
            shader.GetInput(input_name).ConnectToSource(reader.ConnectableAPI(),'result')
            if name=='displayColor':
                # An annotation must remain readable inside a shaded joint.
                shader.GetInput('emissiveColor').ConnectToSource(reader.ConnectableAPI(),'result')
        self.surface_mesh=self.mesh('/WeldMarks/Surface',surface_material)
        self.set_triangles(self.surface_mesh,np.concatenate((
            self.triangles+self.normals[:,None,:]*.0005,
            self.triangles-self.normals[:,None,:]*.0005)))
        self.surface_mesh.GetDisplayColorPrimvar().SetInterpolation('uniform')
        self.surface_mesh.GetDisplayOpacityPrimvar().SetInterpolation('uniform')
        self.update_surface_colors()
        if bool(solution.get('fixture_fixed_orientation', False)):
            planned_curve = self.curve('/WeldMarks/RawGTPath', self.planned_material, .002)
            self.set_curve(planned_curve, planned_path)
        if 'cad_contact_curve_world_m' in solution:
            cad_material = self.material('CADReference', (.02, .65, 1.), .6)
            cad_curve = self.curve('/WeldMarks/CADContactReference', cad_material, .0015)
            self.set_curve(cad_curve, solution['cad_contact_curve_world_m'])
            print('[WELD MARKS] cyan=CAD joint outline (reference only, not robot target)', flush=True)
        self.actual_curve=self.curve('/WeldMarks/MeasuredTipTrail',self.actual_material,.0045)
        self.set_curve(self.actual_curve,[])
        print(f'[WELD MARKS] planned green opacity=0.35; red=measured tip sweep; surface triangles={len(self.triangles)}',flush=True)

    def material(self,name,color,opacity):
        from pxr import Gf,Sdf,UsdShade
        material=UsdShade.Material.Define(self.stage,'/WeldMarks/Materials/'+name)
        shader=UsdShade.Shader.Define(self.stage,str(material.GetPath())+'/Shader')
        shader.CreateIdAttr('UsdPreviewSurface')
        shader.CreateInput('diffuseColor',Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*color))
        shader.CreateInput('emissiveColor',Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*color))
        shader.CreateInput('opacity',Sdf.ValueTypeNames.Float).Set(opacity)
        shader.CreateInput('opacityThreshold',Sdf.ValueTypeNames.Float).Set(0.)
        shader.CreateInput('roughness',Sdf.ValueTypeNames.Float).Set(1.)
        shader.CreateInput('ior',Sdf.ValueTypeNames.Float).Set(1.)
        shader.CreateOutput('surface',Sdf.ValueTypeNames.Token)
        material.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(),'surface')
        return material

    def mesh(self,path,material):
        from pxr import UsdGeom,UsdShade
        mesh=UsdGeom.Mesh.Define(self.stage,path)
        mesh.CreateSubdivisionSchemeAttr('none')
        mesh.CreateDoubleSidedAttr(True)
        UsdShade.MaterialBindingAPI.Apply(mesh.GetPrim()).Bind(material)
        return mesh

    def curve(self,path,material,width):
        from pxr import UsdGeom,UsdShade
        curve=UsdGeom.BasisCurves.Define(self.stage,path)
        curve.CreateTypeAttr('linear');curve.CreateWrapAttr('nonperiodic')
        curve.CreateWidthsAttr([width]);curve.SetWidthsInterpolation('constant')
        UsdShade.MaterialBindingAPI.Apply(curve.GetPrim()).Bind(material)
        return curve

    @staticmethod
    def set_triangles(mesh,triangles):
        from pxr import Gf,Vt,UsdGeom
        vertices=np.ascontiguousarray(triangles.reshape(-1,3),dtype=np.float32)
        mesh.CreatePointsAttr().Set(Vt.Vec3fArray.FromNumpy(vertices))
        mesh.CreateFaceVertexCountsAttr().Set(Vt.IntArray.FromNumpy(np.full(len(triangles),3,dtype=np.int32)))
        mesh.CreateFaceVertexIndicesAttr().Set(Vt.IntArray.FromNumpy(np.arange(len(vertices),dtype=np.int32)))
        if len(vertices):
            mesh.CreateExtentAttr().Set([Gf.Vec3f(*map(float,vertices.min(0))),Gf.Vec3f(*map(float,vertices.max(0)))])
            mesh.GetVisibilityAttr().Set(UsdGeom.Tokens.inherited)
        else:
            mesh.GetVisibilityAttr().Set(UsdGeom.Tokens.invisible)

    @staticmethod
    def set_curve(curve,points):
        from pxr import Gf,UsdGeom
        values=[Gf.Vec3f(*map(float,p)) for p in points]
        if len(values)==1:values=values*2
        curve.CreateCurveVertexCountsAttr().Set([len(values)] if values else [])
        curve.CreatePointsAttr().Set(values)
        if values:
            vertices=np.asarray(values)
            curve.CreateExtentAttr().Set([Gf.Vec3f(*map(float,vertices.min(0)-.005)),Gf.Vec3f(*map(float,vertices.max(0)+.005))])
            curve.GetVisibilityAttr().Set(UsdGeom.Tokens.inherited)
        else:
            curve.GetVisibilityAttr().Set(UsdGeom.Tokens.invisible)

    def begin(self,point):
        self.previous=np.asarray(point).copy()
        self.points=[self.previous.copy()]

    def update_surface_colors(self):
        from pxr import Vt
        painted=np.tile(self.painted,2)
        colors=np.where(painted[:,None],(1.,.025,.015),(.05,.95,.15)).astype(np.float32)
        opacity=np.where(painted,1.,np.where(np.tile(self.planned,2),.35,0.)).astype(np.float32)
        self.surface_mesh.CreateDisplayColorAttr().Set(Vt.Vec3fArray.FromNumpy(colors))
        self.surface_mesh.CreateDisplayOpacityAttr().Set(Vt.FloatArray.FromNumpy(opacity))

    def record(self,point,force=False):
        point=np.asarray(point,dtype=float)
        if self.previous is None:
            self.begin(point);return
        if np.linalg.norm(point-self.previous)<.00015 and not force:return
        # Actual swept segment determines the painted area, never playback percentage.
        self.painted |= segment_distance(self.centers,self.previous,point)<=.007
        self.points.append(point.copy());self.previous=point.copy()
        self.update_surface_colors()
        self.set_curve(self.actual_curve,self.points)

    def save(self,path):
        np.savez_compressed(path,actual_tip_path_world_m=np.asarray(self.points),
                            painted_surface_centers_world_m=self.centers[self.painted])
        print(f'[WELD MARKS] saved {len(self.points)} measured points; {int(self.painted.sum())} painted triangles',flush=True)
