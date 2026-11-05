"""Comparación opt-in: packing de huecos, sin escala ni escrituras productivas."""
from collections import Counter
import copy
from dataclasses import dataclass
import math

from app.planchas.model import PlanchaItem, PlanchaProject, Rect, update_free_rectangles


def clone(project):
    return PlanchaProject.from_dict(project.to_dict())


def indicators(pages):
    useful=sum(page.usable_width*page.usable_height for page in pages)
    items=[item for page in pages for item in page.items]
    physical=sum(item.width_cm*item.height_cm for item in items)
    reserved=sum(item.reserved_width_cm*item.reserved_height_cm for item in items)
    return dict(pages=len(pages),placed=len(items),pending=0,impossible=0,
                occupancy=100*physical/useful if useful else 0,
                available_cm2=max(0,useful-reserved),
                page_units=[len(page.items) for page in pages])


@dataclass
class DistributionComparison:
    normal: list
    optimized: list
    improved: bool
    reason: str

    @property
    def selected(self):
        return self.optimized if self.improved else self.normal


def valid_layout(pages, source, *, existing_contract=False):
    flattened=[item for page in pages for item in page.items]
    if Counter(item.item_id for item in flattened)!=Counter(item.item_id for item in source):
        return False
    originals={item.item_id:item for item in source}
    for page in pages:
        gap=0 if existing_contract and page.project_type=='sticker_mixed' else page.gap_cm
        for index,item in enumerate(page.items):
            old=originals[item.item_id]
            if item.to_dict() != {**old.to_dict(), 'x_cm':item.x_cm, 'y_cm':item.y_cm}:
                return False  # This first alternative intentionally never rotates or resizes.
            if not all(math.isfinite(float(v)) for v in (item.x_cm,item.y_cm,item.width_cm,item.height_cm)):
                return False
            if (item.x_cm<page.margin_cm-1e-7 or item.y_cm<page.margin_cm-1e-7
                    or item.x_cm+item.reserved_width_cm>21-page.margin_cm+1e-7
                    or item.y_cm+item.reserved_height_cm>page.workspace_bottom_cm+1e-7):
                return False
            for other in page.items[index+1:]:
                if not (item.x_cm+item.reserved_width_cm+gap<=other.x_cm+1e-7
                        or other.x_cm+other.reserved_width_cm+gap<=item.x_cm+1e-7
                        or item.y_cm+item.reserved_height_cm+gap<=other.y_cm+1e-7
                        or other.y_cm+other.reserved_height_cm+gap<=item.y_cm+1e-7):
                    return False
    return True


def gap_pack(source, template, strategy):
    """Reutiliza la partición de huecos del Creador, sin maximizar tamaños."""
    remaining=[PlanchaItem.from_dict(item.to_dict()) for item in source]
    if strategy=='area':
        remaining.sort(key=lambda i:(-i.reserved_width_cm*i.reserved_height_cm,-i.reserved_height_cm,i.item_id))
    else:
        remaining.sort(key=lambda i:(-i.reserved_height_cm,-i.reserved_width_cm,i.item_id))
    pages=[]
    while remaining:
        page=clone(template); page.items=[]
        gap=page.gap_cm
        # Right/bottom halos separate neighbours without reducing the usable edge.
        free=[Rect(page.margin_cm,page.margin_cm,page.usable_width+gap,page.usable_height+gap)]
        overflow=[]
        for item in remaining:
            width,height=item.reserved_width_cm+gap,item.reserved_height_cm+gap
            candidates=[rect for rect in free if width<=rect.width+1e-9 and height<=rect.height+1e-9]
            if not candidates:
                overflow.append(item); continue
            rect=min(candidates,key=lambda r:(r.area-width*height,min(r.width-width,r.height-height),r.y,r.x))
            item.x_cm,item.y_cm=round(rect.x,8),round(rect.y,8)
            page.items.append(item)
            free=update_free_rectangles(free,Rect(rect.x,rect.y,width,height))
        if not page.items:
            raise ValueError('El candidato no puede colocar todas las piezas; se conserva el modo normal.')
        page._persisted_options={**getattr(page,'_persisted_options',{}),'distribution_mode':'optimized_gaps_v1'}
        pages.append(page); remaining=overflow
    return pages


def compare_distribution(project, *, pages=None, contexts=None):
    inputs=list(pages or [project])
    if any(p.project_type=='sticker_free' or p.manual_from_mixed for p in inputs):
        raise ValueError('El modo Libre manual no se redistribuye.')
    if any(item.locked for page in inputs for item in page.items):
        raise ValueError('Hay posiciones bloqueadas; no se modifica su composición.')
    signatures={(p.workspace_format,p.margin_cm,p.gap_cm,p.layout_mode,p.project_type) for p in inputs}
    if len(signatures)!=1:
        raise ValueError('Compará por separado formatos, modos, márgenes o separaciones incompatibles.')
    items=[PlanchaItem.from_dict(item.to_dict()) for p in inputs for item in p.items]
    if not items:
        raise ValueError('No hay unidades para comparar.')
    if any(item.production_unit_kind!='item' for item in items):
        raise ValueError('Las hojas comerciales no se compactan como stickers.')
    if (not math.isfinite(project.margin_cm) or not math.isfinite(project.gap_cm)
            or project.margin_cm<0 or project.gap_cm<0
            or any(not math.isfinite(v) or v<=0 for i in items for v in
                   (i.width_cm,i.height_cm,i.reserved_width_cm,i.reserved_height_cm))):
        raise ValueError('Dimensiones, margen o separación inválidos.')
    if len({item.item_id for item in items})!=len(items):
        raise ValueError('Hay identidades duplicadas; revisá las cantidades antes de distribuir.')
    if contexts is None and any(item.order_job_id is not None for item in items):
        raise ValueError('Falta verificar material/formato/unidad de los trabajos vinculados.')
    if contexts is not None:
        if any(item.item_id not in contexts for item in items) or len({tuple(contexts[item.item_id]) for item in items})!=1:
            raise ValueError('Los trabajos no tienen material, formato y unidad compatibles.')
        if any(not str(part).strip() for value in contexts.values() for part in value):
            raise ValueError('Hay datos de compatibilidad incompletos.')
        if any(len(value)!=3 or value[2]!='item' for value in contexts.values()):
            raise ValueError('La unidad comercial no permite compactar estas hojas como stickers.')
    if pages and valid_layout(inputs,items,existing_contract=True):
        normal=[clone(page) for page in inputs]
    else:
        normal=PlanchaProject.calculate_pagination(items,margin_cm=project.margin_cm,gap_cm=project.gap_cm,
            layout_mode=project.layout_mode,workspace_format=project.workspace_format,project_type=project.project_type)
        for page in normal:
            page._persisted_options=copy.deepcopy(getattr(project,'_persisted_options',{}))
            page._persisted_options.pop('distribution_mode',None)
    # Normalize only through the established distributor; candidates keep those exact dimensions.
    source=[item for page in normal for item in page.items]
    originals={item.item_id:item for page in inputs for item in page.items}
    for item in source:
        old=originals[item.item_id]
        if (item.width_cm,item.height_cm,item.reserved_width_cm,item.reserved_height_cm,item.rotation)!=(
                old.width_cm,old.height_cm,old.reserved_width_cm,old.reserved_height_cm,old.rotation):
            raise ValueError('Prepará primero la distribución normal: la comparación no puede cambiar tamaños ni rotaciones físicas.')
    template=clone(project)
    candidate=normal
    for strategy in ('area','height'):
        try:
            trial=gap_pack(source,template,strategy)
        except ValueError:
            continue
        if valid_layout(trial,source) and len(trial)<len(candidate):
            candidate=trial
    improved=len(candidate)<len(normal)
    return DistributionComparison(normal,candidate,improved,
        'Menos hojas con todas las unidades y geometría verificada.' if improved else
        'No reduce hojas; se conserva la distribución normal sin cambios.')
