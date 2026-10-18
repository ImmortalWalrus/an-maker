# Convert Unity-sampled Genies clips (bake_out/*.json) to the customizer skeleton (glTF, X mirrored, cm under Root).
# Writes anims.json (index) + anims.bin.txt (base64 little-endian int16 samples).
import json, sys, base64, numpy as np
bake, gltf, outdir = sys.argv[1], sys.argv[2], sys.argv[3]
# clip sets: "dir:Name,Name;dir2:Name" (default: the Starter Pack bake)
import os
SETS = [(d, n.split(',')) for d, n in (x.split(':', 1) for x in os.environ.get('CLIP_SETS', bake + ':Idle,Wave,Peace,Jump,Walk,Run').split(';'))]
LOOPING = set(os.environ.get('LOOPING', 'Idle,Walk,Run').split(','))
FPS = 30
LIFT = {'Jump': 0.3}

def qmul(a, b):
    x1,y1,z1,w1 = np.moveaxis(a, -1, 0); x2,y2,z2,w2 = np.moveaxis(b, -1, 0)
    return np.stack([w1*x2+x1*w2+y1*z2-z1*y2, w1*y2-x1*z2+y1*w2+z1*x2, w1*z2+x1*y2-y1*x2+z1*w2, w1*w2-x1*x2-y1*y2-z1*z2], -1)
def qrot(q, v):
    u = q[..., :3]; w = q[..., 3:4]
    t = 2*np.cross(u, v); return v + w*t + np.cross(u, t)
def qinv(q): return q * np.array([-1, -1, -1, 1])
def mirror(q): return q * np.array([1, -1, -1, 1])      # M q M^T with M = diag(-1, 1, 1)
def qang(a, b): return 2*np.degrees(np.arccos(np.clip(np.abs((a*b).sum(-1)), 0, 1)))

U = json.load(open(f'{SETS[0][0]}/rest.json'))['bones']
names = [b['n'] for b in U]; parent = [b['p'] for b in U]
g = json.load(open(gltf)); N = g['nodes']
joints = [N[j]['name'] for j in g['skins'][0]['joints']]
gidx = {n['name']: i for i, n in enumerate(N)}
rest_t = {n: np.array(N[gidx[n]].get('rotation', [0, 0, 0, 1])) for n in joints}
hips_chain = []
i = names.index('Hips')
while i >= 0: hips_chain.insert(0, i); i = parent[i]

index = {'fps': FPS, 'clips': []}
blob = []; off = 0
def push(arr):
    global off
    a = np.asarray(arr, dtype=np.int16).ravel(); blob.append(a); o = off; off += a.size; return o

for src, c in [(d, n) for d, ns in SETS for n in ns]:
    d = json.load(open(f'{src}/{c}.json'))
    F = len(d['frames'])
    R = np.array([np.array(fr['r']).reshape(-1, 4) for fr in d['frames']])   # F x B x 4 (Unity local)
    T = np.array([np.array(fr['t']).reshape(-1, 3) for fr in d['frames']])
    # Hips world (Unity) -> glTF local under Root (Root has identity rotation, scale 0.01 -> cm)
    wq = np.tile([0, 0, 0, 1.0], (F, 1)); wp = np.zeros((F, 3))
    for k in hips_chain:
        wp = wp + qrot(wq, T[:, k]); wq = qmul(wq, R[:, k])
    hips_q = mirror(wq)
    hips_p = wp * np.array([-1, 1, 1]) * 100.0
    # remove travel: linear XZ drift so the loop/one-shot stays in place
    drift = hips_p[-1] - hips_p[0]
    ramp = np.linspace(0, 1, F)[:, None]
    hips_p[:, 0] -= ramp[:, 0] * drift[0]; hips_p[:, 2] -= ramp[:, 0] * drift[2]
    if c in LIFT:   # keep big cartoon jumps in frame: scale only the airborne part of the hips path
        stand = hips_p[0, 1]; up = hips_p[:, 1] > stand
        hips_p[up, 1] = stand + (hips_p[up, 1] - stand) * LIFT[c]
    info = {'name': c, 'length': d['length'], 'frames': F, 'loop': c in LOOPING, 'tracks': []}
    seam = []
    for n in joints:
        k = names.index(n)
        q = hips_q.copy() if n == 'Hips' else mirror(R[:, k])
        q = q * np.where((q * q[0]).sum(-1, keepdims=True) < 0, -1, 1)          # continuous hemisphere
        if info['loop']:
            e = qang(q[0], q[-1]); seam.append((round(float(e), 2), n))
            if e > 0.05:   # spread the loop seam over the clip (like Unity's Loop Pose)
                delta = qmul(qinv(q[-1]), q[0])
                if delta[3] < 0: delta = -delta
                ang = 2*np.arccos(np.clip(delta[3], -1, 1)); ax = delta[:3] / max(np.linalg.norm(delta[:3]), 1e-9)
                s = np.linspace(0, 1, F)[:, None] * ang
                corr = np.concatenate([ax * np.sin(s/2), np.cos(s/2)], 1)
                q = qmul(q, corr)
        moving = qang(q, q[0]).max() > 0.02
        diff_rest = qang(q[0], rest_t[n]) > 0.02
        if not moving and not diff_rest: continue
        keys = q if moving else q[:1]
        info['tracks'].append({'bone': n, 'keys': len(keys), 'off': push(np.round(keys * 32767))})
    info['hips'] = push(np.round(hips_p * 100))   # 0.01 cm units
    info['hipsDrift'] = [round(float(x), 2) for x in drift]
    seam.sort(reverse=True)
    print(c, F, 'tracks', len(info['tracks']), 'moving', sum(t['keys'] > 1 for t in info['tracks']), 'drift cm', info['hipsDrift'],
          'hipsY', round(float(hips_p[:, 1].min()), 1), round(float(hips_p[:, 1].max()), 1), 'seam', seam[:3])
    # start/end pose vs Idle frame 0 (for blending notes)
    index['clips'].append(info)
data = np.concatenate(blob).astype('<i2').tobytes()
open(f'{outdir}/anims.bin.txt', 'w').write(base64.b64encode(data).decode())
json.dump(index, open(f'{outdir}/anims.json', 'w'), separators=(',', ':'))
print('samples', off, 'bytes', len(data))
