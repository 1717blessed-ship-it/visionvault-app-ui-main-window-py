from collections import OrderedDict
from pathlib import Path
from types import SimpleNamespace
import hashlib
import json

from PIL import Image
import pytest

from app.planchas.editor import PlanchaEditor
from app.planchas.model import PlanchaItem, PlanchaProject, PaginationError
from app.planchas.output_safety import validate_sources, ExportValidationError, atomic_write, save_image
from app.planchas.production_geometry import PRINT_SCALE, CUT_INSET_MM, validate_print_scale


def item(path, **kwargs):
    return PlanchaItem(path=str(path), name='FICTICIO', width_cm=3, height_cm=3,
                       x_cm=.3, y_cm=.3, **kwargs)


def renderer(project):
    editor = object.__new__(PlanchaEditor)
    editor.project = project
    editor.current_project_index = 0
    editor.production_sticker_cache = OrderedDict()
    editor.production_sticker_cache_pixels = 0
    editor.prepared_production_sticker = lambda *args: None
    return editor


@pytest.fixture
def valid(tmp_path):
    path = tmp_path/'FICTICIO.png'
    Image.new('RGBA', (100,100), 'red').save(path)
    return path


@pytest.mark.parametrize('kind', ['missing','corrupt','inaccessible','transparent','empty','partial'])
def test_invalid_sources_never_return_a_document(tmp_path, valid, monkeypatch, kind):
    path = tmp_path/'INVALIDO.png'
    entries = [item(path)]
    if kind == 'corrupt':
        path.write_bytes(b'not-an-image')
    elif kind == 'inaccessible':
        original = Image.open
        def inaccessible(target, *args, **kwargs):
            if str(target) == str(path):
                raise PermissionError('Acceso denegado simulado')
            return original(target, *args, **kwargs)
        monkeypatch.setattr(Image, 'open', inaccessible)
    elif kind == 'transparent':
        Image.new('RGBA',(10,10)).save(path)
    elif kind == 'empty':
        entries = []
    elif kind == 'partial':
        entries.append(item(valid))
    project = PlanchaProject(entries)
    with pytest.raises(ExportValidationError) as error:
        renderer(project).render_sheet()
    if entries:
        assert 'FICTICIO' in str(error.value)
        assert str(path) in str(error.value)
        assert entries[0].item_id in str(error.value)


@pytest.mark.parametrize('failure', ['write','replace'])
def test_atomic_failure_preserves_previous_export(tmp_path, monkeypatch, failure):
    path = tmp_path/'previous.png'
    path.write_bytes(b'VALID-OLD-EXPORT')
    before = path.read_bytes()
    def write(temporary):
        temporary.write_bytes(b'PARTIAL')
        if failure == 'write':
            raise OSError('Disco lleno simulado')
    if failure == 'replace':
        monkeypatch.setattr('app.planchas.output_safety.os.replace', lambda *args: (_ for _ in ()).throw(PermissionError('Locked')))
    with pytest.raises(OSError):
        atomic_write(path,write)
    assert path.read_bytes() == before
    assert list(tmp_path.iterdir()) == [path]


def test_roundtrip_process_config_and_export_bytes_are_identical(tmp_path, valid):
    project = PlanchaProject([item(valid)], margin_cm=.3, gap_cm=.17, project_type='sticker_free')
    project._persisted_options = {'print_settings': {'scale':97.27,'paper':'A4','orientation':'Vertical'},
                                 'cut_settings': {'inset_mm':1.5},'horizontal_gap_cm':.17,'vertical_gap_cm':.19}
    before = renderer(project).render_sheet().tobytes()
    path = tmp_path/'project.json'
    project.save(path)
    # A different global profile must not override the saved one after reopening.
    restored = PlanchaProject.load(path)
    editor = renderer(restored)
    editor.database = SimpleNamespace(printing_config=lambda:{'scale':100,'paper':'OTHER'})
    assert editor._current_print_config() == project._persisted_options['print_settings']
    assert restored.to_dict() == project.to_dict()
    assert editor.render_sheet().tobytes() == before
    assert restored.margin_cm == .3 and restored.gap_cm == .17
    assert PRINT_SCALE == .9727 and CUT_INSET_MM == 1.5


def test_historical_absent_fields_differ_from_explicit_zero():
    historical = PlanchaProject.from_dict({'items': [],'workspace_format':'a4'})
    explicit = PlanchaProject.from_dict({'items': [],'margin_cm':0,'gap_cm':0})
    assert (historical.margin_cm,historical.gap_cm) == (.15,.05)
    assert (explicit.margin_cm,explicit.gap_cm) == (0,0)
    with pytest.raises(ValueError):
        PlanchaProject.from_dict({'margin_cm':-1})


def test_multipage_manifest_preserves_every_page(tmp_path):
    items = [PlanchaItem(path=f'{i}.png', name=str(i),width_cm=4.8,height_cm=4.8) for i in range(50)]
    pages = PlanchaProject.calculate_pagination(items,margin_cm=.3,gap_cm=.12)
    path = tmp_path/'set.json'
    PlanchaProject.save_pages(path,pages)
    assert [p.to_dict() for p in PlanchaProject.load_pages(path)] == [p.to_dict() for p in pages]


@pytest.mark.parametrize('scale', [97.27,100,'97.27'])
def test_scale_profiles_apply_same_calibration_once(scale):
    assert validate_print_scale(scale)
    from app.printing.windows_print import PRINT_SCALE as backend_scale
    assert backend_scale == PRINT_SCALE
    assert 10*backend_scale == pytest.approx(9.727)
    assert 10*backend_scale != pytest.approx(10*backend_scale**2)


@pytest.mark.parametrize('scale', [0,90,float('nan'),None,'bad'])
def test_unknown_scale_is_not_silently_recalibrated(scale):
    assert not validate_print_scale(scale)


def test_impossible_pagination_reports_all_units_no_partial_confirmation():
    valid = PlanchaItem(path='small',name='Small',width_cm=4,height_cm=4)
    huge = PlanchaItem(path='huge',name='Huge',width_cm=30,height_cm=30)
    with pytest.raises(PaginationError) as error:
        PlanchaProject.calculate_pagination([valid,huge])
    report = error.value.report[0]
    assert report['requested'] == report['placed'] + report['unplaced'] == 1
    assert report['unplaced'] == 1
    assert 'A4' in report['reason']
    assert sum(len(p.items) for p in error.value.pages) == 1


@pytest.mark.parametrize('quantity', [50,100,200])
def test_extra_pages_reconcile_exactly(quantity):
    items = [PlanchaItem(path='same', name='Repeated',width_cm=4.8,height_cm=4.8) for _ in range(quantity)]
    pages = PlanchaProject.calculate_pagination(items)
    assert sum(len(p.items) for p in pages) == quantity
    assert {i.item_id for p in pages for i in p.items} == {i.item_id for i in items}


def test_export_failure_leaves_reservations_and_production_untouched(tmp_path, valid):
    from app.database.database import ImageDatabase
    from app.services.production_batch_service import ProductionBatchService
    from app.services.order_production_service import OrderProductionService
    db = ImageDatabase(tmp_path/'isolated.db')
    db.connection.execute('INSERT INTO images(path,name,extension,size,modified,caption,visible_width,visible_height) VALUES(?,?,?,?,?,?,?,?)',
                          (str(valid),'FICTICIO','.png',1,1,'FICTICIO',100,100))
    db.connection.commit()
    oid = db.create_order_with_details('FICTICIO', jobs=[{'title':'Stickers','material':'Vinilo','quantity':3,
        'unit_kind':'item','distribution_policy':'complete'}], designs=[{'image_path':str(valid),'quantity':3,
        'size_cm':5,'order_job_index':0,'unit_kind':'item','packing_mode':'standard_five_bands'}])
    jid = db.order_jobs(oid)[0]['id']
    service = ProductionBatchService(db)
    service.save(OrderProductionService(db).preview(oid,{jid:3}))
    assert db.connection.execute("SELECT COUNT(*) FROM plancha_item_assignments WHERE state='prepared'").fetchone()[0] == 3
    before = db.connection.iterdump()
    digest = hashlib.sha256('\n'.join(before).encode()).hexdigest()
    project = PlanchaProject([item(tmp_path/'missing.png')])
    with pytest.raises(ExportValidationError):
        renderer(project).render_sheet()
    assert hashlib.sha256('\n'.join(db.connection.iterdump()).encode()).hexdigest() == digest
    assert db.order(oid)['status'] != 'Entregado'
    db.close()


def test_failed_export_action_does_not_replace_existing_png(tmp_path):
    target = tmp_path/'final.png'
    target.write_bytes(b'previous-valid-export')
    editor = renderer(PlanchaProject([item(tmp_path/'missing.png')]))
    editor.database = None
    editor.all_projects = []
    editor.plancha_id = None
    with pytest.raises(ExportValidationError):
        editor.export_final(silent=True,custom_path=str(target))
    assert target.read_bytes() == b'previous-valid-export'


def test_restore_in_fresh_process_preserves_geometry_and_pixels(tmp_path, valid):
    import subprocess
    import sys
    project = PlanchaProject([item(valid)],margin_cm=.4,gap_cm=.18,project_type='sticker_free')
    project.items[0].x_cm = project.items[0].y_cm = .4
    project._persisted_options = {'print_settings':{'scale':97.27,'paper':'A4','orientation':'Vertical'}}
    path = tmp_path/'reopen.json'
    project.save(path)
    expected = hashlib.sha256(renderer(project).render_sheet().tobytes()).hexdigest()
    code = '''import sys,hashlib,json
from collections import OrderedDict
from app.planchas.model import PlanchaProject
from app.planchas.editor import PlanchaEditor
p=PlanchaProject.load(sys.argv[1])
e=object.__new__(PlanchaEditor); e.project=p; e.current_project_index=0
e.production_sticker_cache=OrderedDict(); e.production_sticker_cache_pixels=0
e.prepared_production_sticker=lambda *a: None
print(json.dumps([p.margin_cm,p.gap_cm,hashlib.sha256(e.render_sheet().tobytes()).hexdigest()]))
'''
    output = subprocess.run([sys.executable,'-c',code,str(path)],capture_output=True,text=True,check=True)
    assert json.loads(output.stdout) == [.4,.18,expected]


@pytest.mark.parametrize('scale',[97.27,100])
def test_print_validator_accepts_calibrated_and_historical_profile(tmp_path,valid,monkeypatch,scale):
    project=PlanchaProject([item(valid)],margin_cm=.3)
    editor=renderer(project)
    final=tmp_path/'final.png'
    save_image(editor.render_sheet(),final,'PNG',dpi=(300,300))
    editor.database=object()
    editor.plancha_id=1
    editor.project_path=str(valid)
    editor.final_png_path=str(final)
    editor._linked_order_id=lambda: None
    editor._current_print_config=lambda:{'scale':scale,'paper':'A4','orientation':'Vertical','printer_name':'FICTICIA'}
    monkeypatch.setattr('app.printing.windows_print.printer_status',lambda name:(True,'Disponible simulada'))
    assert editor._print_validation_error() is None


def test_later_page_failure_does_not_publish_earlier_pages(tmp_path,valid):
    from app.planchas.output_safety import save_page_outputs
    path=tmp_path/'set.json'
    original=tmp_path/'set_plancha_1.png'
    original.write_bytes(b'PREVIOUS-VALID')
    pages=[PlanchaProject([item(valid)]) for _ in range(2)]
    calls=[]
    def render(project):
        calls.append(project)
        if len(calls)==2:
            raise OSError('Fallo en la segunda página')
        return Image.new('RGBA',(100,100),'red')
    with pytest.raises(OSError):
        save_page_outputs(pages,path,render)
    assert original.read_bytes()==b'PREVIOUS-VALID'
    assert list(tmp_path.glob('set_plancha_*.png'))==[original]
    assert not path.exists()


def test_effective_pixels_apply_one_scale_and_reject_second_fit():
    from app.planchas.production_geometry import calibrated_print_pixels
    dimensions=calibrated_print_pixels(2480,3508,600,600)
    assert dimensions==(round(2480*2*.9727),round(3508*2*.9727))
    assert dimensions!= (round(2480*2*.9727**2),round(3508*2*.9727**2))
    with pytest.raises(ValueError,match='segunda reducción'):
        calibrated_print_pixels(2480,3508,600,600,printable_width=4000,printable_height=6000)
