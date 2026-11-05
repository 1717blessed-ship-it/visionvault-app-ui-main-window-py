from collections import Counter
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from PIL import Image
import pytest

from app.planchas.editor import PlanchaEditor, preview_geometry
from app.planchas.model import PlanchaItem,PlanchaProject,PaginationError
from app.planchas.optional_distribution import compare_distribution,valid_layout,indicators
from app.planchas.output_safety import ExportValidationError
from tools.benchmark_creator_sprint2 import source,normal


@pytest.mark.parametrize('count',[10,25,50,100,200])
@pytest.mark.parametrize('mixed',[False,True])
def test_baseline_geometry_unchanged_and_comparison_safe(count,mixed):
    project=source(count,mixed)
    before=project.to_dict()
    baseline=normal(source(count,mixed))
    comparison=compare_distribution(project)
    assert [p.to_dict() for p in comparison.normal]==[p.to_dict() for p in baseline]
    assert len(comparison.selected)<=len(baseline)
    assert valid_layout(comparison.selected,[i for p in baseline for i in p.items])
    assert project.to_dict()==before
    repeated=compare_distribution(project)
    assert [p.to_dict() for p in repeated.selected]==[p.to_dict() for p in comparison.selected]
    if not comparison.improved:
        assert [p.to_dict() for p in comparison.selected]==[p.to_dict() for p in baseline]


@pytest.mark.parametrize('margin,gap,workspace',[(.3,.17,'a4'),(.2,.1,'a5'),(.15,.07,'franja')])
def test_custom_geometry_formats_and_unequal_design_counts(margin,gap,workspace):
    project=source(100,True);project.margin_cm=margin;project.gap_cm=gap;project.workspace_format=workspace
    result=compare_distribution(project)
    old=[i for page in result.normal for i in page.items]
    assert valid_layout(result.selected,old)
    assert Counter(i.path for p in result.selected for i in p.items)==Counter(i.path for i in project.items)
    assert all(p.margin_cm==margin and p.gap_cm==gap and p.workspace_format==workspace for p in result.selected)


def test_measured_hole_improvement_and_fallback_for_too_small_holes():
    improved=compare_distribution(source(200,True))
    assert improved.improved and (len(improved.normal),len(improved.selected))==(8,5)
    no_improvement=compare_distribution(source(10,False))
    assert not no_improvement.improved
    assert indicators(improved.selected)['placed']==200
    assert indicators(improved.selected)['pending']==0


def test_unequal_40_35_25_reconciles_each_design_and_existing_pages():
    project=source(100,True)
    for n,item in enumerate(project.items):
        group=0 if n<40 else 1 if n<75 else 2
        item.path=f'DISEÑO-{group}';item.group_id=f'grupo-{group}'
    baseline=normal(PlanchaProject.from_dict(project.to_dict()))
    comparison=compare_distribution(baseline[0],pages=baseline)
    assert [p.to_dict() for p in comparison.normal]==[p.to_dict() for p in baseline]
    assert Counter(i.path for p in comparison.selected for i in p.items)=={'DISEÑO-0':40,'DISEÑO-1':35,'DISEÑO-2':25}


def test_recovered_modes_and_calibration_metadata_are_preserved():
    project=source(100,True)
    project._persisted_options={'print_settings':{'scale':97.27},'cut_settings':{'inset_mm':1.5}}
    result=compare_distribution(project)
    assert result.improved
    for page in result.selected:
        assert page.to_dict()['print_settings']=={'scale':97.27}
        assert page.to_dict()['cut_settings']=={'inset_mm':1.5}
        assert page.to_dict()['distribution_mode']=='optimized_gaps_v1'
    fallback=source(10,False)
    fallback._persisted_options=project._persisted_options.copy()
    result=compare_distribution(fallback)
    assert not result.improved
    assert result.selected[0].to_dict()['print_settings']=={'scale':97.27}


def test_existing_mixed_packer_is_the_exact_normal_reference():
    from app.planchas.sticker_mixed import StickerMixedPacker
    project=source(25,True)
    for i in project.items:i.nominal_size_cm=5
    pages=StickerMixedPacker().pack(project.items).projects
    result=compare_distribution(pages[0],pages=pages)
    assert [p.to_dict() for p in result.normal]==[p.to_dict() for p in pages]
    if result.improved:
        assert valid_layout(result.selected,[i for p in pages for i in p.items])


@pytest.mark.parametrize('constraint',['free','locked','sheet','duplicate','unknown_context','materials','formats','invalid_gap'])
def test_incompatible_or_manual_inputs_are_rejected(constraint):
    project=source(100,True); kwargs={}
    if constraint=='free':project.project_type='sticker_free'
    if constraint=='locked':project.items[0].locked=True
    if constraint=='sheet':project.items[0].production_unit_kind='sheet'
    if constraint=='duplicate':project.items[1].item_id=project.items[0].item_id
    if constraint=='unknown_context':project.items[0].order_job_id=7
    if constraint=='materials':
        kwargs['contexts']={i.item_id:('Vinilo' if n else 'Papel','a4','item') for n,i in enumerate(project.items)}
    if constraint=='formats':
        other=source(10,True);other.workspace_format='a5';kwargs['pages']=[project,other]
    if constraint=='invalid_gap':project.gap_cm=-.1
    before=project.to_dict()
    with pytest.raises(ValueError):compare_distribution(project,**kwargs)
    assert project.to_dict()==before


def test_impossible_is_explicit_not_a_shorter_success():
    project=PlanchaProject([PlanchaItem(path='huge',name='Huge',width_cm=30,height_cm=30)])
    with pytest.raises(PaginationError) as error: compare_distribution(project)
    assert error.value.report[0]['unplaced']==1


def test_persistence_preview_export_and_missing_sources(tmp_path):
    from collections import OrderedDict
    path=tmp_path/'FICTICIO.png';Image.new('RGBA',(100,100),'red').save(path)
    project=source(100,True)
    for i in project.items:i.path=str(path)
    pages=compare_distribution(project).selected
    manifest=tmp_path/'set.json';PlanchaProject.save_pages(manifest,pages)
    restored=PlanchaProject.load_pages(manifest)
    assert [p.to_dict() for p in restored]==[p.to_dict() for p in pages]
    editor=object.__new__(PlanchaEditor)
    editor.current_project_index=0;editor.production_sticker_cache=OrderedDict();editor.production_sticker_cache_pixels=0
    editor.prepared_production_sticker=lambda *a:None
    editor.project=restored[0]
    geometry=[preview_geometry(i) for i in editor.project.items]
    sheet=editor.render_sheet()
    assert [preview_geometry(i) for i in editor.project.items]==geometry
    assert sheet.size==(2480,3508)
    for item,rect in zip(editor.project.items,geometry):
        center=(round((rect['design_x_cm']+item.width_cm/2)/2.54*300),
                round((rect['design_y_cm']+item.height_cm/2)/2.54*300))
        assert sheet.getpixel(center)[3]>0
    path.unlink()
    with pytest.raises(ExportValidationError):editor.render_sheet()


def ui_stub(project):
    return SimpleNamespace(project=project,all_projects=[],plancha_id=None,project_path='',preserve_layout=False,
        database=None,format_heading=SimpleNamespace(set=lambda _:None),selected_ids=set(),
        snapshot=lambda:None,render=lambda:None,update_plancha_navigation=lambda:None,status_message=lambda _:None)


def test_ui_cancel_preserves_entire_composition(tmp_path,monkeypatch):
    image=tmp_path/'image.png';Image.new('RGBA',(20,20),'red').save(image)
    project=source(100,True)
    for i in project.items:i.path=str(image)
    ui=ui_stub(project);before=project.to_dict()
    monkeypatch.setattr('app.planchas.editor.messagebox.askyesno',lambda *a,**k:False)
    assert PlanchaEditor.compare_optional_distribution(ui) is False
    assert project.to_dict()==before and ui.all_projects==[]


def test_ui_applies_only_after_confirmation(tmp_path,monkeypatch):
    image=tmp_path/'image.png';Image.new('RGBA',(20,20),'red').save(image)
    project=source(100,True)
    for i in project.items:i.path=str(image)
    ui=ui_stub(project)
    monkeypatch.setattr('app.planchas.editor.messagebox.askyesno',lambda *a,**k:True)
    assert PlanchaEditor.compare_optional_distribution(ui)
    assert ui.max_planchas==3 and sum(len(p.items) for p in ui.all_projects)==100


def test_order_batch_reservations_remain_unchanged_and_block_ui(tmp_path,monkeypatch):
    from app.database.database import ImageDatabase
    from app.services.production_batch_service import ProductionBatchService
    from app.services.order_production_service import OrderProductionService
    image=tmp_path/'FICTICIO.png';Image.new('RGBA',(100,100),'red').save(image)
    db=ImageDatabase(tmp_path/'isolated.db')
    db.connection.execute('INSERT INTO images(path,name,extension,size,modified,caption,visible_width,visible_height) VALUES(?,?,?,?,?,?,?,?)',
                          (str(image),'FICTICIO','.png',1,1,'FICTICIO',100,100));db.connection.commit()
    oid=db.create_order_with_details('FICTICIO',jobs=[{'title':'Stickers','material':'Vinilo','quantity':100,
        'unit_kind':'item','distribution_policy':'complete'}],designs=[{'image_path':str(image),'quantity':100,'size_cm':5,
        'order_job_index':0,'unit_kind':'item','packing_mode':'standard_five_bands'}])
    jid=db.order_jobs(oid)[0]['id'];service=ProductionBatchService(db)
    preview=OrderProductionService(db).preview(oid,{jid:100})
    project=preview.groups[0].projects[0]
    # Comparing unreserved compatible copies is read-only.
    before='\n'.join(db.connection.iterdump())
    all_pages=preview.groups[0].projects
    result=compare_distribution(project,pages=all_pages,
        contexts={i.item_id:('Vinilo','a4','item') for p in all_pages for i in p.items})
    assert '\n'.join(db.connection.iterdump())==before
    preview.groups[0].projects=result.selected
    service.save(preview)
    assert db.connection.execute("SELECT COUNT(*),COUNT(DISTINCT requested_unit_key) FROM plancha_item_assignments WHERE state='prepared'").fetchone()[:]==(100,100)
    before='\n'.join(db.connection.iterdump())
    ui=ui_stub(project);ui.database=db
    notices=[]
    monkeypatch.setattr('app.planchas.output_safety.logger.exception',lambda *a:None)
    monkeypatch.setattr('tkinter.messagebox.showerror',lambda *a,**kw:notices.append(a))
    assert PlanchaEditor.compare_optional_distribution(ui) is False
    assert notices and 'reservadas' in notices[0][1]
    assert '\n'.join(db.connection.iterdump())==before
    db.close()
