# WMS/

Kod modelu segmentacji wodomierzy. Zawiera architekturę U-Net, skrypty treningowe, serwer FastAPI do inferencji i narzędzia do lokalnych predykcji.

## Struktura

```
WMS/
├── configs/
│   └── train.yaml          # hiperparametry i konfiguracja treningu
├── data/
│   ├── training/
│   │   ├── images/         # zdjęcia wodomierzy (śledzone przez DVC)
│   │   ├── masks/          # maski binarne (śledzone przez DVC)
│   │   ├── images.dvc      # manifest DVC → S3
│   │   ├── masks.dvc       # manifest DVC → S3
│   │   └── temp/           # tymczasowy split train/val/test (generowany automatycznie)
│   └── predictions/
│       └── photos_to_predict/   # zdjęcia do ręcznych predykcji (predicts.py)
├── models/                 # wagi modelu — gitignored, tylko lokalnie
│   ├── best.pth
│   └── metrics.json
├── src/
│   ├── model.py            # architektura WaterMetersUNet
│   ├── dataset.py          # PyTorch Dataset
│   ├── transforms.py       # preprocessing i augmentacje
│   ├── prepareDataset.py   # split danych (80/10/10), walidacja
│   ├── train.py            # pętla treningowa + MLflow
│   ├── predicts.py         # lokalne predykcje z plików
│   ├── download_model.py   # pobieranie modelu z MLflow
│   └── serve/
│       └── app.py          # serwer FastAPI (serving produkcyjny)
└── tests/                  # testy jednostkowe i integracyjne
```

## Dane treningowe

Dane są przechowywane w S3 i wersjonowane przez DVC. Katalogi `images/` i `masks/` są widoczne w Git (nie ignorowane), żeby można było wrzucać nowe pliki przez `git add`. Sama zawartość jest śledzona przez pliki `.dvc`, nie przez Git.

Konwencja nazewnicza plików: `id_<ID>_value_<odczyt>.jpg`, gdzie odczyt to wartość z wodomierza, np. `id_42_value_211_427.jpg` = odczyt 211,427. Każde zdjęcie ma odpowiadającą maskę o tym samym stem nazwy (rozszerzenie może się różnić — `.jpg` lub `.png`).

Maski są binarne: piksel = 0 (tło) lub 255 (tarcza wodomierza). Podczas ładowania progowanie przy 127 normalizuje je do wartości 0/1.

Aby pobrać dane z S3:
```bash
dvc pull
```

Aby dodać nowe zdjęcia i uruchomić pipeline treningowy — wystarczy skopiować pary obraz+maska do katalogów `images/` i `masks/`, a następnie wykonać `git push`. Pre-push hook automatycznie tworzy branch `data/TIMESTAMP` i uruchamia GitHub Actions.

## Pliki źródłowe (`src/`)

### model.py — architektura

`WaterMetersUNet` to implementacja U-Net z podwójnymi blokami konwolucyjnymi (double conv) na każdym poziomie. Enkoder składa się z 4 etapów z MaxPool2d między nimi, za nimi bottleneck, po którym następuje symetryczny dekoder z bilinearnym upsamplingiem i skip connections. Każdy etap enkoder+dekoder ma swój odpowiednik z concatenacją cech (skip connection). Ostatnia warstwa to Conv2d 1×1 redukująca do 1 kanału — logity dla BCEWithLogitsLoss.

Parametry wejściowe:
- `inChannels=3` — obraz RGB
- `baseFilters=16` — bazowa szerokość sieci (16 → 32 → 64 → 128 → 256 w bottleneck)
- `outChannels=1` — maska binarna

### prepareDataset.py — podział danych

Skrypt wczytuje wszystkie pliki z `data/training/images/` i `data/training/masks/`, dopasowuje pary po stem nazwy pliku (obsługuje różne rozszerzenia) i dzieli zestaw na:
- 80% train, 10% val, 10% test (deterministycznie według `WMS_SEED`)

Wynik zapisywany jest do `data/training/temp/{train,val,test}/{images,masks}/`. Katalog `temp/` jest tworzony od nowa przy każdym uruchomieniu treningu — nie jest commitowany ani śledzony przez DVC.

Uruchomiony bezpośrednio (`__main__`) generuje wykresy rozkładu klas pikseli i podziału zbioru do katalogu `Results/`.

### transforms.py — preprocessing i augmentacje

`valTransforms` (walidacja i test):
1. Resize do 512×512
2. Normalizacja do [0.0, 1.0]
3. Rozciąganie kontrastu (percentyl 2–98)
4. Medianowe rozmycie (kernel 3×3)
5. Konwersja do tensora CHW

`TrainTransforms` (trening) — stosowane jednocześnie do obrazu i maski, żeby augmentacje przestrzenne były spójne:
- random horizontal flip (p=0.5)
- random vertical flip (p=0.3)
- random rotation ±10° (p=0.5)
- color jitter: losowy brightness factor 0.8–1.2 (p=0.3, tylko obraz)

Cały preprocessing z `valTransforms` stosowany jest też po augmentacjach geometrycznych.

### dataset.py — WMSDataset

Klasa `WMSDataset` dziedziczy po `torch.utils.data.Dataset`. Ładuje obraz przez OpenCV (BGR→RGB), maskę jako grayscale i proguje ją przy 127 do wartości 0/1 float32. Obsługuje dwa tryby transformacji: `paired_transforms` dla treningu (synchroniczne augmentacje) i `imageTransforms` dla val/test (tylko obraz).

### train.py — pętla treningowa

Punkt wejścia do treningu. Działanie krok po kroku:

1. Wczytuje konfigurację z `configs/train.yaml` i seed z `--seed` (domyślnie 42).
2. Uruchamia `prepareDataset.py` jako subprocess (przekazuje seed przez `WMS_SEED`).
3. Tworzy `DataLoader`-y z `WMSDataset` dla wszystkich trzech splitów.
4. Inicjalizuje `WaterMetersUNet`, `BCEWithLogitsLoss` (pos_weight=1.0), Adam i `ReduceLROnPlateau`.
5. Jeśli istnieje `models/best.pth` — ewaluuje go, żeby ustalić `previousBestVal` (punkt odniesienia do porównania po sesji).
6. Uruchamia pętlę treningową (max `epochs`, z early stopping po `patience=5` epokach bez poprawy val loss). Co 5 epok loguje metryki do MLflow.
7. Po zakończeniu: jeśli `bestSessionVal < previousBestVal` — nadpisuje `best.pth`.
8. Zapisuje `metrics.json` z wynikami test Dice/IoU/Hausdorff.
9. Generuje wykresy (loss, accuracy, dice, iou + predykcje na batchu testowym) do `Results/`.
10. Rejestruje model do MLflow Model Registry (`water-meter-segmentation`).

Wersja modelu = `{GITHUB_SHA[:7]}-{md5(dvc.lock)[:8]}`.

Metryki śledzone: Loss, Pixel Accuracy, Dice coefficient, IoU dla każdego splitu na każdej epoce. Na końcu dodatkowo Hausdorff distance na zbiorze testowym.

Konfiguracja (`configs/train.yaml`):

| Parametr | Wartość |
|---|---|
| epochs | 100 |
| batch_size | 4 |
| learning_rate | 0.0001 |
| weight_decay | 0.0001 |
| early_stopping_patience | 5 |
| scheduler factor/patience | 0.5 / 3 |

### predicts.py — lokalne predykcje

Wczytuje wagi z `models/production.pth` (pobrane z MLflow) lub fallback do `models/best.pth`. Przetwarza wszystkie pliki z `data/predictions/photos_to_predict/`, wyświetla porównanie oryginał/maska i zapisuje maski do `data/predictions/predicted_masks/`.

Jeśli brak modelu, wyświetla instrukcję pobrania przez `download_model.py`.

### serve/app.py — API produkcyjne

FastAPI na porcie 8000. Trzy endpointy:

- `GET /health` — status aplikacji i informacja o załadowanym modelu
- `POST /predict` — przyjmuje plik obrazu (JPG/PNG), zwraca maskę w base64 + metadane (rozmiar, latencja, device)
- `GET /metrics` — metryki Prometheusa

Model ładowany przy starcie. Kolejność prób:
1. `MODEL_PATH` (zmienna środowiskowa)
2. MLflow (`MODEL_VERSION` → `models:/water-meter-segmentation/<version>`)
3. domyślne ścieżki: `best.pth`, `WMS/models/best.pth`, `/app/best.pth`

Preprocessing przy inferencji = identyczny `valTransforms` jak podczas treningu (resize 512×512, contrast stretch, median blur).

Metryki Prometheusa: `wms_predictions_total`, `wms_predict_latency_seconds`, `wms_predict_errors_total`, `wms_model_loaded`.
