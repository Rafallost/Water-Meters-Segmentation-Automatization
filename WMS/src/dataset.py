from torch.utils.data import Dataset # All PyTorch datasets must inherit from this base dataset class
import cv2
import torch
import numpy as np

class WMSDataset(Dataset):
    def __init__(self, imagePaths, maskPaths, imageTransforms=None, paired_transforms=None):
        """
        Args:
            imagePaths: List of image paths
            maskPaths: List of mask paths
            imageTransforms: Legacy transforms (applied only to image) - for backward compatibility
            paired_transforms: New transforms that take (image, mask) and return (image_tensor, mask_tensor)
        """
        self.imagePaths = imagePaths
        self.maskPaths = maskPaths
        self.imageTransforms = imageTransforms
        self.paired_transforms = paired_transforms

    def __len__(self):
        return len(self.imagePaths)

    def __getitem__(self, i):
        image_path = self.imagePaths[i] #Grab the image path form the current index
        image = cv2.imread(image_path) # Load image
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

        mask = cv2.imread(self.maskPaths[i], cv2.IMREAD_GRAYSCALE)  # uint8
        # Threshold to 0/1
        mask = (mask >= 127).astype(np.uint8)

        # Use new paired transforms if available (for training with augmentation)
        if self.paired_transforms:
            image, mask = self.paired_transforms(image, mask)
            return image, mask

        # Otherwise use legacy transforms (for validation/test or old code)
        if self.imageTransforms:
            image = self.imageTransforms(image)

        # resize from nearest neighbor
        mask = cv2.resize(mask, (512, 512), interpolation=cv2.INTER_NEAREST)
        # To tensor float32 0.0/1.0
        mask = torch.from_numpy(mask.astype(np.float32))[None, ...]  # 1xHxW

        return image, mask


