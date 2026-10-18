"""Layer generation ON TOP OF THE REAL 3D PIECES: make one new piece (an outer layer or an over-item such as a bag)
for an existing look, drawn over renders of that look's actual meshes. The image model then sees the true bulk,
folds and hems of what the piece goes over (a Tripo hoodie is puffier than the hoodie in the concept images), so
the generated piece fits it by construction instead of being bent afterwards (pieces are never deformed).

Creates a small "layer outfit" holding only the new piece; steps 3-6 then run on it unchanged, and equip combines it
with the look's other pieces (<layer_outfit>:<key>).

BUNDLES (--bundle-with <garment key>): an over-item that must wrap a specific garment closely (a crossbody strap over
a puffy hoodie) cannot fit as a separate rigid piece, and pieces are never bent. So the item is drawn on the real
garment as above, and then the garment AND the item are cut out and generated TOGETHER as ONE piece
("<garment>_with_<item>", the garment's slot). The strap is then built onto that exact surface by the 3D generator.
The bundle is equipped / bought / removed as one model; the plain garment stays its own wardrobe item.

Run: python pipeline/tpose/s2_over.py --look Outfits/_looks/full-look --base Xander --from Outfits/hoodie-boy
         --key gray_crossbody_bag --out Outfits/hoodie-boy-bag2 [--exclude gray_crossbody_bag]
         [--bundle-with black_graphic_hoodie] [--reuse-dressed Outfits/hoodie-boy-bag2]
  1. render the look (without the excluded pieces) from the step-1 cameras        -> 00_under/{view}.png
  2. Codex adds ONLY the new piece, everything else pixel-identical                -> 02_dressed/{view}.png
  3. split the piece (s2_images step 3)                                            -> 03_garments/{view}_<key>.png
Then: s4_meshes.py, s5_dump_meshes.py, s5_place.py, s6_fit.py on the layer outfit, and equip.
"""
import argparse, json, shutil, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from s2_images import codex, split, CANVAS  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
from anmaker_config import BLENDER  # noqa: E402  (this machine's Blender: .anmaker/config.json or a search)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--look', required=True)
    ap.add_argument('--base', required=True)
    ap.add_argument('--from', dest='src', required=True, help='outfit the piece description/concept come from')
    ap.add_argument('--key', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--exclude', nargs='*', default=None, help='look pieces not rendered underneath (default: --key)')
    ap.add_argument('--bundle-with', nargs='*', default=None, help='garment key(s) generated together with --key')
    ap.add_argument('--reuse-dressed', default=None, help='layer outfit whose 00_under / 02_dressed images to reuse')
    ap.add_argument('--under-mannequin', action='store_true', help='the first layer: draw on the bare avatar renders '
                    '(step 1, same cameras) instead of a look')
    a = ap.parse_args()
    look, src, d = Path(a.look).resolve(), Path(a.src).resolve(), Path(a.out).resolve()
    d.mkdir(parents=True, exist_ok=True)
    log = d / 'codex.log'
    src_pieces = json.loads((src / 'outfit.json').read_text())['pieces']
    piece = next(p for p in src_pieces if p['key'] == a.key)
    out_piece = piece
    if a.bundle_with:
        bw = [next(p for p in src_pieces if p['key'] == k) for k in a.bundle_with]
        out_piece = {'key': '_with_'.join([b['key'] for b in bw] + [piece['key']]), 'slot': bw[0]['slot'],
                     'bundle_of': [b['key'] for b in bw] + [piece['key']],
                     'description': ' '.join(f"{b['description']}" for b in bw) + f" Worn TOGETHER with it, as part of the "
                     f"same piece: {piece['description']} ONE combined piece: the {', '.join(b['key'] for b in bw)} "
                     f"and the {piece['key']} with its whole strap exactly as worn on it."}
    (d / 'outfit.json').write_text(json.dumps({'pieces': [out_piece], 'over_look': str(look), 'from': str(src)}, indent=2))
    if not (d / '01_mannequin').exists():
        shutil.copytree(src / '01_mannequin', d / '01_mannequin')
    shutil.copy(src / 'concept.png', d / 'concept.png')
    if a.reuse_dressed:  # the same garment + item drawn before: reuse those images (same cameras, same look)
        for sub in ('00_under', '02_dressed'):
            if not (d / sub).exists() and (Path(a.reuse_dressed) / sub).exists():
                shutil.copytree(Path(a.reuse_dressed) / sub, d / sub)

    # 1. the real pieces underneath (or the bare avatar for a first layer)
    if a.under_mannequin and not (d / '00_under').exists():
        (d / '00_under').mkdir()
        for v in ('front', 'left', 'back', 'right'):
            shutil.copy(d / '01_mannequin' / f'{v}.png', d / '00_under' / f'{v}.png')
    if not all((d / '00_under' / f'{v}.png').exists() for v in ('front', 'left', 'back', 'right')):
        subprocess.run([BLENDER, '-b', '--factory-startup', '-P', str(Path(__file__).parent / 'render_under.py'), '--',
                        str(look), a.base, str(d / '00_under'), '--exclude', *(a.exclude or [a.key])], check=True)

    # 2. add ONLY the new piece on top of the render
    keep = f"""Everything already in image 1 must stay PIXEL-IDENTICAL: the same character, face, hair, every piece of
clothing with its exact shape, size, bulk, folds and colours, the same pose, camera, framing, lighting and plain white
background, {CANVAS}, same 3D render style. Do not slim, smooth, move or redraw anything that is there.
The new piece is worn ON the real outer surface shown in image 1: it rests on top of the clothes exactly as they are
rendered (a strap lies on the outside of a bulky hoodie following its true thickness, over its folds and over the
hood where they meet; a bag hangs against the outside of the clothes) - it never sinks into them or passes behind
them. Every opening of the new piece (waistband, collar, cuffs, hems) wraps closely around what it goes over: a
waistband sits snugly around the waist with the body fully inside it, a collar around the neck - no skin or lower
clothing pushes out through the piece anywhere, and it rests on the body or the clothes under it without floating.
LAYERING: where the new piece hangs over clothing already worn (a shirt hem over a waistband, belt loops, pockets),
it lies OUTSIDE that clothing like a looser shell: at every height it is a little wider than the clothing it covers,
seen from the front, the back AND the sides, held off it by that clothing's full thickness. The waistband, its belt
loops and anything on it are completely hidden under the hem - nothing pokes out - and the hem falls straight down
over them, never tucked in or pulled in tight against the body below the waistband's outline."""
    what = f"{piece['key']}: {piece['description']}"
    keep += ' ' + LAYER_STANDARD.get(SH_KIND.get(out_piece['slot']), '')
    covering = out_piece['slot'] in COVER_SLOTS and not a.under_mannequin and not a.bundle_with  # a bundle's under-render already holds its own garment
    for rnd in range(COVER_ROUNDS + 1):
        dress_and_split(d, a, piece, out_piece, what, keep, log)
        res = {v: image_checks(d, v, out_piece['key'], out_piece['slot'], a.base, covering) for v in VIEWS}
        for v, (ok, stats, why) in res.items():
            print(f'[2d] {v}: {"ok" if ok else "REDO - " + "; ".join(why)}', stats, flush=True)
        bad = [v for v, r in res.items() if not r[0]]
        (d / 'image_checks.json').write_text(json.dumps({'pass': not bad, 'failing_views': bad, 'round': rnd,
                                                         'checks': {v: r[2] for v, r in res.items()}}, indent=2))
        if not bad or rnd == COVER_ROUNDS:
            if bad:
                # never hand a drawing that breaks the checks to the paid 3D step: stop here (exit 2), so a chained
                # gate does not run. Redraw (rerun) or adjust the piece's description first.
                print('[2d] STOPPED: still failing the image checks in', bad, '- no mesh will be generated', flush=True)
                sys.exit(2)
            break
        redo = VIEWS if 'front' in bad else bad  # the other views are drawn from the front one
        stamp = f'_cover{rnd}_'
        for v in redo:
            for f in [d / '02_dressed' / f'{v}.png', d / '03_garments' / f"{v}_{out_piece['key']}.png"]:
                if f.exists():
                    f.replace(f.with_name(stamp + f.name))   # replace: an earlier run may have left the same backup name
        why = {w.split(':')[0] for v in bad for w in res[v][2]}
        keep += '\n' + ' '.join(REDO_NOTES[w] for w in sorted(why))
    print('[over] images ready in', d, flush=True)


VIEWS = ('front', 'left', 'back', 'right')
COVER_SLOTS = ('top', 'outerwear', 'fullbody')
# The layer shells (shells.py) said up front, so the first drawing already meets them (the image checks verify it)
SH_KIND = {'bottom': 'bottom', 'top': 'upper', 'outerwear': 'upper', 'fullbody': 'upper'}
LAYER_STANDARD = {
    'bottom': "LAYER STANDARD (pieces are mixed and matched like RPG armour layers): the waistband is FLAT and lies "
              "against the body all the way round - elastic or flat-sewn, no belt, no belt loops, tabs or buckles "
              "standing out; any pockets around the hips are flat, sewn onto the surface. From the waistband down "
              "to the top of the thighs - hips and seat included - the fabric follows the body closely (about 1 cm "
              "off it, seen from the front AND the side). Below that the legs keep the design's own cut (baggy is "
              "fine), every leg opening or ankle cuff is clearly wider than the ankle, with space all round it, and "
              "full-length legs end at the top of the ankle (where a high-top sneaker's collar sits), never pooling over "
              "the foot.",
    'upper': "LAYER STANDARD (pieces are mixed and matched like RPG armour layers): around the hips the hem hangs "
             "straight and clearly AWAY from the body, a relaxed fit, so any trousers' waistband fits underneath "
             "without touching it. Sleeves are loose tubes with clear space all round the arm - above and below - "
             "to their hems, ending in a neat soft cuff whose opening leaves about a finger's width (1-2 cm) of room "
             "all round the wrist - narrower than a puffy sleeve, never a gaping bell opening, never tight. The cuff is "
             "one solid, continuous edge of the sleeve: no separate loose rim, ring or loop hanging past it. Nothing hugs "
             "the skin except at the "
             "collar and shoulders. A crew or round neckline hugs the base "
             "of the neck all the way round, a few millimetres off it at the front AND the back - never a wide, dropped "
             "or stretched-open neck hole.",
}
CHEST_ROOM_MM = 8.0   # a top stands at least this far off the chest/back outline (relaxed fit)
HEM_ABOVE_FOOT_M = 0.035   # full-length bottoms end at a high-top's collar, ~3.5 cm above the ankle joint
CUFF_MARGIN_PX = 3    # ~4 mm: a leg opening must leave room round the ankle
SLEEVE_MARGIN_PX = 3  # ~4 mm: a sleeve must surround the arm above and below, in the front and back views
REDO_NOTES = {
    'cover': "IMPORTANT: a previous attempt drew the new piece NARROWER than the clothing under it, so the waistband "
             "would poke out through it. Make it clearly wider than the waistband at every height, especially seen "
             "from the side (front-to-back depth) - the waistband and belt loops fully inside it.",
    'shell': "IMPORTANT: a previous attempt broke the layer standard at the waist. Bottoms: a FLAT waistband that "
             "lies against the body (elastic or flat-sewn, no belt, no belt loops or tabs sticking out, pockets flat), "
             "and the hips and seat follow the body closely down to the top of the thighs, seen from the side too. "
             "Tops and outerwear: the hem hangs clearly away from the body around the hips, never hugging them.",
    'missing': "",
    'chest': "IMPORTANT: a previous attempt drew the top hugging the chest and back. Give its body a relaxed fit: "
             "clearly off the chest, back and sides (about a finger's width), while the crew neckline stays snug.",
    'neck': "IMPORTANT: a previous attempt drew the neck opening wider than the neck. The crew neckline must sit snugly "
            "around the base of the neck, front, back and sides, only a few millimetres off it.",
    'hem': "IMPORTANT: a previous attempt drew the trouser legs too long, pooling over the feet. Full-length legs end "
           "at the top of the ankle - where the collar of a high-top sneaker would be, about two fingers above the ankle "
           "bone - with the whole foot and ankle bone visible below the hem.",
    'cuff': "IMPORTANT: a previous attempt drew leg openings as tight as the ankle. The ankle cuffs must be "
            "clearly wider than the ankle, with visible space all round it - like a loose elastic cuff, not a sock.",
    'sleevecuff': "IMPORTANT: a previous attempt drew tight cuffs. Every sleeve ends in a soft cuff clearly wider than "
                  "the wrist, about a finger's width of visible space all round it - never a snug elastic or ribbed cuff, "
                  "and never a gaping bell opening either.",
    'sleeve': "IMPORTANT: a previous attempt drew a sleeve that cuts into the arm. Every sleeve is a loose tube with "
              "clear space all around the arm - above and below it - all the way to the sleeve's hem.",
}
COVER_ROUNDS = 3  # image redraws are free; a mesh costs credits - get the drawings right first
COVER_MARGIN_PX = 4   # ~5 mm at the step-1 camera scale (figure ~1025 px tall)
COVER_NEED = 0.9


def covers_under(d: Path, view: str, key: str):
    """2D layering check before any 3D credits are spent: on every image row where the new piece overlaps clothing
    already worn (from 00_under vs the bare 01_mannequin render, same camera), the piece's outline must extend at
    least COVER_MARGIN_PX past that clothing's outline on each side whose edge IS clothing (rows ending in skin - arms,
    hands - are not covered by design). Side views measure front-to-back depth, where a hem pulled in over a waistband
    shows up. Returns (ok, stats)."""
    import numpy as np
    from PIL import Image
    from s5_place import background_mask
    under, ok_u = d / '00_under' / f'{view}.png', d / '01_mannequin' / f'{view}.png'
    gpng = d / '03_garments' / f'{view}_{key}.png'
    if not (under.exists() and ok_u.exists() and gpng.exists()):
        return True, {'skipped': True}
    um, _ = background_mask(under)
    mm, _ = background_mask(ok_u)
    u = np.asarray(Image.open(under).convert('RGB'), float)
    m = np.asarray(Image.open(ok_u).convert('RGB'), float)
    cloth = um & ((np.abs(u - m).sum(-1) > 90) | ~mm)
    pm, _ = background_mask(gpng)
    prow = np.nonzero(pm.any(1))[0]
    margins = []
    for r in range(pm.shape[0]):
        if not pm[r].any() or cloth[r].sum() <= 3 or r > prow.max() - 5:  # the last rows are the hem edge itself
            continue
        uc, pc = np.nonzero(um[r])[0], np.nonzero(pm[r])[0]
        for edge, gap in ((uc.min(), uc.min() - pc.min()), (uc.max(), pc.max() - uc.max())):
            if cloth[r, max(edge - 2, 0):edge + 3].any():
                margins.append(gap)
    if not margins:
        return True, {'overlap': 0}
    g = np.array(margins)
    share = float((g >= COVER_MARGIN_PX).mean())
    return share >= COVER_NEED, {'edges': len(g), 'covered_share': round(share, 2), 'min_px': int(g.min()),
                                 'median_px': float(np.median(g))}


def image_checks(d: Path, view: str, key: str, slot: str, base: str, covering: bool):
    """All 2D checks of one view, before any 3D credits are spent: (ok, stats, reasons).
      cover   the piece covers the clothing drawn under it (covers_under; layer outfits only)
      shell   the layer shell at the hips and waistband (shells.BANDS): bottoms within each sub-band's max of the
              body outline, tops/outerwear at least that + GAP_MM outside it - the standard the 3D inspection enforces
      sleeve  front/back views: each sleeve surrounds the arm above and below with a margin"""
    import numpy as np
    import shells as SH
    from s5_place import background_mask
    stats, why = {}, []
    if covering:
        ok, st = covers_under(d, view, key)
        stats['cover'] = st
        if not ok:
            why.append(f"cover: {st.get('covered_share')} of the edges clear the clothing under it")
    gpng, mpng = d / '03_garments' / f'{view}_{key}.png', d / '01_mannequin' / f'{view}.png'
    camf = d / '01_mannequin' / 'camera.json'
    if not gpng.exists():
        why.append('missing: the garment image was not produced')  # never pass a view that was not drawn
        return False, stats, why
    if not (mpng.exists() and camf.exists()):
        return not why, stats, why
    cam = json.loads(camf.read_text())
    lm = json.loads((ROOT / 'Bases' / f'{base}.json').read_text())['landmarks']
    pxmm = 1 / (cam['metres_per_pixel'] * 1000)
    pm, _ = background_mask(gpng)
    bm, _ = background_mask(mpng)
    prow = np.nonzero(pm.any(1))[0]
    kind = SH.SLOTS.get(slot)
    dpng = d / '02_dressed' / f'{view}.png'
    if kind and len(prow) and dpng.exists():
        # measured on the DRESSED image (registered to the mannequin within ~1 px; at the waistband its outline is
        # the outermost garment) - the cut-out garment images drift 3-5 % in scale between views
        pm_shell, _ = background_mask(dpng)
        r0, r1 = SH.shell_rows(cam, lm['Hips'][2])
        edge = int(SH.EDGE * 1000 * pxmm)
        mpp, cz, H = cam['metres_per_pixel'], cam['center'][2], cam['res'][1]
        gaps, lims = [], []
        for r in range(max(r0, prow.min() + edge), min(r1, prow.max() - edge) + 1):
            if not pm[r].any() or not bm[r].any():
                continue
            z_rel = cz + (H / 2 - r) * mpp - lm['Hips'][2]
            band = next((bd for bd in SH.BANDS.values() if bd['z'][0] <= z_rel < bd['z'][1]), None)
            if band is None:
                continue
            bc, pc_ = np.nonzero(bm[r])[0], np.nonzero(pm_shell[r])[0]
            gaps += [(bc.min() - pc_.min()) / pxmm, (pc_.max() - bc.max()) / pxmm]
            lims += [band['bottom_max']] * 2
        if len(gaps) >= 10:
            g, lim = np.array(gaps), np.array(lims, float)
            if kind == 'bottom':
                share = float((g <= lim).mean())
                stats['shell'] = {'edges': len(g), 'within_shell_share': round(share, 2), 'max_mm': round(float(g.max()), 1)}
                if share < 0.95:
                    why.append(f'shell: {1 - share:.0%} of the waistband/hip outline is further off the body than the '
                               f'bottoms shell ({", ".join(f"{k} {v['bottom_max']}" for k, v in SH.BANDS.items())} mm)')
            else:
                share = float((g >= lim + SH.GAP_MM).mean())
                stats['shell'] = {'edges': len(g), 'clear_share': round(share, 2), 'min_mm': round(float(g.min()), 1)}
                if share < 0.95:
                    why.append(f'shell: only {share:.0%} of the waistband/hip outline clears the bottoms shell '
                               f'(+{SH.GAP_MM} mm)')
    if SH.SLOTS.get(slot) == 'bottom' and len(prow):
        # hem height: full-length legs stop where a high-top's collar is (Foot joint + HEM_ABOVE_FOOT_M), never pooling
        # over the foot - the CHAMPIGNON sweats ran down to 7 cm and clashed with every shoe (the cargo joggers end at 15)
        mpp_, cz_, H_ = cam['metres_per_pixel'], cam['center'][2], cam['res'][1]
        hem_z = cz_ + (H_ / 2 - prow.max()) * mpp_
        min_z = lm['LeftFoot'][2] + HEM_ABOVE_FOOT_M
        stats['hem'] = {'hem_z_m': round(float(hem_z), 3), 'min_z_m': round(float(min_z), 3)}
        if hem_z < min_z - 0.005:
            why.append(f'hem: the legs end at {hem_z * 100:.1f} cm, below the top of a shoe ({min_z * 100:.1f} cm)')
        # leg openings: just above the hem the cuff surrounds the ankle with room on both sides, in every view
        bottom = prow.max()
        lo_r, hi_r = bottom - int(0.018 * 1000 * pxmm), bottom - int(0.004 * 1000 * pxmm)
        mid = cam['res'][0] // 2
        halves = [(0, mid), (mid, cam['res'][0])] if view in ('front', 'back') else [(0, cam['res'][0])]
        ok_e = tot_e = 0
        for c0, c1 in halves:
            for r in range(lo_r, hi_r + 1):
                bc, pc_ = np.nonzero(bm[r, c0:c1])[0], np.nonzero(pm[r, c0:c1])[0]
                if not len(bc) or not len(pc_):
                    continue
                tot_e += 2
                ok_e += int(bc.min() - pc_.min() >= CUFF_MARGIN_PX) + int(pc_.max() - bc.max() >= CUFF_MARGIN_PX)
        if tot_e:
            share = ok_e / tot_e
            stats['cuff'] = {'edges': tot_e, 'room_share': round(share, 2)}
            if share < 0.9:
                why.append(f'cuff: the leg opening leaves {CUFF_MARGIN_PX} px of room round the ankle on only '
                           f'{share:.0%} of its edges')
    if slot in COVER_SLOTS and len(prow) and dpng.exists():
        # chest room: between the belly and the armpits the top stands clear of the body outline (seen front, back AND
        # sides). A top drawn hugging the chest comes out of the 3D generator thin, gets scaled up to clear the skin,
        # and the scale-up lifts and widens its collar off the neck
        mpp, cz, H = cam['metres_per_pixel'], cam['center'][2], cam['res'][1]
        rz = lambda z: int(round(H / 2 - (z - cz) / mpp))
        dm, _ = background_mask(dpng)
        lo_r, hi_r = rz(lm['Spine2'][2] + 0.04), rz(lm['Spine'][2])
        gaps = []
        for r in range(lo_r, hi_r + 1):
            bc, dc = np.nonzero(bm[r])[0], np.nonzero(dm[r])[0]
            if not len(bc) or not len(dc) or bc.max() - bc.min() > 0.45 / mpp:  # arms in the row (front views)
                continue
            gaps += [(bc.min() - dc.min()) / pxmm, (dc.max() - bc.max()) / pxmm]
        if len(gaps) >= 10:
            g = np.array(gaps)
            share = float((g >= CHEST_ROOM_MM).mean())
            stats['chest'] = {'edges': len(g), 'room_share': round(share, 2), 'min_mm': round(float(g.min()), 1)}
            if share < 0.9:
                why.append(f'chest: only {share:.0%} of the chest/back outline stands {CHEST_ROOM_MM:.0f} mm off the body')
    if slot in COVER_SLOTS and view in ('front', 'back'):
        right = np.array(cam['views'][view]['right'], float)
        W = cam['res'][0]
        col = lambda x: int(round(W / 2 + float(np.dot(x, right)) / cam['metres_per_pixel']))
        z_arm = (lm['LeftArm'][2] + lm['LeftHand'][2]) / 2
        ra, rb = SH.shell_rows(cam, z_arm - 0.10)[1], SH.shell_rows(cam, z_arm + 0.10)[1]
        top_r, bot_r = min(ra, rb), max(ra, rb)
        bad = tot = cuff_bad = cuff_tot = 0
        for side in ('Left', 'Right'):
            c0, c1 = col(np.array(lm[f'{side}Arm']) + [0.04 if side == 'Left' else -0.04, 0, 0]), col(lm[f'{side}Hand'])
            cols = range(min(c0, c1), max(c0, c1) + 1)
            covered = [c for c in cols if pm[top_r:bot_r, c].any() and bm[top_r:bot_r, c].any()]
            if len(covered) < 6 + int(0.03 / cam['metres_per_pixel']):
                continue
            # the sleeve's own hem/cuff band (its outermost 3 cm - a ribbed cuff hugs the wrist by design; the 3D
            # inspection judges the opening) is not judged
            hem = int(0.03 / cam['metres_per_pixel'])
            outer_first = abs(covered[0] - W / 2) > abs(covered[-1] - W / 2)
            # ...but the cuff opening itself must still clear the wrist: a snug cuff makes the 3D sleeve end tighter
            # than the forearm, which then runs through the sleeve wall (the MONCHILL puffer, three mesh tries)
            for c in (covered[:hem] if outer_first else covered[-hem:]):
                ar, pr = np.nonzero(bm[top_r:bot_r, c])[0], np.nonzero(pm[top_r:bot_r, c])[0]
                cuff_tot += 1
                if pr.min() > ar.min() - SLEEVE_MARGIN_PX or pr.max() < ar.max() + SLEEVE_MARGIN_PX:
                    cuff_bad += 1
            covered = covered[hem:] if outer_first else covered[:-hem]
            for c in covered:
                ar, pr = np.nonzero(bm[top_r:bot_r, c])[0], np.nonzero(pm[top_r:bot_r, c])[0]
                tot += 1
                if pr.min() > ar.min() - SLEEVE_MARGIN_PX or pr.max() < ar.max() + SLEEVE_MARGIN_PX:
                    bad += 1
        if tot:
            share = 1 - bad / tot
            stats['sleeve'] = {'columns': tot, 'surrounds_share': round(share, 2)}
            if share < 0.9:
                why.append(f'sleeve: surrounds the arm with {SLEEVE_MARGIN_PX} px to spare in only {share:.0%} of '
                           f'its length')
        if cuff_tot:
            share = 1 - cuff_bad / cuff_tot
            stats['sleeve_cuff'] = {'columns': cuff_tot, 'surrounds_share': round(share, 2)}
            if share < 0.8:
                why.append(f'sleevecuff: the cuff opening clears the wrist by {SLEEVE_MARGIN_PX} px in only {share:.0%} '
                           f'of its width')
    return not why, stats, why


def dress_and_split(d, a, piece, out_piece, what, keep, log):
    (d / '02_dressed').mkdir(exist_ok=True)
    front = d / '02_dressed' / 'front.png'
    codex(d, f"""Use your image generation tool. Image 1 is a 3D render of a dressed character (front view). Image 2 is the
outfit concept. Generate ONE image: image 1 with ONE item added - {what} - worn the way image 2 shows it.
{keep}
Save the image as ./02_dressed/front.png. Reply with only the saved path.""",
          [d / '00_under' / 'front.png', d / 'concept.png'], front, log)
    seen = {'back': "from BEHIND (the character's right is on the image RIGHT)",
            'left': "from the character's LEFT side (the character faces the image LEFT edge; its right side is "
                    "the FAR side, hidden behind the body)",
            'right': "from the character's RIGHT side (the character faces the image RIGHT edge; its left side is "
                     "the FAR side, hidden behind the body)"}
    jobs = []
    for view, how in seen.items():
        out = d / '02_dressed' / f'{view}.png'
        jobs.append((f"""Use your image generation tool. Image 1 is a 3D render of a dressed character seen {how}. Image 2 is the
same character from the front with one item added: {what}. Generate ONE image: image 1 (this exact camera) with
exactly that same item added, as it looks {how} - same size, colours, strap width and position on the body as in
image 2.
3D CONSISTENCY: first work out from image 2 where every part of the item is on the body in 3D - which shoulder the
strap goes over, which hip the bag hangs at, whether it sits in front of or beside the body. Then draw ONLY what this
camera can see: parts on the far side of the body are hidden behind it (e.g. seen from the side opposite the bag, the
bag is hidden and only the strap over the near shoulder shows); never move a part to the near side to make it visible.
{keep}
Save the image as ./02_dressed/{view}.png. Reply with only the saved path.""",
                     [d / '00_under' / f'{view}.png', front, d / 'concept.png'], out))
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(lambda j: codex(d, j[0], j[1], j[2], log), jobs))

    # 3. the piece alone, at the same place
    split(d, [out_piece], log)


if __name__ == '__main__':
    main()
