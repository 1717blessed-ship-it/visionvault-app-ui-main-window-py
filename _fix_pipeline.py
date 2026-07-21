"""
Fix 1: variables inexistentes en analysis_data (hole_details, holes_filled,
        removed_particles) que causan NameError en el bloque de QC.
Fix 2: has_grey_border=False faltante en los ClassifyResult manuales.
"""
from pathlib import Path

f = Path(__file__).parent / "app/stickers/pipeline.py"
text = f.read_text(encoding="utf-8")

# ── Fix 1: quitar las 3 claves que referencian variables inexistentes ─────
OLD_ANALYSIS = (
    '            "protection_zones": [list(z) for z in (protection_zones or [])],\n'
    '        }'
)
NEW_ANALYSIS = (
    '            "protection_zones": [list(z) for z in (protection_zones or [])],\n'
    '            # ── campos extendidos (vacíos cuando no aplican) ──────────\n'
    '            "holes_filled": 0,\n'
    '            "hole_analysis": [],\n'
    '            "removed_particles_count": 0,\n'
    '            "removed_particles": [],\n'
    '        }'
)
if OLD_ANALYSIS in text:
    text = text.replace(OLD_ANALYSIS, NEW_ANALYSIS)
    print("Fix1 OK")
else:
    # buscar y eliminar solo las líneas problemáticas
    for bad in (
        '            "holes_detected": len(hole_details),\n',
        '            "holes_filled": holes_filled,\n',
        '            "hole_analysis": hole_details,\n',
        '            "removed_particles_count": len(removed_particles),\n',
        '            "removed_particles": removed_particles,\n',
    ):
        if bad in text:
            text = text.replace(bad, "")
    print("Fix1 fallback OK")

# ── Fix 2: has_grey_border=False en ClassifyResult preserve_full_image ───
OLD_CR1 = (
    '                has_white_border=False,\n'
    '                has_black_outline=False,\n'
    '                uniform_background=False,\n'
    '                is_photo=False,\n'
    '                bg_color=(0, 0, 0),\n'
    '            )\n'
    '            rgba.putalpha(Image.new("L", rgba.size, 255))'
)
NEW_CR1 = (
    '                has_white_border=False,\n'
    '                has_grey_border=False,\n'
    '                has_black_outline=False,\n'
    '                uniform_background=False,\n'
    '                is_photo=False,\n'
    '                bg_color=(0, 0, 0),\n'
    '            )\n'
    '            rgba.putalpha(Image.new("L", rgba.size, 255))'
)
if OLD_CR1 in text:
    text = text.replace(OLD_CR1, NEW_CR1)
    print("Fix2a OK")
else:
    print("Fix2a MISS - ya tiene has_grey_border o texto distinto")

# ── Fix 2b: has_grey_border=False en ClassifyResult mask_override ─────────
OLD_CR2 = (
    '                has_white_border=False,\n'
    '                has_black_outline=False,\n'
    '                uniform_background=False,\n'
    '                is_photo=False,\n'
    '                bg_color=(0, 0, 0),\n'
    '            )\n'
    '        else:\n'
    '            classify_result = self.classify(rgba, mode_override=mode_override)'
)
NEW_CR2 = (
    '                has_white_border=False,\n'
    '                has_grey_border=False,\n'
    '                has_black_outline=False,\n'
    '                uniform_background=False,\n'
    '                is_photo=False,\n'
    '                bg_color=(0, 0, 0),\n'
    '            )\n'
    '        else:\n'
    '            classify_result = self.classify(rgba, mode_override=mode_override)'
)
if OLD_CR2 in text:
    text = text.replace(OLD_CR2, NEW_CR2)
    print("Fix2b OK")
else:
    print("Fix2b MISS - ya tiene has_grey_border o texto distinto")

f.write_text(text, encoding="utf-8")

# Verificar con ast
import ast, sys
try:
    ast.parse(text)
    print("Syntax OK")
except SyntaxError as e:
    print(f"Syntax ERR line {e.lineno}: {e.msg}")
    sys.exit(1)
