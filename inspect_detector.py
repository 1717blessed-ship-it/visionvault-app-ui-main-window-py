from PIL import Image, ImageDraw
from app.stickers.pipeline import StickerProcessor
import numpy as np
from pathlib import Path

img=Image.new('RGBA',(220,220),(18,18,18,255))
draw=ImageDraw.Draw(img)
draw.rectangle([20,20,200,200],fill=(255,255,255))
draw.ellipse([55,55,165,165],fill=(80,120,220))
mask=StickerProcessor._uniform_background_alpha(img,tolerance=42)
arr=np.asarray(mask)
subject=arr>127
rgb=np.asarray(img.convert('RGB'))
is_white=(rgb[:,:,0]>=240)&(rgb[:,:,1]>=240)&(rgb[:,:,2]>=240)
# Save summary
lines=[]
lines.append(f'shape={arr.shape}')
lines.append(f'unique={np.unique(arr).tolist()}')
lines.append(f'subject_pixels={subject.sum()}')
lines.append(f'white_pixels={is_white.sum()}')
lines.append(f'white_in_subject={((is_white & subject).sum())}')
# Save small patch of the mask around the center
lines.append('mask_patch')
for row in arr[90:110,90:110]:
    lines.append(' '.join(['#' if v else '.' for v in row]))
lines.append('rgb_patch')
for row in rgb[90:110,90:110]:
    lines.append(' '.join([f'{p[0]:3d},{p[1]:3d},{p[2]:3d}' for p in row]))
Path('inspect_detector_output.txt').write_text('\n'.join(lines), encoding='utf-8')
print('wrote inspect_detector_output.txt')
