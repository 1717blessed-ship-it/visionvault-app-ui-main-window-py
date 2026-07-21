import numpy as np
from PIL import Image, ImageDraw
from app.stickers.pipeline import StickerProcessor
import cv2


def inspect_case(name, image):
    mask = StickerProcessor._uniform_background_alpha(image, tolerance=42)
    mask_arr = np.asarray(mask.convert('L'), dtype=np.uint8)
    subject = mask_arr > 127
    rgb = np.asarray(image.convert('RGB'), dtype=np.uint8)
    is_white = (rgb[:, :, 0] >= 240) & (rgb[:, :, 1] >= 240) & (rgb[:, :, 2] >= 240)
    lines = []
    lines.append(f'CASE {name}')
    lines.append(f'subject sum {int(subject.sum())}')
    lines.append(f'white pixels {int(is_white.sum())}')
    for width in range(3, 16, 2):
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (width, width))
        dilated = cv2.dilate(subject.astype(np.uint8), kernel, iterations=1).astype(bool)
        ring = dilated & ~subject
        white_ring = is_white & ring
        lines.append(f'{width} ring {int(ring.sum())} white {int(white_ring.sum())} pct {round(float(white_ring.sum()/max(1, ring.sum())), 4)}')
    lines.append(f'analysis {StickerProcessor._analyze_white_border_structural(image, mask)}')
    lines.append('---')
    return '\n'.join(lines)

img_pos = Image.new('RGBA', (220, 220), color=(18, 18, 18, 255))
d = ImageDraw.Draw(img_pos)
d.rectangle([20, 20, 200, 200], fill=(255, 255, 255))
d.ellipse([55, 55, 165, 165], fill=(80, 120, 220))

img_neg = Image.new('RGBA', (220, 220), color=(18, 18, 18, 255))
d2 = ImageDraw.Draw(img_neg)
d2.rectangle([60, 60, 160, 160], fill=(255, 255, 255))
d2.ellipse([80, 80, 140, 140], fill=(100, 100, 200))
d2.rectangle([90, 90, 110, 110], fill=(255, 255, 255))

output = inspect_case('positive', img_pos) + '\n' + inspect_case('internal_white', img_neg)
Path = __import__('pathlib').Path('inspect_border_debug_output.txt')
Path.write_text(output, encoding='utf-8')
print(output)
