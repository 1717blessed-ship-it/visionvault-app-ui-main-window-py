from PIL import Image, ImageDraw
from app.stickers.pipeline import StickerProcessor
import numpy as np
import cv2

img = Image.new('RGBA', (220, 220), color=(18, 18, 18, 255))
d = ImageDraw.Draw(img)
d.rectangle([20, 20, 200, 200], fill=(255, 255, 255))
d.ellipse([55, 55, 165, 165], fill=(80, 120, 220))
mask = StickerProcessor._uniform_background_alpha(img, tolerance=42)
rgb = np.asarray(img.convert('RGB'), dtype=np.uint8)
subject = (np.asarray(mask.convert('L'), dtype=np.uint8) > 127)
is_white = (rgb[:, :, 0] >= 240) & (rgb[:, :, 1] >= 240) & (rgb[:, :, 2] >= 240)
subject_u8 = (subject.astype(np.uint8) * 255)
contours, _ = cv2.findContours(subject_u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
print('contours', len(contours))
print('subject count', int(subject.sum()))
for idx, contour in enumerate(contours):
    print('contour', idx, 'points', len(contour))

contour_mask = np.zeros_like(subject_u8, dtype=np.uint8)
cv2.drawContours(contour_mask, contours, -1, 255, thickness=1)
print('border pixels', int(np.argwhere(contour_mask > 0).shape[0]))
white_contour = is_white & (contour_mask > 0)
print('white contour', int(white_contour.sum()))
interior_mask = subject & ~((contour_mask > 0))
print('interior mask', int(interior_mask.sum()))
print('interior white', int(np.count_nonzero(is_white & interior_mask)))
print('white pct', white_contour.sum() / max(1, np.argwhere(contour_mask > 0).shape[0]))
print('interior ratio', np.count_nonzero(is_white & interior_mask) / max(1, interior_mask.sum()))
print('analysis', StickerProcessor._analyze_white_border_structural(img, mask))
