from PIL import Image, ImageDraw
from app.stickers.pipeline import StickerProcessor
import numpy as np
img=Image.new('RGBA',(220,220),(18,18,18,255))
draw=ImageDraw.Draw(img)
draw.rectangle([20,20,200,200],fill=(255,255,255))
draw.ellipse([55,55,165,165],fill=(80,120,220))
mask=StickerProcessor._uniform_background_alpha(img,tolerance=42)
arr=np.asarray(mask)
print('shape', arr.shape)
print('unique', np.unique(arr))
print('subject', (arr>127).sum())
print(arr[0:8,0:8])
