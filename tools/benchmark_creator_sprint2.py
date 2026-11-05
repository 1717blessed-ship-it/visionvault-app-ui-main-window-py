"""Benchmark reproducible sin base operativa ni imágenes físicas."""
import argparse
import hashlib
import json
from pathlib import Path
from statistics import median
import sys
from time import perf_counter
import tracemalloc

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.planchas.model import PlanchaItem, PlanchaProject


def source(count, mixed):
    return PlanchaProject([PlanchaItem(path=f'FICTICIO-{i%3}.png',name=f'Diseño {i%3}',
        width_cm=([4.8,3.2,2.4][i%3] if mixed else 4.8),
        height_cm=([4.8,3,2][i%3] if mixed else 4.8),
        item_id=f'unit-{i}',group_id=f'design-{i%3}',copy_number=i//3+1)
        for i in range(count)],margin_cm=.15,gap_cm=.05)


def normal(project):
    return PlanchaProject.calculate_pagination(project.items,margin_cm=project.margin_cm,
        gap_cm=project.gap_cm,layout_mode=project.layout_mode,workspace_format=project.workspace_format,
        project_type=project.project_type)


def measure(fn):
    times=[]
    for _ in range(3):
        start=perf_counter(); pages=fn(); times.append((perf_counter()-start)*1000)
    tracemalloc.start(); fn(); _,peak=tracemalloc.get_traced_memory(); tracemalloc.stop()
    useful=sum(p.usable_width*p.usable_height for p in pages)
    area=sum(i.width_cm*i.height_cm for p in pages for i in p.items)
    geometry=[[i.to_dict() for i in p.items] for p in pages]
    return dict(pages=len(pages),counts=[len(p.items) for p in pages],
        placed=sum(len(p.items) for p in pages),pending=0,occupancy=round(100*area/useful,3),
        available_cm2=round(useful-area,3),median_ms=round(median(times),3),peak_bytes=peak,
        geometry_sha256=hashlib.sha256(json.dumps(geometry,sort_keys=True).encode()).hexdigest())


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--compare',action='store_true'); args=parser.parse_args()
    rows=[]
    for mixed in (False,True):
        for count in (10,25,50,100,200):
            row=dict(mixed=mixed,count=count,normal=measure(lambda:normal(source(count,mixed))))
            if args.compare:
                from app.planchas.optional_distribution import compare_distribution
                row['optimized']=measure(lambda:compare_distribution(source(count,mixed)).selected)
            rows.append(row)
    output=ROOT/'artifacts'/('creator-s2-comparison.json' if args.compare else 'creator-s2-baseline-benchmark.json')
    output.write_text(json.dumps(rows,indent=2),encoding='utf-8')
    print(json.dumps(rows,indent=2))


if __name__=='__main__': main()
