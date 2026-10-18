# Compare Unity rest skeleton with the customizer glTF skeleton: find axis mapping and check rest-pose agreement.
import json, sys, itertools, numpy as np
bake, gltf = sys.argv[1], sys.argv[2]
def qm(q):
    x,y,z,w = q
    return np.array([[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)],[2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)],[2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)]])
U = json.load(open(bake+'/rest.json'))['bones']
uw = {}
for i,b in enumerate(U):
    R, T, S = qm(b['r']), np.array(b['t']), np.array(b['s'])
    if b['p'] < 0: uw[i] = (R, T, S.mean())
    else:
        PR, PT, PS = uw[b['p']]; uw[i] = (PR@R, PT + PR@(T*PS), PS*S.mean())
upos = {U[i]['n']: uw[i][1] for i in uw}; urot = {U[i]['n']: uw[i][0] for i in uw}
g = json.load(open(gltf)); N = g['nodes']; par = {}
for i,n in enumerate(N):
    for c in n.get('children', []): par[c] = i
gw = {}
def W(i):
    if i in gw: return gw[i]
    n = N[i]; R = qm(n.get('rotation',[0,0,0,1])); T = np.array(n.get('translation',[0,0,0])); S = np.array(n.get('scale',[1,1,1])).mean()
    if i in par:
        PR, PT, PS = W(par[i]); gw[i] = (PR@R, PT + PR@(T*PS), PS*S)
    else: gw[i] = (R, T, S)
    return gw[i]
gpos = {}; grot = {}
for i,n in enumerate(N):
    R,T,S = W(i); gpos[n['name']] = T; grot[n['name']] = R
common = [k for k in gpos if k in upos and k not in ('Root',)]
print('common', len(common))
best = None
for perm in itertools.permutations(range(3)):
    for signs in itertools.product([1,-1], repeat=3):
        M = np.zeros((3,3))
        for r,(c,s) in enumerate(zip(perm, signs)): M[r,c] = s
        e = sum(np.linalg.norm(M@upos[k] - gpos[k]) for k in common)/len(common)
        if best is None or e < best[0]: best = (e, M)
print('mean joint err (m)', best[0]); print(best[1])
M = best[1]
worst = sorted(((np.linalg.norm(M@upos[k]-gpos[k]), k) for k in common), reverse=True)[:5]; print('worst', worst)
# rest rotation relation: G = M U M^T C_k  -> per bone correction C_k
for k in ['Hips','LeftArm','LeftHand','Head','LeftHandIndex1']:
    C = (M@urot[k]@M.T).T @ grot[k]
    print(k, np.round(C,3).tolist())
