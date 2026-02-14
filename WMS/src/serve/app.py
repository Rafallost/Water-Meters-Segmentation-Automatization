"""
FastAPI serving application for Water Meters Segmentation model.

Endpoints:
- GET /health: Health check
- POST /predict: Predict segmentation mask from uploaded image
- GET /metrics: Prometheus metrics

Environment variables:
- MODEL_PATH: Path to model weights (default: best.pth from MLflow or local)
- MLFLOW_TRACKING_URI: MLflow server URI (optional)
- MODEL_VERSION: Model version to load from MLflow (optional)
"""

import os
import io
import base64
import time
from pathlib import Path
from typing import Optional

import torch
import numpy as np
from PIL import Image
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import Response, JSONResponse
from prometheus_client import (
    Counter,
    Histogram,
    Gauge,
    generate_latest,
    CONTENT_TYPE_LATEST,
)

# Import model and transforms from parent directory
import sys

sys.path.append(str(Path(__file__).parent.parent.parent))
from WMS.src.model import WaterMetersUNet
from WMS.src.transforms import valTransforms

# =============================================================================
# Prometheus Metrics
# =============================================================================
predict_count = Counter("wms_predictions_total", "Total number of predictions made")
predict_latency = Histogram(
    "wms_predict_latency_seconds", "Prediction latency in seconds"
)
predict_errors = Counter(
    "wms_predict_errors_total", "Total number of prediction errors"
)
model_loaded = Gauge("wms_model_loaded", "Model loaded status (1=loaded, 0=not loaded)")

# =============================================================================
# FastAPI App
# =============================================================================
app = FastAPI(
    title="Water Meters Segmentation API",
    description="Segmentation API for water meter detection using U-Net",
    version="1.0.0",
)

# Global model variable
model: Optional[torch.nn.Module] = None
device: torch.device = None


# =============================================================================
# Model Loading
# =============================================================================
def load_model_from_path(model_path: str) -> torch.nn.Module:
    """Load model from local path."""
    print(f"Loading model from: {model_path}")

    # Initialize model
    model = WaterMetersUNet(inChannels=3, baseFilters=16, outChannels=1)

    # Load weights
    if not os.path.exists(model_path):
        raise FileNotFoundError(f"Model file not found: {model_path}")

    checkpoint = torch.load(model_path, map_location=device)
    model.load_state_dict(checkpoint)
    model.to(device)
    model.eval()

    print(f"Model loaded successfully from {model_path}")
    return model


def load_model_from_mlflow(model_version: str = "production") -> torch.nn.Module:
    """Load model from MLflow registry."""
    import mlflow
    import mlflow.pytorch

    mlflow_uri = os.environ.get("MLFLOW_TRACKING_URI", "http://localhost:5000")
    mlflow.set_tracking_uri(mlflow_uri)

    print(f"Loading model from MLflow: version={model_version}")

    # Load model from MLflow
    model_name = "water-meter-segmentation"
    model_uri = f"models:/{model_name}/{model_version}"

    try:
        model = mlflow.pytorch.load_model(model_uri, map_location=device)
        model.to(device)
        model.eval()
        print(f"Model loaded successfully from MLflow: {model_uri}")
        return model
    except Exception as e:
        print(f"Failed to load model from MLflow: {e}")
        raise


def initialize_model():
    """Initialize model on startup."""
    global model, device

    # Set device
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Using device: {device}")

    # Try loading model
    model_path = os.environ.get("MODEL_PATH")
    model_version = os.environ.get("MODEL_VERSION")

    try:
        if model_path and os.path.exists(model_path):
            # Load from local path
            model = load_model_from_path(model_path)
        elif model_version:
            # Load from MLflow
            model = load_model_from_mlflow(model_version)
        else:
            # Try default paths
            default_paths = ["best.pth", "WMS/models/best.pth", "/app/best.pth"]
            for path in default_paths:
                if os.path.exists(path):
                    model = load_model_from_path(path)
                    break

            if model is None:
                print("WARNING: No model found. Using untrained model.")
                model = WaterMetersUNet(inChannels=3, baseFilters=16, outChannels=1)
                model.to(device)
                model.eval()

        model_loaded.set(1)
        print("Model initialization complete")

    except Exception as e:
        print(f"ERROR initializing model: {e}")
        model_loaded.set(0)
        raise


# =============================================================================
# Preprocessing & Inference
# =============================================================================
def preprocess_image(image: Image.Image) -> torch.Tensor:
    """
    Preprocess image for inference.

    Args:
        image: PIL Image (RGB)

    Returns:
        torch.Tensor: Preprocessed image tensor (1, 3, 512, 512)
    """
    # Convert to numpy array
    image_np = np.array(image)

    # Apply validation transforms (resize, normalize, etc.)
    image_tensor = valTransforms(image_np)

    # Add batch dimension
    image_tensor = image_tensor.unsqueeze(0)

    return image_tensor


def postprocess_mask(output: torch.Tensor) -> np.ndarray:
    """
    Postprocess model output to binary mask.

    Args:
        output: torch.Tensor (1, 1, 512, 512) - logits

    Returns:
        np.ndarray: Binary mask (512, 512) with values 0/255
    """
    # Apply sigmoid to get probabilities
    probs = torch.sigmoid(output)

    # Threshold at 0.5
    binary_mask = (probs > 0.5).float()

    # Convert to numpy and remove batch/channel dimensions
    mask_np = binary_mask.squeeze().cpu().numpy()

    # Convert to 0-255 range
    mask_uint8 = (mask_np * 255).astype(np.uint8)

    return mask_uint8


def mask_to_base64(mask: np.ndarray) -> str:
    """Convert mask array to base64 encoded PNG."""
    mask_image = Image.fromarray(mask, mode="L")
    buffer = io.BytesIO()
    mask_image.save(buffer, format="PNG")
    buffer.seek(0)
    mask_base64 = base64.b64encode(buffer.read()).decode("utf-8")
    return mask_base64


# =============================================================================
# API Endpoints
# =============================================================================
@app.on_event("startup")
async def startup_event():
    """Initialize model on startup."""
    initialize_model()


@app.get("/")
async def root():
    """Serve prediction UI."""
    html = """<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Water Meters Segmentation</title>
<style>
  body { font-family: sans-serif; max-width: 960px; margin: 40px auto; padding: 0 20px;
         background: #f5f5f5; color: #222; }
  h1 { font-size: 1.4rem; margin-bottom: 4px; }
  p.sub { color: #666; margin: 0 0 24px; font-size: 0.9rem; }
  .drop-zone {
    border: 2px dashed #999; border-radius: 8px; padding: 40px;
    text-align: center; cursor: pointer; background: #fff;
    transition: border-color .2s;
  }
  .drop-zone:hover, .drop-zone.dragover { border-color: #3b82f6; }
  .drop-zone input { display: none; }
  .drop-zone label { cursor: pointer; color: #3b82f6; font-weight: 500; }
  button#predict-btn {
    margin-top: 16px; padding: 10px 28px; background: #3b82f6; color: #fff;
    border: none; border-radius: 6px; font-size: 1rem; cursor: pointer;
  }
  button#predict-btn:disabled { background: #93c5fd; cursor: default; }
  button#download-btn {
    margin-top: 12px; padding: 8px 20px; background: #16a34a; color: #fff;
    border: none; border-radius: 6px; font-size: 0.9rem; cursor: pointer; display: none;
  }
  #status { margin-top: 12px; font-size: 0.9rem; color: #555; min-height: 20px; }
  #results { margin-top: 28px; }
  .result-row { display: flex; gap: 16px; align-items: flex-start; background: #fff;
               padding: 16px; border-radius: 8px; margin-bottom: 16px; }
  .result-row img { width: 220px; height: 220px; object-fit: contain; border: 1px solid #ddd; border-radius: 4px; }
  .result-row .info { font-size: 0.85rem; color: #555; margin-top: 6px; }
  .col { display: flex; flex-direction: column; align-items: center; }
  .col span { font-size: 0.8rem; font-weight: 600; margin-bottom: 6px; color: #444; }
</style>
</head>
<body>
<h1>Water Meters Segmentation</h1>
<p class="sub">Wgraj zdjęcia wodomierzy, aby otrzymać maski segmentacji</p>

<div class="drop-zone" id="drop-zone">
  <input type="file" id="file-input" accept="image/*" multiple>
  <p>Przeciągnij zdjęcia tutaj lub <label for="file-input">wybierz pliki</label></p>
  <p id="file-count" style="color:#555;font-size:.85rem;margin:0"></p>
</div>

<button id="predict-btn" disabled>Predykcja</button>
<button id="download-btn">Pobierz wszystkie maski (.zip)</button>
<div id="status"></div>
<div id="results"></div>

<script>
const dropZone  = document.getElementById('drop-zone');
const fileInput = document.getElementById('file-input');
const predictBtn = document.getElementById('predict-btn');
const downloadBtn = document.getElementById('download-btn');
const statusEl  = document.getElementById('status');
const resultsEl = document.getElementById('results');

let selectedFiles = [];
let maskBlobs = [];

dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('dragover'); });
dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
dropZone.addEventListener('drop', e => {
  e.preventDefault(); dropZone.classList.remove('dragover');
  setFiles([...e.dataTransfer.files].filter(f => f.type.startsWith('image/')));
});
fileInput.addEventListener('change', () => setFiles([...fileInput.files]));

function setFiles(files) {
  selectedFiles = files;
  document.getElementById('file-count').textContent = files.length ? `Wybrano: ${files.length} plik(ów)` : '';
  predictBtn.disabled = files.length === 0;
  resultsEl.innerHTML = '';
  downloadBtn.style.display = 'none';
  maskBlobs = [];
}

predictBtn.addEventListener('click', async () => {
  if (!selectedFiles.length) return;
  predictBtn.disabled = true;
  resultsEl.innerHTML = '';
  maskBlobs = [];
  downloadBtn.style.display = 'none';
  statusEl.textContent = `Przetwarzanie 0 / ${selectedFiles.length}…`;

  for (let i = 0; i < selectedFiles.length; i++) {
    const file = selectedFiles[i];
    statusEl.textContent = `Przetwarzanie ${i + 1} / ${selectedFiles.length}: ${file.name}…`;

    const formData = new FormData();
    formData.append('image', file);

    try {
      const res = await fetch('/predict', { method: 'POST', body: formData });
      if (!res.ok) { const e = await res.json(); throw new Error(e.detail || res.statusText); }
      const data = await res.json();

      const origUrl = URL.createObjectURL(file);
      const maskUrl = 'data:image/png;base64,' + data.mask_base64;

      const raw = atob(data.mask_base64);
      const arr = new Uint8Array(raw.length);
      for (let j = 0; j < raw.length; j++) arr[j] = raw.charCodeAt(j);
      const maskName = 'mask_' + file.name.replace(/\\.[^.]+$/, '.png');
      maskBlobs.push({ name: maskName, blob: new Blob([arr], { type: 'image/png' }) });

      const row = document.createElement('div');
      row.className = 'result-row';
      row.innerHTML = `
        <div class="col"><span>Oryginał</span><img src="${origUrl}" alt="original"></div>
        <div class="col"><span>Maska</span><img src="${maskUrl}" alt="mask">
          <a href="${maskUrl}" download="${maskName}"
             style="margin-top:6px;font-size:.8rem;color:#3b82f6">Pobierz maskę</a>
        </div>
        <div class="info">${file.name}<br>Latencja: ${data.metadata.latency_seconds}s</div>`;
      resultsEl.appendChild(row);
    } catch (err) {
      const row = document.createElement('div');
      row.className = 'result-row';
      row.style.borderLeft = '4px solid #ef4444';
      row.textContent = file.name + ': Błąd — ' + err.message;
      resultsEl.appendChild(row);
    }
  }

  statusEl.textContent = `Gotowe (${selectedFiles.length} zdjęć).`;
  predictBtn.disabled = false;
  if (maskBlobs.length > 0) downloadBtn.style.display = 'inline-block';
});

downloadBtn.addEventListener('click', async () => {
  const { default: JSZip } = await import('https://cdn.jsdelivr.net/npm/jszip@3.10.1/+esm');
  const zip = new JSZip();
  maskBlobs.forEach(({ name, blob }) => zip.file(name, blob));
  const content = await zip.generateAsync({ type: 'blob' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(content);
  a.download = 'maski.zip';
  a.click();
});
</script>
</body>
</html>"""
    from fastapi.responses import HTMLResponse

    return HTMLResponse(content=html)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    if model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")

    return {
        "status": "healthy",
        "model_loaded": model is not None,
        "device": str(device),
    }


@app.post("/predict")
async def predict(image: UploadFile = File(...)):
    """
    Predict segmentation mask from uploaded image.

    Args:
        image: Uploaded image file (JPG, PNG)

    Returns:
        JSON with base64-encoded mask and metadata
    """
    if model is None:
        predict_errors.inc()
        raise HTTPException(status_code=503, detail="Model not loaded")

    start_time = time.time()

    try:
        # Read and validate image
        image_bytes = await image.read()
        image_pil = Image.open(io.BytesIO(image_bytes))

        # Convert to RGB if needed
        if image_pil.mode != "RGB":
            image_pil = image_pil.convert("RGB")

        # Preprocess
        image_tensor = preprocess_image(image_pil)
        image_tensor = image_tensor.to(device)

        # Inference
        with torch.no_grad():
            output = model(image_tensor)

        # Postprocess
        mask = postprocess_mask(output)

        # Encode to base64
        mask_base64 = mask_to_base64(mask)

        # Record metrics
        latency = time.time() - start_time
        predict_count.inc()
        predict_latency.observe(latency)

        # Return response
        return JSONResponse(
            {
                "status": "success",
                "mask_base64": mask_base64,
                "metadata": {
                    "input_size": list(image_pil.size),
                    "output_size": [512, 512],
                    "latency_seconds": round(latency, 3),
                    "device": str(device),
                },
            }
        )

    except Exception as e:
        predict_errors.inc()
        print(f"Prediction error: {e}")
        raise HTTPException(status_code=500, detail=f"Prediction failed: {str(e)}")


@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


# =============================================================================
# Entry Point
# =============================================================================
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
