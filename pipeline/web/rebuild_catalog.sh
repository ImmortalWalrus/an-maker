#!/bin/bash
# Rebuild the wardrobe end to end: refit every piece (step 6), equip + inspect every look the customizer can show
# (each piece alone, every overlapping pair, the full outfit), then export the web assets. Stops on any failed check.
# Run from the repo root: bash pipeline/web/rebuild_catalog.sh
set -e
B="$(python -c "import sys; sys.path.insert(0, 'pipeline/tpose'); import anmaker_config as C; print(C.BLENDER)")"
T=pipeline/tpose
HAIR=hoodie-boy:navy_teal_tousled_hair
TEE=hoodie-boy-tee4:white_crew_neck_tshirt
JOG=hoodie-boy-joggers5:olive_cargo_joggers
BUN=${BUN:-hoodie-boy-hoodiebag4:black_graphic_hoodie_with_gray_crossbody_bag}
SHOE=hoodie-boy:multicolor_high_top_sneakers
ALL="$HAIR $TEE $JOG $BUN $SHOE"

for o in $(for s in $ALL; do echo "${s%%:*}"; done | sort -u); do
  echo "== fit $o"
  "$B" -b --factory-startup -P $T/s6_fit.py -- Outfits/$o Xander 2>&1 | grep -E "Error|Traceback" && exit 1 || true
done

failed=0
look() {  # look <name> <pieces...>
  local n=$1; shift
  "$B" -b --factory-startup -P $T/equip.py -- --base Xander --name "$n" --pieces "$@" 2>&1 | grep -E "Error|Traceback" && exit 1
  local r
  r=$("$B" -b --factory-startup -P $T/inspect_look.py -- Outfits/_looks/$n Xander 2>&1 | grep -E "^\[inspect\] (PASS|FAIL)|^  [a-z]|shell warning|Traceback")
  echo "== $n"; echo "$r"
  echo "$r" | grep -q "^\[inspect\] PASS" || failed=1
}
for s in $ALL; do look "web-${s#*:}" "$s"; done          # each piece alone (also the customizer's skin masks)
look web-tee-joggers $TEE $JOG
look combo-jog-shoes $JOG $SHOE
look combo-jog-bundle $JOG $BUN
look combo-tee-bundle $TEE $BUN
look full-look $ALL
[ $failed = 0 ] || { echo "REBUILD STOPPED: a look failed inspection"; exit 1; }

echo "== export"
"$B" -b --factory-startup -P pipeline/web/export_web.py -- --base Xander --out web/customizer/assets --pieces $ALL 2>&1 \
  | grep -E "\[web\]|Error|Traceback"
python pipeline/web/glb_to_gltf.py web/customizer/assets
# the body was re-exported: rebuild the two asset sets that depend on its vertex order (face masks, feminine build)
python pipeline/web/build_face_masks.py --out web/customizer/assets
python pipeline/web/build_feminine.py --out web/customizer/assets
# legs must not be joined by fabric or mixed weights below the knees (the webbing seen in animation) - except skirts
# and dresses, where fabric between the legs is correct (their hems are weighted at runtime)
for s in $ALL; do
  k=${s#*:}
  case "$k" in *skirt*|*dress*) echo "leg bridge: $k skipped (skirt/dress)"; continue;; esac
  if [ "$(python -c "import json;print(json.load(open('Outfits/${s%%:*}/outfit.json'))['pieces'][[p['key'] for p in json.load(open('Outfits/${s%%:*}/outfit.json'))['pieces']].index('$k')]['slot'])")" = bottom ]; then
    python -I pipeline/anim/check_leg_bridge.py web/customizer/assets/piece_$k.glb || { echo "REBUILD STOPPED: $k joins the legs"; exit 1; }
  fi
done
# live page files from the animation session that this export does not write (keep them when publishing):
#   assets/anims.json, anims.bin.txt, feminine*.json/png, face_masks.json, lip_sdf.png,
#   makeup.json, makeup_clementine.png, makeup_alex.png, makeup_sticker.png (build_makeup.py; body-independent)
echo REBUILD DONE
