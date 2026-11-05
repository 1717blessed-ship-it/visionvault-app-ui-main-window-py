"""Editor real con borrador ficticio, sin base de datos ni impresora."""
from pathlib import Path
import sys
import tkinter as tk

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from PIL import Image,ImageDraw
from app.planchas.editor import PlanchaEditor
from app.ui.theme import configure_plancha_styles
from tools.benchmark_creator_sprint2 import source,normal


def main():
    folder=ROOT/'artifacts'/'creator-s2-visual-20261024';folder.mkdir(exist_ok=True)
    files=[]
    for index,color in enumerate(('red','green','blue')):
        path=folder/f'FICTICIO-{index}.png'
        image=Image.new('RGBA',(200,200),color);ImageDraw.Draw(image).text((20,80),f'FICTICIO {index}',fill='white')
        image.save(path);files.append(path)
    pages=normal(source(100,True))
    for page in pages:
        for item in page.items:item.path=str(files[int(item.name[-1])])
    root=tk.Tk();root.title('DOCCIONE — SPRINT 2 — BORRADOR FICTICIO SIN BASE')
    root.geometry('1280x720+10+10');configure_plancha_styles(root)
    editor=PlanchaEditor(root,[],project=pages[0],preserve_layout=True,auto_paginate=False,host=root)
    editor.pack(fill='both',expand=True)
    # Sólo este harness habilita comparación: no es una plancha histórica ni reservada.
    editor.preserve_layout=False;editor.all_projects=pages;editor.max_planchas=len(pages)
    editor.update_plancha_navigation()
    root.after(1500,editor.compare_optional_distribution)
    root.mainloop()


if __name__=='__main__':main()
