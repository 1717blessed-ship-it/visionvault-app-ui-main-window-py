"""Evidencia renderizada sin base ni impresión: normal y alternativa opcional."""
from collections import OrderedDict
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from PIL import Image,ImageDraw
from app.planchas.editor import PlanchaEditor,preview_geometry
from app.planchas.model import PlanchaProject
from app.planchas.optional_distribution import compare_distribution,indicators,valid_layout
from app.planchas.output_safety import save_image
from tools.benchmark_creator_sprint2 import source


def render(project):
    editor=object.__new__(PlanchaEditor);editor.project=project;editor.current_project_index=0
    editor.production_sticker_cache=OrderedDict();editor.production_sticker_cache_pixels=0
    editor.prepared_production_sticker=lambda *args:None
    geometry=[preview_geometry(i) for i in project.items]
    sheet=editor.render_sheet()
    assert geometry==[preview_geometry(i) for i in project.items]
    return sheet


def main():
    folder=ROOT/'artifacts'/'creator-s2-acceptance-20261024';folder.mkdir(exist_ok=False)
    files=[]
    for n,color in enumerate(('red','green','blue')):
        path=folder/f'FICTICIO-{n}.png';image=Image.new('RGBA',(200,200),color)
        ImageDraw.Draw(image).text((20,80),f'FICTICIO {n}',fill='white');image.save(path);files.append(path)
    project=source(100,True)
    for i in project.items:i.path=str(files[int(i.name[-1])])
    comparison=compare_distribution(project)
    assert comparison.improved and valid_layout(comparison.selected,[i for p in comparison.normal for i in p.items])
    report={'physical_validation':False,'normal':indicators(comparison.normal),'optimized':indicators(comparison.selected)}
    hashes=[]
    for mode,pages in [('normal',comparison.normal),('optimized',comparison.selected)]:
        PlanchaProject.save_pages(folder/f'{mode}.json',pages)
        restored=PlanchaProject.load_pages(folder/f'{mode}.json')
        assert [p.to_dict() for p in pages]==[p.to_dict() for p in restored]
        for n,(page,reopened) in enumerate(zip(pages,restored),1):
            sheet=render(page);after=render(reopened)
            before_hash=hashlib.sha256(sheet.tobytes()).hexdigest()
            after_hash=hashlib.sha256(after.tobytes()).hexdigest()
            assert before_hash==after_hash
            save_image(sheet,folder/f'{mode}-{n:02d}.png','PNG',dpi=(300,300))
            hashes.append({'mode':mode,'page':n,'before':before_hash,'after':after_hash})
    report['pixel_hashes']=hashes
    (folder/'observations.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'normal':report['normal'],'optimized':report['optimized'],'pages_verified':len(hashes)},indent=2))


if __name__=='__main__':main()
