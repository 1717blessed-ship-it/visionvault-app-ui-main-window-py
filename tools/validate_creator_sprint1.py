"""Evidencia aislada de fidelidad: no base operativa ni spool de impresión."""
from collections import OrderedDict
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from PIL import Image
from app.planchas.editor import PlanchaEditor
from app.planchas.model import PlanchaItem, PlanchaProject, PaginationError
from app.planchas.output_safety import save_image
from app.planchas.production_geometry import PRINT_SCALE,CUT_INSET_MM


def render(project):
    editor=object.__new__(PlanchaEditor)
    editor.project=project
    editor.current_project_index=0
    editor.production_sticker_cache=OrderedDict()
    editor.production_sticker_cache_pixels=0
    editor.prepared_production_sticker=lambda *args: None
    return editor.render_sheet()


def main():
    folder=ROOT/'artifacts'/'creator-s1-acceptance-20261023'
    folder.mkdir(exist_ok=False)
    source=folder/'FICTICIO.png'
    Image.new('RGBA',(200,200),'red').save(source)
    items=[PlanchaItem(path=str(source),name=f'FICTICIO {i}',width_cm=4.8,height_cm=4.8) for i in range(6)]
    project=PlanchaProject(items,margin_cm=.3,gap_cm=.12)
    project.optimize()
    project._persisted_options={'print_settings':{'paper':'A4','orientation':'Vertical','scale':97.27},
                                'cut_settings':{'inset_mm':CUT_INSET_MM}}
    before=render(project)
    project.save(folder/'project.json')
    restored=PlanchaProject.load(folder/'project.json')
    after=render(restored)
    save_image(before,folder/'before.png','PNG',dpi=(300,300))
    save_image(after,folder/'after.png','PNG',dpi=(300,300))
    hashes=[hashlib.sha256(sheet.tobytes()).hexdigest() for sheet in (before,after)]
    assert hashes[0]==hashes[1]
    assert project.to_dict()==restored.to_dict()
    report={'geometry_before':project.to_dict(),'geometry_after':restored.to_dict(),
            'pixel_sha256_before_after':hashes,'dpi':300,'size_px':before.size,
            'print_scale':PRINT_SCALE,'cut_inset_mm':CUT_INSET_MM,'physical_validated':False}
    try:
        PlanchaProject.calculate_pagination([PlanchaItem(path=str(source),name='Imposible',width_cm=30,height_cm=30)])
    except PaginationError as error:
        report['rejected']=error.report
    (folder/'observations.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'pixel_hashes':hashes,'dimensions_px':before.size,'same_geometry':True},indent=2))


if __name__=='__main__':
    main()
