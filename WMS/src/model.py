import torch
import torch.nn as nn # Conv2d, BatchNorm2d etc.
import torch.nn.functional as F # interpolate

class WaterMetersUNet(nn.Module):
    def __init__(self, inChannels, baseFilters=16, outChannels=1):
        super(WaterMetersUNet, self).__init__()

        # ======================================= ENCODER =============================================
        # Double convolution blocks for better feature extraction
        self.enc1 = nn.Sequential(
            nn.Conv2d(inChannels, baseFilters, kernel_size=3, padding=1), # inChannels -> baseChannels (3 -> 16)
            nn.BatchNorm2d(baseFilters),
            nn.ReLU(inplace=True),
            nn.Conv2d(baseFilters, baseFilters, kernel_size=3, padding=1), # Double conv
            nn.BatchNorm2d(baseFilters),
            nn.ReLU(inplace=True)
        )
        self.pool1 = nn.MaxPool2d(2, stride=2) # Resize h, w by half (e.g. 512 -> 256)


        self.enc2 = nn.Sequential(
            nn.Conv2d(baseFilters, baseFilters * 2, kernel_size=3, padding=1), # (16 -> 32)
            nn.BatchNorm2d(baseFilters * 2),
            nn.ReLU(inplace=True),
            nn.Conv2d(baseFilters * 2, baseFilters * 2, kernel_size=3, padding=1), # Double conv
            nn.BatchNorm2d(baseFilters * 2),
            nn.ReLU(inplace=True)
        )
        self.pool2 = nn.MaxPool2d(2, stride=2)


        self.enc3 = nn.Sequential(
            nn.Conv2d(baseFilters * 2, baseFilters * 4, kernel_size=3, padding=1), # (32 -> 64)
            nn.BatchNorm2d(baseFilters * 4),
            nn.ReLU(inplace=True),
            nn.Conv2d(baseFilters * 4, baseFilters * 4, kernel_size=3, padding=1), # Double conv
            nn.BatchNorm2d(baseFilters * 4),
            nn.ReLU(inplace=True)
        )
        self.pool3 = nn.MaxPool2d(2, stride=2)

        self.enc4 = nn.Sequential(
            nn.Conv2d(baseFilters * 4, baseFilters * 8, kernel_size=3, padding=1), # (64 -> 128)
            nn.BatchNorm2d(baseFilters * 8),
            nn.ReLU(inplace=True),
            nn.Conv2d(baseFilters * 8, baseFilters * 8, kernel_size=3, padding=1), # Double conv
            nn.BatchNorm2d(baseFilters * 8),
            nn.ReLU(inplace=True)
        )
        self.pool4 = nn.MaxPool2d(2, stride=2)

        # Deepest layer of UNet, without pooling after that
        self.bottleneck = nn.Sequential(
            nn.Conv2d(baseFilters * 8, baseFilters * 16, kernel_size=3, padding=1), # (128 -> 256)
            nn.BatchNorm2d(baseFilters * 16),
            nn.ReLU(inplace=True),
            nn.Conv2d(baseFilters * 16, baseFilters * 16, kernel_size=3, padding=1), # Double conv
            nn.BatchNorm2d(baseFilters * 16),
            nn.ReLU(inplace=True)
        )


        # ==================== DECODER (Rebuilding resolution (upsampling)) ======================
        self.dec4 = nn.Sequential( # bottleneck + enc4 -> (256 + 128 = 384 [channels])
            nn.Conv2d(baseFilters * 16 + baseFilters * 8, baseFilters * 8, kernel_size=3, padding=1), # 384 -> 128
            nn.BatchNorm2d(baseFilters * 8),
            nn.ReLU(inplace=True),
            nn.Conv2d(baseFilters * 8, baseFilters * 8, kernel_size=3, padding=1), # Double conv
            nn.BatchNorm2d(baseFilters * 8),
            nn.ReLU(inplace=True)
        )

        self.dec3 = nn.Sequential( # dec4 + enc3 -> (128 + 64 = 192 [channels])
            nn.Conv2d(baseFilters * 8 + baseFilters * 4, baseFilters * 4, kernel_size=3, padding=1), # 192 -> 64
            nn.BatchNorm2d(baseFilters * 4),
            nn.ReLU(inplace=True),
            nn.Conv2d(baseFilters * 4, baseFilters * 4, kernel_size=3, padding=1), # Double conv
            nn.BatchNorm2d(baseFilters * 4),
            nn.ReLU(inplace=True)
        )

        self.dec2 = nn.Sequential( # dec3 + enc2 -> (64 + 32 = 96 [channels])
            nn.Conv2d(baseFilters * 4 + baseFilters * 2, baseFilters * 2, kernel_size=3, padding=1), # 96 -> 32
            nn.BatchNorm2d(baseFilters * 2),
            nn.ReLU(inplace=True),
            nn.Conv2d(baseFilters * 2, baseFilters * 2, kernel_size=3, padding=1), # Double conv
            nn.BatchNorm2d(baseFilters * 2),
            nn.ReLU(inplace=True)
        )

        self.dec1 = nn.Sequential( # dec2 + enc1 -> (32 + 16 = 48 [channels])
            nn.Conv2d(baseFilters * 2 + baseFilters, baseFilters, kernel_size=3, padding=1), # 48 -> 16
            nn.BatchNorm2d(baseFilters),
            nn.ReLU(inplace=True),
            nn.Conv2d(baseFilters, baseFilters, kernel_size=3, padding=1), # Double conv
            nn.BatchNorm2d(baseFilters),
            nn.ReLU(inplace=True)
        )

        # Last layer 1x1 16 -> outChannels (1)
        self.final = nn.Conv2d(baseFilters, outChannels, kernel_size=1)


    def forward(self, x):
        e1 = self.enc1(x)       # (N, baseFilters, H, W)
        p1 = self.pool1(e1)     # (N, baseFilters, H/2, W/2)

        e2 = self.enc2(p1)      # (N, baseFilters*2, H/2, W/2)
        p2 = self.pool2(e2)     # (N, baseFilters*2, H/4, W/4)

        e3 = self.enc3(p2)      # (N, baseFilters*4, H/4, W/4)
        p3 = self.pool3(e3)     # (N, baseFilters*4, H/8, W/8)

        e4 = self.enc4(p3)      # (N, baseFilters*8, H/8, W/8)
        p4 = self.pool4(e4)     # (N, baseFilters*8, H/16, W/16)

        b = self.bottleneck(p4)  # (N, baseFilters*16, H/16, W/16)

        d4 = F.interpolate(b, size=e4.shape[2:], mode='bilinear', align_corners=False)
        d4 = torch.cat((d4, e4), dim=1)
        d4 = self.dec4(d4)                                                                  # (N, baseFilters*8, H/8, W/8)

        d3 = F.interpolate(d4, size=e3.shape[2:], mode='bilinear', align_corners=False)
        d3 = torch.cat((d3, e3), dim=1)
        d3 = self.dec3(d3)                                                                  # (N, baseFilters*4, H/4, W/4)

        d2 = F.interpolate(d3, size=e2.shape[2:], mode='bilinear', align_corners=False)
        d2 = torch.cat((d2, e2), dim=1)
        d2 = self.dec2(d2)                                                                  # (N, baseFilters*2, H/2, W/2)

        d1 = F.interpolate(d2, size=e1.shape[2:], mode='bilinear', align_corners=False)
        d1 = torch.cat((d1, e1), dim=1)
        d1 = self.dec1(d1)                                                                  # (N, baseFilters, H, W)

        out = self.final(d1) # (N, out_channels, H, W)
        return out