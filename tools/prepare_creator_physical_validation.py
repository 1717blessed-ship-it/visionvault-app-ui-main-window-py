"""Kit diagnóstico: sólo archivos ficticios y base aislada, nunca spool ni estados reales."""
import base64
from collections import OrderedDict
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from PIL import Image,ImageDraw,ImageFont
from app.database.database import ImageDatabase
from app.planchas.editor import PlanchaEditor,preview_geometry
from app.planchas.model import PlanchaProject,PlanchaItem
from app.planchas.optional_distribution import compare_distribution,indicators,valid_layout
from app.planchas.production_geometry import PRINT_SCALE,CUT_INSET_MM,production_min_for_nominal,expected_final_size
from app.planchas.output_safety import save_image
from app.printing.windows_print import validate_a4_png
from tools.benchmark_creator_sprint2 import source,normal


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def readonly(path):return sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)
def px(mm):return round(mm/25.4*300)


def render(project):
    editor=object.__new__(PlanchaEditor);editor.project=project;editor.current_project_index=0
    editor.production_sticker_cache=OrderedDict();editor.production_sticker_cache_pixels=0
    geometry=[preview_geometry(item) for item in project.items]
    sheet=editor.render_sheet()
    assert [preview_geometry(item) for item in project.items]==geometry
    return sheet


def main():
    folder=ROOT/'artifacts'/'creator-physical-validation-20261024'
    folder.mkdir(exist_ok=False)
    protected=[ROOT/'visionvault.db',ROOT/'artifacts/acceptance-s3-20261023/physical-pending.db']
    before={str(path):digest(path) for path in protected}
    with readonly(protected[0]) as conn:
        row=conn.execute('SELECT setting_value FROM app_settings WHERE setting_key=?',('printing_config',)).fetchone()
        if not row:raise ValueError('No hay configuración vigente: no se inventa un perfil.')
        config=json.loads(row[0])
    profile=config.get('printer_profiles',{}).get(config.get('printer_name'),{})
    active={**config,**profile}
    if abs(float(active.get('scale',0))-PRINT_SCALE*100)>1e-6:
        raise ValueError('La configuración real requiere revisión, no se reemplaza su escala.')
    encoded=active.get('devmode_b64') or active.get('devmode')
    driver=base64.b64decode(encoded) if encoded else b''
    (folder/'driver-profile.bin').write_bytes(driver)
    snapshot={key:active.get(key) for key in ('printer_name','paper','orientation','scale','quality','color','copies','devmode_summary')}
    snapshot.update(devmode_bytes=len(driver),devmode_sha256=hashlib.sha256(driver).hexdigest(),
        effective_scale=PRINT_SCALE,strict_calibration=True,physical_validated=False,
        driver_internal_options_verified=False,material_profile_confirmation_required=True)
    (folder/'configuration.json').write_text(json.dumps(snapshot,ensure_ascii=False,indent=2),encoding='utf-8')
    # Deliberately isolated profile copy, never save into the operative database.
    db=ImageDatabase(folder/'homologation-isolated.db')
    db.save_printing_config(active['printer_name'],active)
    images=[]
    for n,color in enumerate(('#cc3545','#2474bb','#2c9840')):
        path=folder/f'FICTICIO-{n}.png'
        art=Image.new('RGBA',(500,500),(0,0,0,0));draw=ImageDraw.Draw(art)
        if n==0:draw.ellipse((15,15,484,484),fill=color)
        else:draw.rounded_rectangle((15,15,484,484),radius=35,fill=color)
        art.save(path);images.append(path)
    items=[];expectations=[]
    x=2.0
    for n,nominal in enumerate((3,5,8)):
        size=production_min_for_nominal(nominal)
        if n==2:x=2.0
        y=8.0 if n<2 else 17.5
        item=PlanchaItem(path=str(images[n]),name=f'FICTICIO nominal {nominal} cm',width_cm=size,height_cm=size,
                        x_cm=x,y_cm=y,nominal_size_cm=nominal)
        items.append(item)
        expectations.append(dict(id=f'C-{n+1}',name=item.name,document_width_mm=size*10,
            expected_printed_width_mm=size*10*PRINT_SCALE,expected_cut_width_mm=expected_final_size(size)*10,
            x_document_mm=x*10,y_document_mm=y*10,measured_x_mm=None,measured_y_mm=None,
            measured_printed_width_mm=None,measured_printed_height_mm=None,measured_cut_width_mm=None,
            measured_cut_height_mm=None,damaged_units=None,photo=None))
        x+=size+.5
    calibration=PlanchaProject(items,margin_cm=.3,gap_cm=.5)
    calibration._restored_geometry=True
    calibration._persisted_options={'print_settings':active,'cut_settings':{'inset_mm':CUT_INSET_MM},
        'diagnostic_overlay':'El PNG final tiene referencias añadidas de diagnóstico. No regenerar desde JSON para imprimir las reglas.'}
    transparent=render(calibration)
    sheet=Image.new('RGBA',transparent.size,'white');sheet.alpha_composite(transparent)
    draw=ImageDraw.Draw(sheet)
    try:font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',24)
    except OSError:font=ImageFont.load_default()
    def text(x,y,value):draw.text((px(x),px(y)),value,fill='black',font=font)
    def line(x,y,length,vertical=False):
        end=(px(x),px(y+length)) if vertical else (px(x+length),px(y))
        draw.line([(px(x),px(y)),end],fill='black',width=3)
        for step in (0,length):
            if vertical:draw.line([(px(x-1.5),px(y+step)),(px(x+1.5),px(y+step))],fill='black',width=3)
            else:draw.line([(px(x+step),px(y-1.5)),(px(x+step),px(y+1.5))],fill='black',width=3)
    text(16,13,'DOCCIONE - DIAGNOSTICO - NO ES PEDIDO')
    line(20,30,50);text(20,33,'50 mm documento -> 48,635 mm impresos esperados')
    compensated=50/PRINT_SCALE
    line(20,47,compensated);text(20,50,'Referencia compensada: 50 mm impresos esperados')
    line(180,80,compensated,True);text(130,137,'Vertical: 50 mm esperados')
    text(120,88,'C1/C2: 5 mm entre cajas')
    text(120,94,'Impreso esperado: 4,8635 mm')
    text(120,105,'NO CORTAR reglas/textos/cruces')
    text(120,112,'Cortar solo 3 contornos de color')
    text(16,276,'C3: nominal final 80 mm. Medir antes y despues del corte.')
    anchors=[]
    for label,x,y in [('TL',10,10),('TR',200,10),('BL',10,287),('BR',200,287)]:
        draw.line([(px(x-2),px(y)),(px(x+2),px(y))],fill='black',width=3)
        draw.line([(px(x),px(y-2)),(px(x),px(y+2))],fill='black',width=3)
        anchors.append(dict(id=label,x_document_mm=x,y_document_mm=y,measured_x_mm=None,measured_y_mm=None))
    draw.rectangle((px(10),px(10),px(200),px(287)),outline='#777777',width=1)
    output=folder/'01-calibration-a4.png';save_image(sheet,output,'PNG',dpi=(300,300))
    calibration.save(folder/'01-calibration-stickers.json')
    registered=[]
    def register(project,path,json_path,name):
        pid=db.save_plancha_project(None,name,'MATERIAL DE PRUEBA A CONFIRMAR',json.dumps(project.to_dict(),ensure_ascii=False),str(json_path))
        db.set_plancha_final_png(pid,str(path))
        registered.append(dict(plancha_id=pid,file=path.name,project=json_path.name))
    register(calibration,output,folder/'01-calibration-stickers.json','HOMOLOGACION - referencias diagnosticas: usar PNG preparado')
    model=source(100,True)
    for item in model.items:item.path=str(images[int(item.name[-1])])
    result=compare_distribution(model)
    assert result.improved
    original=[item for page in result.normal for item in page.items]
    assert valid_layout(result.selected,original)
    expected={item.item_id:(item.width_cm,item.height_cm,item.path,item.copy_number) for item in original}
    checks=[]
    for mode,pages in [('A-normal',result.normal),('B-optimized',result.selected)]:
        assert {i.item_id:(i.width_cm,i.height_cm,i.path,i.copy_number) for p in pages for i in p.items}==expected
        for page in pages:
            page._persisted_options={**getattr(page,'_persisted_options',{}),'print_settings':active,
                                     'cut_settings':{'inset_mm':CUT_INSET_MM}}
        PlanchaProject.save_pages(folder/f'{mode}-all-pages.json',pages)
        for n,page in enumerate(pages,1):
            page._persisted_options={**getattr(page,'_persisted_options',{}),'print_settings':active,
                                     'cut_settings':{'inset_mm':CUT_INSET_MM}}
            path=folder/f'{mode}-{n:02d}.png';json_path=path.with_suffix('.json')
            page.save(json_path);before_geometry=[preview_geometry(i) for i in page.items]
            image=render(page);save_image(image,path,'PNG',dpi=(300,300))
            assert before_geometry==[preview_geometry(i) for i in page.items]
            assert validate_a4_png(path)[0]
            checks.append(dict(file=path.name,items=len(page.items),sha256=digest(path),size_px=image.size))
            register(page,path,json_path,f'HOMOLOGACION {mode} {n}/{len(pages)} - FICTICIO')
    # Existing regular last-row regression, also checked as an explicit diagnostic.
    regular=normal(source(10,False))[0]
    last_y=max(i.y_cm for i in regular.items)
    last=sorted([i for i in regular.items if i.y_cm==last_y],key=lambda i:i.x_cm)
    assert last[0].x_cm==regular.margin_cm
    assert all(abs(b.x_cm-a.x_cm-a.reserved_width_cm-regular.gap_cm)<.001 for a,b in zip(last,last[1:]))
    with readonly(protected[1]) as conn:
        physical=conn.execute('SELECT state,COUNT(*),SUM(quantity) FROM plancha_item_assignments GROUP BY state').fetchall()
        print_jobs=conn.execute('SELECT COUNT(*) FROM print_jobs').fetchone()[0]
    assert physical==[('prepared',3,3.0)] and print_jobs==0
    assert db.connection.execute('SELECT COUNT(*) FROM print_jobs').fetchone()[0]==0
    assert db.connection.execute('SELECT COUNT(*) FROM plancha_item_assignments').fetchone()[0]==0
    db.close()
    assert all(digest(Path(path))==value for path,value in before.items())
    rulers=[dict(id='R-document',document_length_mm=50,expected_printed_mm=50*PRINT_SCALE),
            dict(id='R-compensated-X',document_length_mm=compensated,expected_printed_mm=50),
            dict(id='R-compensated-Y',document_length_mm=compensated,expected_printed_mm=50)]
    for ruler in rulers:
        ruler['source_length_px']=px(ruler['document_length_mm'])
        ruler['expected_from_raster_mm']=ruler['source_length_px']*25.4/300*PRINT_SCALE
        ruler['measured_mm']=None;ruler['error_mm']=None
    report=dict(date='2026-10-24',branch='codex/creador-planchas-s2-optimizacion',
        homologation='PENDIENTE DE OPERADOR',print_scale=PRINT_SCALE,cut_inset_mm=CUT_INSET_MM,
        configuration=snapshot,normal=indicators(result.normal),optimized=indicators(result.selected),
        same_units_and_sizes=True,last_regular_row_left_aligned=True,preview_export_geometry_equal=True,
        rulers=rulers,calibration_stickers=expectations,anchors=anchors,
        anchor_distance_x_printed_mm=190*PRINT_SCALE,anchor_distance_y_printed_mm=277*PRINT_SCALE,
        physical_test_batch=physical,physical_test_print_jobs=print_jobs,protected_sha256=before,
        calibration_file=dict(file=output.name,sha256=digest(output),size_px=sheet.size),
        outputs=checks,isolated_planchas=registered,measurements_received=False)
    (folder/'validation-manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    (folder/'operator-results.json').write_text(json.dumps(dict(operator=None,date=None,printer=None,
        substrate=None,driver_profile_confirmed=None,copies_printed=None,pages_printed=[],pages_cut=[],
        ruler_measurements=rulers,sticker_measurements=expectations,anchor_measurements=anchors,
        damaged_stickers=None,missing_stickers=None,photos=[],observations=None,approved_by=None),ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(folder=str(folder),printer=snapshot['printer_name'],copies=snapshot['copies'],
        files=1+len(checks),normal=report['normal']['pages'],optimized=report['optimized']['pages'],
        status=report['homologation'],protected_unchanged=True),ensure_ascii=False,indent=2))


def finalize_existing():
    """Finaliza únicamente el kit diagnóstico propio, sin tocar bases protegidas."""
    folder=ROOT/'artifacts/creator-physical-validation-20261024'
    path=folder/'01-calibration-a4.png'
    with Image.open(path) as source_image:
        white=Image.new('RGBA',source_image.size,'white')
        white.alpha_composite(source_image.convert('RGBA'))
    save_image(white,path,'PNG',dpi=(300,300))
    for mode in ('A-normal','B-optimized'):
        pages=[PlanchaProject.load(p) for p in sorted(folder.glob(f'{mode}-[0-9][0-9].json'))]
        PlanchaProject.save_pages(folder/f'{mode}-all-pages.json',pages)
    manifest_path=folder/'validation-manifest.json'
    report=json.loads(manifest_path.read_text(encoding='utf-8'))
    report['calibration_file']=dict(file=path.name,sha256=digest(path),size_px=white.size)
    report['printer_inventory']={'driver':'EPSON L3210 Series','status':'Normal',
        'queues':['FOTOGRÁFICA 1 EPSON L3210','FOTOGRÁFICA 2 EPSON L3210','SUBLIMACIÓN EPSON L3210'],
        'source':'Get-Printer, consulta de solo lectura 2026-10-24'}
    for output in report['outputs']:
        assert digest(folder/output['file'])==output['sha256']
        assert validate_a4_png(folder/output['file'])[0]
    assert validate_a4_png(path)[0]
    assert all(digest(Path(p))==sha for p,sha in report['protected_sha256'].items())
    manifest_path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Kit finalizado: 8 PNG A4 válidos; bases protegidas sin cambios.')


if __name__=='__main__':main()
