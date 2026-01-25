import torch
import matplotlib.pyplot as plt
from model import WaterMetersUNet
from transforms import imageTransforms
import cv2
import os

# Preparing paths for custom predictions
baseDataDir = os.path.join(os.path.dirname(__file__), '..', 'data')

# Custom predictions from predictions directory
custom_dir = os.path.join(baseDataDir, 'predictions', 'photos_to_predict')
save_dir   = os.path.join(baseDataDir, 'predictions', 'predicted_masks')
os.makedirs(save_dir, exist_ok=True)

# Loading model and weight
device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
model = WaterMetersUNet(inChannels=3, outChannels=1).to(device)
modelPath = os.path.join(os.path.dirname(__file__), '..', 'models', 'best.pth')  # CHOOSE CHECKPOINT
checkpoint = torch.load(modelPath, map_location=device)
model.load_state_dict(checkpoint)
model.eval()

for fname in os.listdir(custom_dir):
    if not fname.lower().endswith('.jpg'):
        continue
    img_path = os.path.join(custom_dir, fname)
    # 1) Load and convert to RGB
    bgr = cv2.imread(img_path)
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    orig_resized = cv2.resize(rgb, (512, 512), interpolation=cv2.INTER_AREA)
    # 2) Apply same transformations as in training
    tensor = imageTransforms(rgb).unsqueeze(0).to(device)  # [1,3,512,512]
    # 3) Prediction
    with torch.no_grad():
        out   = model(tensor)
        prob  = torch.sigmoid(out).squeeze().cpu().numpy()   # [512,512]
        predM = (prob > 0.5).astype('uint8') * 255           # 0/255

    # 4) Display both images
    fig, ax = plt.subplots(1,2, figsize=(10,5))
    ax[0].imshow(orig_resized)
    ax[0].set_title('Original')
    ax[0].axis('off')
    ax[1].imshow(predM, cmap='gray')
    ax[1].set_title('Predicted mask')
    ax[1].axis('off')
    plt.suptitle(fname)
    plt.show()

    # 5) Save the predicted mask
    cv2.imwrite(os.path.join(save_dir, f"mask_{fname}"), predM)

print(f"Predictions complete! Masks saved to: {save_dir}")
