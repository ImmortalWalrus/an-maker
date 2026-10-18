"""The fitted tee's texture layout: ONE true-scale sewing pattern shared by every variant (sleeveless / short / elbow,
standard / crop). Pattern pieces are laid out in metres on a canvas CANVAS_W x CANVAS_H; a shorter sleeve or a cropped
hem simply uses less of its piece, so one texture kit dresses all six variants at the same print scale.

  piece        pattern coordinates (metres)                                     placed at (canvas metres)
  front        u: arc length around the torso from the centre front (+ = wearer's left), v: height above Z_LO
  back         u: arc length from the centre back (+ = wearer's right, so it reads from behind), v: as front
  left/right   u: angle around the arm x SLEEVE_R (the unroll seam runs under the arm), v: distance down the sleeve
  sleeve       from the shoulder split

Used by shell_garment.py (inside Blender) and tee_kit.py (system Python), so it imports nothing but the standard library.
"""

CANVAS_W, CANVAS_H = 1.03, 0.74      # metres of fabric the texture covers (aspect 1.39 -> e.g. 2048 x 1472 px)
TORSO_W, TORSO_H = 0.50, 0.50        # front / back pieces: arc +-0.25 m, height 0.50 m from Z_LO (hips - 4.5 cm)
SLEEVE_W, SLEEVE_H = 0.35, 0.20      # sleeve pieces: circumference (2 pi SLEEVE_R) x length down the arm
SLEEVE_R = 0.055                     # unroll radius around the arm (a sleeve 8 mm off a ~4.5 cm arm)
Z_LO_BELOW_HIPS = 0.045
GAP = 0.01
# centre of each piece's u = 0 line and bottom of its v range, in canvas metres
ORIGIN = {
    'front': (GAP + TORSO_W / 2, GAP + SLEEVE_H + GAP),
    'back': (GAP + TORSO_W + GAP + TORSO_W / 2, GAP + SLEEVE_H + GAP),
    'left': (GAP + SLEEVE_W / 2, GAP),
    'right': (GAP + SLEEVE_W + GAP + SLEEVE_W / 2, GAP),
}
SIZE = {'front': (TORSO_W, TORSO_H), 'back': (TORSO_W, TORSO_H), 'left': (SLEEVE_W, SLEEVE_H), 'right': (SLEEVE_W, SLEEVE_H)}


def tex_size(width_px):
    """Texture pixel size for a given width (height keeps the canvas aspect, rounded to a multiple of 16)."""
    return width_px, int(round(width_px * CANVAS_H / CANVAS_W / 16)) * 16


def px_per_m(width_px):
    return width_px / CANVAS_W
