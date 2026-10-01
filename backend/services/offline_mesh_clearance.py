"""Offline triangle-surface diagnostics. No fixture registration or safety gate.

Distances use exact planar triangles (vertex/face, edge/edge and edge/face
crossings), with AABB trees for pruning. Numerical equality is machine-scale,
not a physical clearance acceptance threshold. Containment needs a separate
closed-solid check; zero surface distance alone does not measure penetration.
"""
from dataclasses import dataclass
import heapq
import numpy as np


def _segment_closest(p, q, r, s):
    u, v, w = q-p, s-r, p-r
    a, b, c = np.sum(u*u,1), np.sum(u*v,1), np.sum(v*v,1)
    d, e = np.sum(u*w,1), np.sum(v*w,1)
    den = a*c-b*b
    sc = np.divide(b*e-c*d, den, out=np.zeros_like(den),
                   where=den > np.finfo(float).eps*a*c*8)
    sc = np.clip(sc, 0, 1)
    tc = np.divide(b*sc+e, c, out=np.zeros_like(c), where=c>0)
    below, above = tc<0, tc>1
    sc[below] = np.clip(np.divide(-d, a, out=np.zeros_like(a), where=a>0)[below],0,1)
    sc[above] = np.clip(np.divide(b-d,a,out=np.zeros_like(a),where=a>0)[above],0,1)
    tc = np.clip(tc,0,1)
    # A degenerate first segment still projects to the second segment.
    tc[a==0] = np.clip(np.divide(e,c,out=np.zeros_like(c),where=c>0)[a==0],0,1)
    sc[c==0] = np.clip(np.divide(-d,a,out=np.zeros_like(a),where=a>0)[c==0],0,1)
    return p+sc[:,None]*u, r+tc[:,None]*v


def _point_triangle(p, t):
    a, b, c = t[:,0], t[:,1], t[:,2]
    u, v, w = b-a, c-a, p-a
    uu, uv, vv = np.sum(u*u,1), np.sum(u*v,1), np.sum(v*v,1)
    wu, wv = np.sum(w*u,1), np.sum(w*v,1)
    den = uu*vv-uv*uv
    s = np.divide(wu*vv-wv*uv,den,out=np.zeros_like(den),where=den>0)
    z = np.divide(wv*uu-wu*uv,den,out=np.zeros_like(den),where=den>0)
    proj = a+s[:,None]*u+z[:,None]*v
    inside = (den>0)&(s>=0)&(z>=0)&(s+z<=1)
    best = np.full(len(p), np.inf)
    closest = np.zeros_like(p)
    for i,j in ((0,1),(1,2),(2,0)):
        _, candidate = _segment_closest(p,p,t[:,i],t[:,j])
        dist = np.sum((p-candidate)**2,1)
        take = dist<best
        closest[take],best[take]=candidate[take],dist[take]
    closest[inside]=proj[inside]
    return closest


def _segment_triangle(p, q, t):
    # Moller-Trumbore, with relative machine precision for parallelism only.
    edge1, edge2, direction = t[:,1]-t[:,0], t[:,2]-t[:,0], q-p
    h = np.cross(direction,edge2)
    det = np.sum(edge1*h,1)
    scale = np.linalg.norm(edge1,axis=1)*np.linalg.norm(edge2,axis=1)*np.linalg.norm(direction,axis=1)
    good = abs(det)>np.finfo(float).eps*scale*64
    inv = np.divide(1.,det,out=np.zeros_like(det),where=good)
    offset = p-t[:,0]
    u = inv*np.sum(offset*h,1)
    cross = np.cross(offset,edge1)
    v = inv*np.sum(direction*cross,1)
    along = inv*np.sum(edge2*cross,1)
    eps = np.finfo(float).eps*128
    hit = good&(u>=-eps)&(v>=-eps)&(u+v<=1+eps)&(along>=-eps)&(along<=1+eps)
    return hit,p+np.clip(along,0,1)[:,None]*direction


def triangle_pairs(a, b):
    """Nearest points for paired triangles, including noncoplanar crossings."""
    a,b=np.asarray(a,dtype=float),np.asarray(b,dtype=float)
    best=np.full(len(a),np.inf)
    ca,cb=np.zeros((len(a),3)),np.zeros((len(a),3))
    def offer(x,y):
        d=np.sum((x-y)**2,1)
        take=d<best
        best[take],ca[take],cb[take]=d[take],x[take],y[take]
    for i in range(3):
        offer(a[:,i],_point_triangle(a[:,i],b))
        offer(_point_triangle(b[:,i],a),b[:,i])
    for i,j in ((0,1),(1,2),(2,0)):
        for k,l in ((0,1),(1,2),(2,0)):
            offer(*_segment_closest(a[:,i],a[:,j],b[:,k],b[:,l]))
        for source,target in ((a,b),(b,a)):
            hit,point=_segment_triangle(source[:,i],source[:,j],target)
            best[hit],ca[hit],cb[hit]=0.,point[hit],point[hit]
    return best,ca,cb


@dataclass
class _Node:
    low: np.ndarray
    high: np.ndarray
    indices: np.ndarray | None
    children: tuple | None


class TriangleSurface:
    def __init__(self, vertices, faces):
        vertices=np.asarray(vertices,dtype=float)
        faces=np.asarray(faces)
        if (vertices.ndim!=2 or vertices.shape[1]!=3 or not len(vertices)
            or not np.isfinite(vertices).all() or faces.ndim!=2 or faces.shape[1]!=3
            or not len(faces) or not np.issubdtype(faces.dtype,np.integer)
            or faces.min()<0 or faces.max()>=len(vertices)):
            raise ValueError("Finite vertices and valid indexed triangles required")
        self.triangles=vertices[faces].copy()
        self.nodes=[]
        lows,highs=self.triangles.min(1),self.triangles.max(1)
        centers=(lows+highs)/2
        def build(indices):
            low,high=lows[indices].min(0),highs[indices].max(0)
            index=len(self.nodes)
            self.nodes.append(None)
            if len(indices)<=8:
                node=_Node(low,high,indices,None)
            else:
                axis=np.argmax(np.ptp(centers[indices],axis=0))
                order=indices[np.argsort(centers[indices,axis],kind='stable')]
                mid=len(order)//2
                node=_Node(low,high,None,(build(order[:mid]),build(order[mid:])))
            self.nodes[index]=node
            return index
        build(np.arange(len(faces)))


def _bound(a,b):
    gap=np.maximum(0,np.maximum(a.low-b.high,b.low-a.high))
    return float(gap@gap)


def _children(a,b,ia,ib):
    if a.children and (not b.children or np.prod(a.high-a.low)>=np.prod(b.high-b.low)):
        return [(i,ib) for i in a.children]
    return [(ia,j) for j in b.children]


def surface_clearance(a, b):
    """Unsigned surface minimum plus intersecting triangle-pair count.

    Counts depend on tessellation, not number of separate collision events.
    Closest points and original triangle IDs are retained for reproducibility.
    """
    scale=max(1.,float(np.max(abs(a.triangles))),float(np.max(abs(b.triangles))))
    numerical=np.finfo(float).eps*scale*512
    best=np.inf
    witness=None
    queue=[(_bound(a.nodes[0],b.nodes[0]),0,0)]
    while queue:
        lower,ia,ib=heapq.heappop(queue)
        if lower>=best: continue
        na,nb=a.nodes[ia],b.nodes[ib]
        if na.indices is not None and nb.indices is not None:
            aa=np.repeat(na.indices,len(nb.indices));bb=np.tile(nb.indices,len(na.indices))
            distances,ca,cb=triangle_pairs(a.triangles[aa],b.triangles[bb])
            index=int(np.argmin(distances))
            if distances[index]<best:
                best=float(distances[index]);witness=(int(aa[index]),int(bb[index]),ca[index],cb[index])
        else:
            for i,j in _children(na,nb,ia,ib):
                bound=_bound(a.nodes[i],b.nodes[j])
                if bound<best: heapq.heappush(queue,(bound,i,j))
    intersecting=[]
    stack=[(0,0)]
    while stack:
        ia,ib=stack.pop();na,nb=a.nodes[ia],b.nodes[ib]
        if _bound(na,nb)>numerical**2: continue
        if na.indices is not None and nb.indices is not None:
            aa=np.repeat(na.indices,len(nb.indices));bb=np.tile(nb.indices,len(na.indices))
            d,ca,cb=triangle_pairs(a.triangles[aa],b.triangles[bb])
            for index in np.flatnonzero(d<=numerical**2):
                intersecting.append((int(aa[index]),int(bb[index]),ca[index]))
        else:
            stack.extend(_children(na,nb,ia,ib))
    return dict(minimum_surface_distance_m=float(np.sqrt(best)),
        closest_a_m=witness[2].tolist(),closest_b_m=witness[3].tolist(),
        closest_triangle_a=witness[0],closest_triangle_b=witness[1],
        intersecting_triangle_pair_count=len(intersecting),
        intersection_examples=[dict(triangle_a=i,triangle_b=j,point_m=p.tolist())
                               for i,j,p in intersecting[:8]],
        numerical_equality_m=numerical,physical_clearance_threshold_m=None,
        containment_checked=False,runtime_approved=False)


def solid_angle_inside(points, triangles):
    """Generalized winding diagnostic for a consistently oriented closed solid.

    Caller must establish closed topology before treating inside as penetration.
    Boundary values need a separate distance/quantization uncertainty analysis.
    """
    points,triangles=np.asarray(points,dtype=float),np.asarray(triangles,dtype=float)
    result=[]
    for point in points:
        a,b,c=np.moveaxis(triangles-point,1,0)
        la,lb,lc=np.linalg.norm(a,axis=1),np.linalg.norm(b,axis=1),np.linalg.norm(c,axis=1)
        numerator=np.sum(a*np.cross(b,c),1)
        denominator=la*lb*lc+np.sum(a*b,1)*lc+np.sum(b*c,1)*la+np.sum(c*a,1)*lb
        result.append(float(np.sum(2*np.arctan2(numerator,denominator))/(4*np.pi)))
    return np.asarray(result)
