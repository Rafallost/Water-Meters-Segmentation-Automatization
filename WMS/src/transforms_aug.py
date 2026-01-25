import torchvision.transforms as TRANS
import torchvision.transforms.functional as TF
import numpy as np
import cv2
import torch
import random

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

# Validation/Test transforms (no augmentation)
valTransforms = TRANS.Compose([
    TRANS.ToPILImage(),
    TRANS.Resize((512, 512)),
    TRANS.Lambda(to_float_np),
    TRANS.Lambda(contrast_stretch),
    TRANS.Lambda(median_blur),
    TRANS.Lambda(lambda arr: torch.from_numpy(arr).permute(2, 0, 1)),  # HWC -> CHW
])

class TrainTransforms:
    """
    Training transforms with spatial augmentation applied to both image and mask.
    """
    def __init__(self, p_hflip=0.5, p_vflip=0.3, rotation_degrees=15, p_rotate=0.5):
        self.p_hflip = p_hflip
        self.p_vflip = p_vflip
        self.rotation_degrees = rotation_degrees
        self.p_rotate = p_rotate

    def __call__(self, image, mask):
        """
        Apply augmentation to both image and mask.
        Args:
            image: numpy array (H, W, C) uint8
            mask: numpy array (H, W) uint8 with values 0/1
        Returns:
            image: torch tensor (C, H, W) float32
            mask: torch tensor (1, H, W) float32
        """
        # Convert to PIL for torchvision transforms
        from PIL import Image
        image_pil = Image.fromarray(image)
        mask_pil = Image.fromarray((mask * 255).astype(np.uint8))

        # Resize
        image_pil = TF.resize(image_pil, [512, 512])
        mask_pil = TF.resize(mask_pil, [512, 512], interpolation=TF.InterpolationMode.NEAREST)

        # Random horizontal flip
        if random.random() < self.p_hflip:
            image_pil = TF.hflip(image_pil)
            mask_pil = TF.hflip(mask_pil)

        # Random vertical flip
        if random.random() < self.p_vflip:
            image_pil = TF.vflip(image_pil)
            mask_pil = TF.vflip(mask_pil)

        # Random rotation
        if random.random() < self.p_rotate:
            angle = random.uniform(-self.rotation_degrees, self.rotation_degrees)
            image_pil = TF.rotate(image_pil, angle, interpolation=TF.InterpolationMode.BILINEAR)
            mask_pil = TF.rotate(mask_pil, angle, interpolation=TF.InterpolationMode.NEAREST)

        # Convert image to numpy for preprocessing
        image_np = np.array(image_pil).astype(np.float32) / 255.0
        image_np = contrast_stretch(image_np)
        image_np = median_blur(image_np)

        # Color jitter (only for image)
        if random.random() < 0.3:
            brightness_factor = random.uniform(0.8, 1.2)
            image_np = np.clip(image_np * brightness_factor, 0.0, 1.0)

        # Convert to torch tensors
        image_tensor = torch.from_numpy(image_np).permute(2, 0, 1)  # HWC -> CHW
        mask_np = (np.array(mask_pil) >= 127).astype(np.float32)
        mask_tensor = torch.from_numpy(mask_np)[None, ...]  # Add channel dimension

        return image_tensor, mask_tensor
