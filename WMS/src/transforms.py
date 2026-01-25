import torchvision.transforms as TRANS
import numpy as np
import cv2
import torch

def to_float_np(img):
    arr = np.array(img).astype(np.float32) / 255.0
    return arr

def contrast_stretch(img: np.ndarray):
    p2, p98 = np.percentile(img, (2, 98))
    img = (img - p2) / (p98 - p2 + 1e-6)
    return np.clip(img, 0.0, 1.0)

def median_blur(img: np.ndarray):
    u8 = (img * 255).astype(np.uint8)
    blurred = cv2.medianBlur(u8, 3)
    return blurred.astype(np.float32) / 255.0

imageTransforms = TRANS.Compose([
    TRANS.ToPILImage(),
    TRANS.Resize((512, 512)),
    TRANS.Lambda(to_float_np),
    TRANS.Lambda(contrast_stretch),
    TRANS.Lambda(median_blur),
    TRANS.Lambda(lambda arr: torch.from_numpy(arr).permute(2, 0, 1)),  # HWC -> CHW
])
