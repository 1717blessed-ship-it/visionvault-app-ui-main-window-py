"""Offline human-reference packet. Never creates or approves ground truth.

prepare: copy original and distinctly labelled automatic proposals for review.
compare: only accepts an explicitly approved, hash-bound, source-sized reference.
"""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil

import cv2
import numpy as np
from PIL import Image

from scripts.validate_sticker_visuals import composite, tile


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def alpha(path):
    with Image.open(path) as image:
        if image.mode not in ('L','RGBA'):
            raise ValueError('La referencia debe ser una máscara L o una imagen RGBA con alfa real.')
        return image.getchannel('A').copy() if image.mode=='RGBA' else image.copy()


def regions(difference):
    count, labels, stats, _ = cv2.connectedComponentsWithStats(difference.astype('uint8'),8)
    result=[]
    for index in range(1,count):
        x,y,w,h,area=(int(v) for v in stats[index])
        result.append(dict(id=index,bbox=[x,y,x+w,y+h],pixels=area))
    return sorted(result,key=lambda item:item['pixels'],reverse=True)


def prepare(source, metadata, output):
    source, metadata, output=Path(source).resolve(),Path(metadata).resolve(),Path(output).resolve()
    data=json.loads(metadata.read_text(encoding='utf-8'))
    if data['artifacts'].get('source_hash') != digest(source):
        raise ValueError('La metadata no acredita el hash de esta fuente.')
    mask=alpha(data['artifacts']['mask_editable'])
    with Image.open(source) as image:
        original=image.convert('RGBA')
    if mask.size!=original.size:
        raise ValueError('La máscara automática no está en coordenadas de la fuente.')
    output.mkdir(parents=True,exist_ok=False)
    shutil.copy2(source,output/'original.png')
    mask.save(output/'automatic_proposal_NOT_REFERENCE.png')
    draft=dict(approved=False,reviewer='',reviewed_at='',coordinate_space='source',
               source_sha256=digest(source),mask_path='mask_reviewed.png',mask_sha256='',
               original_dimensions=list(original.size),notes='Requiere revisión y aprobación humana; no es referencia validada.')
    (output/'approval_PENDING.json').write_text(json.dumps(draft,ensure_ascii=False,indent=2),encoding='utf-8')
    shown=original.copy()
    shown.putalpha(mask)
    panels=[('ORIGINAL - embedded checker',original.convert('RGB')),
            ('AUTOMATIC PROPOSAL - not truth',composite(shown,'black')),
            ('automatic visual alpha',mask.convert('RGB'))]
    candidate_path=data['artifacts'].get('checkerboard_segmentation_candidate')
    packet=dict(status='PENDING_HUMAN_REVIEW',source_sha256=digest(source),
                source=str(source),metadata=str(metadata),dimensions=list(original.size),
                reference_created=False,reference_approved=False)
    if candidate_path:
        candidate=alpha(candidate_path)
        if candidate.size!=mask.size:
            raise ValueError('Candidato desalineado; no se compara ni reescala.')
        candidate.save(output/'rejected_candidate_NOT_REFERENCE.png')
        disagreement=np.abs(np.asarray(mask,dtype='int16')-np.asarray(candidate,dtype='int16'))>8
        overlay=np.asarray(original.convert('RGB')).copy()
        overlay[disagreement]=(255,0,255)
        overlay=Image.fromarray(overlay)
        overlay.save(output/'algorithm_disagreement_NOT_ERROR_MAP.png')
        packet['algorithm_disagreement_regions']=regions(disagreement)
        panels.append(('MAGENTA = disagreement, not error',overlay))
        for index,region in enumerate(packet['algorithm_disagreement_regions'][:8],1):
            x0,y0,x1,y1=region['bbox']
            box=(max(0,x0-8),max(0,y0-8),min(original.width,x1+8),min(original.height,y1+8))
            crop=overlay.crop(box)
            crop.resize((crop.width*2,crop.height*2),Image.Resampling.NEAREST).save(output/f'region_{index:02d}_200pct.png')
    sheet=Image.new('RGB',(520,580),'white')
    for index,(label,image) in enumerate(panels):
        sheet.paste(tile(image,label),((index%2)*260,(index//2)*290))
    sheet.save(output/'review_comparison.png')
    (output/'packet.json').write_text(json.dumps(packet,ensure_ascii=False,indent=2),encoding='utf-8')
    return packet


def validate_reference(source, approval):
    approval=Path(approval).resolve()
    data=json.loads(approval.read_text(encoding='utf-8'))
    if data.get('approved') is not True or not data.get('reviewer','').strip():
        raise ValueError('Falta aprobación humana explícita e identidad del revisor.')
    try:
        stamp=datetime.fromisoformat(data.get('reviewed_at',''))
        if stamp.tzinfo is None:
            raise ValueError()
    except ValueError:
        raise ValueError('Se requiere fecha ISO de revisión con zona horaria.') from None
    if data.get('coordinate_space')!='source' or data.get('source_sha256','').lower()!=digest(source):
        raise ValueError('La aprobación no corresponde a esta fuente/coordenadas.')
    path=(approval.parent/data['mask_path']).resolve()
    if not data.get('mask_sha256') or data['mask_sha256'].lower()!=digest(path):
        raise ValueError('La máscara no coincide con el hash aprobado.')
    reference=alpha(path)
    if reference.getextrema()[1]==0:
        raise ValueError('La referencia está vacía.')
    with Image.open(source) as image:
        if reference.size!=image.size or list(image.size)!=data.get('original_dimensions'):
            raise ValueError('Dimensiones distintas: prohibido reescalar una referencia.')
    return reference,data


def compare(source, automatic, approval, output):
    reference,review=validate_reference(source,approval)
    automatic=alpha(automatic)
    if automatic.size!=reference.size:
        raise ValueError('La máscara automática no coincide con la referencia; no se reescala.')
    output=Path(output).resolve()
    output.mkdir(parents=True,exist_ok=False)
    ref=np.asarray(reference,dtype='int16')
    got=np.asarray(automatic,dtype='int16')
    r,g=ref>12,got>12
    difference=np.abs(ref-got)>8
    missing=r&~g
    excess=g&~r
    def boundary(binary):
        return binary & ~(cv2.erode(binary.astype('uint8'),np.ones((3,3),dtype='uint8'),borderType=cv2.BORDER_CONSTANT,borderValue=0)>0)
    rb,gb=boundary(r),boundary(g)
    distances=[]
    precision=recall=None
    if rb.any() and gb.any():
        to_ref=cv2.distanceTransform((~rb).astype('uint8'),cv2.DIST_L2,5)[gb]
        to_got=cv2.distanceTransform((~gb).astype('uint8'),cv2.DIST_L2,5)[rb]
        precision=float((to_ref<=1).mean())
        recall=float((to_got<=1).mean())
        distances=np.concatenate((to_ref,to_got))
    measures=dict(reference_reviewer=review['reviewer'],source_sha256=digest(source),
                  foreground_iou=float((r&g).sum()/max(1,(r|g).sum())),
                  alpha_mae=float(np.abs(ref-got).mean()),missing_pixels=int(missing.sum()),
                  excess_pixels=int(excess.sum()),partial_alpha_difference_pixels=int((difference&~missing&~excess).sum()),
                  boundary_precision_1px=precision,boundary_recall_1px=recall,
                  boundary_distance_p95_px=float(np.percentile(distances,95)) if len(distances) else None,
                  boundary_hausdorff_px=float(np.max(distances)) if len(distances) else None,
                  difference_regions=regions(difference),production_approval=False)
    # Red=missing, green=excess, yellow=alpha difference; not an artistic edit.
    with Image.open(source) as source_image:
        overlay=np.asarray(source_image.convert('RGB')).copy()
    overlay[difference]=(255,220,0)
    overlay[missing]=(255,0,0)
    overlay[excess]=(0,220,0)
    overlay=Image.fromarray(overlay)
    overlay.save(output/'differences.png')
    Image.fromarray((difference*255).astype('uint8')).save(output/'difference_mask.png')
    for index,region in enumerate(measures['difference_regions'],1):
        x0,y0,x1,y1=region['bbox']
        box=(max(0,x0-6),max(0,y0-6),min(reference.width,x1+6),min(reference.height,y1+6))
        crop=overlay.crop(box)
        crop.resize((crop.width*2,crop.height*2),Image.Resampling.NEAREST).save(output/f'region_{index:03d}_200pct.png')
    (output/'metrics.json').write_text(json.dumps(measures,ensure_ascii=False,indent=2),encoding='utf-8')
    return measures


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    prepare_parser=sub.add_parser('prepare')
    compare_parser=sub.add_parser('compare')
    for command in (prepare_parser,compare_parser):
        command.add_argument('--source',required=True,type=Path)
        command.add_argument('--output',required=True,type=Path)
    prepare_parser.add_argument('--metadata',required=True,type=Path)
    compare_parser.add_argument('--automatic',required=True,type=Path)
    compare_parser.add_argument('--approval',required=True,type=Path)
    args=vars(parser.parse_args())
    function=prepare if args.pop('command')=='prepare' else compare
    print(json.dumps(function(**args),ensure_ascii=False,indent=2))
