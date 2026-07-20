import numpy as np
from PIL import Image, ImageDraw
from app.stickers.pipeline import StickerProcessor
import cv2

img = Image.new('RGBA', (220, 220), color=(18, 18, 18, 255))
d = ImageDraw.Draw(img)
d.rectangle([20, 20, 200, 200], fill=(255, 255, 255))
d.ellipse([55, 55, 165, 165], fill=(80, 120, 220))
mask = StickerProcessor._uniform_background_alpha(img, tolerance=42)
arr = np.asarray(mask.convert('L'), dtype=np.uint8)
subject = arr > 127
print('subject sum', int(subject.sum()))
rgb = np.asarray(img.convert('RGB'), dtype=np.uint8)
is_white = (rgb[:, :, 0] >= 240) & (rgb[:, :, 1] >= 240) & (rgb[:, :, 2] >= 240)
print('white sum', int(is_white.sum()))
for width in range(3, 19, 2):
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (width, width))
    eroded = cv2.erode(subject.astype(np.uint8), kernel, iterations=1).astype(bool)
    shell = subject.astype(bool) & ~eroded
    core = eroded
    white_shell = is_white & shell
    white_core = is_white & core
    shell_ratio = white_shell.sum() / max(1, shell.sum())
    core_ratio = white_core.sum() / max(1, core.sum())
    contrast = shell_ratio - core_ratio
    print(width, 'shell', int(shell.sum()), 'white_shell', int(white_shell.sum()), 'shell_ratio', round(float(shell_ratio), 3), 'core_ratio', round(float(core_ratio), 3), 'contrast', round(float(contrast), 3))
print('analysis', StickerProcessor._analyze_white_border_structural(img, mask))

img2 = Image.new('RGBA', (220, 220), color=(18, 18, 18, 255))
d2 = ImageDraw.Draw(img2)
d2.rectangle([60, 60, 160, 160], fill=(255, 255, 255))
d2.ellipse([80, 80, 140, 140], fill=(100, 100, 200))
d2.rectangle([90, 90, 110, 110], fill=(255, 255, 255))
mask2 = StickerProcessor._uniform_background_alpha(img2, tolerance=42)
arr2 = np.asarray(mask2.convert('L'), dtype=np.uint8)
subject2 = arr2 > 127
print('subject2 sum', int(subject2.sum()))
rgb2 = np.asarray(img2.convert('RGB'), dtype=np.uint8)
is_white2 = (rgb2[:, :, 0] >= 240) & (rgb2[:, :, 1] >= 240) & (rgb2[:, :, 2] >= 240)
print('white2 sum', int(is_white2.sum()))
for width in range(3, 19, 2):
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (width, width))
    eroded2 = cv2.erode(subject2.astype(np.uint8), kernel, iterations=1).astype(bool)
    shell2 = subject2.astype(bool) & ~eroded2
    core2 = eroded2
    white_shell2 = is_white2 & shell2
    white_core2 = is_white2 & core2
    shell_ratio2 = white_shell2.sum() / max(1, shell2.sum())
    core_ratio2 = white_core2.sum() / max(1, core2.sum())
    contrast2 = shell_ratio2 - core_ratio2
    print('neg', width, 'shell', int(shell2.sum()), 'white_shell', int(white_shell2.sum()), 'shell_ratio', round(float(shell_ratio2), 3), 'core_ratio', round(float(core_ratio2), 3), 'contrast', round(float(contrast2), 3))
print('analysis2', StickerProcessor._analyze_white_border_structural(img2, mask2))
