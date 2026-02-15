# GitHub Actions Workflows

Przegląd wszystkich workflow w tym projekcie i ich wzajemnych zależności.

## Architektura

```
Użytkownik pushuje dane
        │
        ▼
training-data-pipeline.yaml   ←── główny pipeline (auto)
  ├── ec2-control.yaml         ←── reużywalny: start/stop EC2
  └── deploy-model.yaml        ←── reużywalny: build + deploy

Push kodu do main
        │
        ▼
release-deploy.yaml            ←── wyzwalacz releasu (auto)
  ├── ec2-control.yaml
  └── deploy-model.yaml

Ręczne operacje
  ├── ec2-manual-control.yaml  ←── start/stop EC2 z UI
  └── deploy-model.yaml        ←── ręczny deploy
```

## Opis workflow

### `training-data-pipeline.yaml` — Główny pipeline danych i treningu

Wyzwalacz: push do branchy `data/**`

Jest to centralny workflow projektu. Uruchamia się automatycznie gdy użytkownik pushuje nowe dane treningowe przez pre-push hook. Wykonuje pełny cykl:

1. Pobiera dane z S3, scala z nowymi danymi, waliduje jakość (pary obraz/maska, rozmiar 512×512, maski binarne)
2. Uruchamia EC2
3. Trenuje model, ocenia quality gate względem dynamicznego baseline z MLflow
4. Zatrzymuje EC2 (zawsze, nawet przy błędzie)
5. Jeśli model się poprawił: tworzy PR i włącza auto-merge
6. Jeśli nie: branch `data/TIMESTAMP` pozostaje do przeglądu

### `release-deploy.yaml` — Deploy przy zmianie kodu

Wyzwalacz: push do `main` gdy zmieniają się pliki:

- `WMS/src/serve/**` (kod aplikacji)
- `docker/**` (Dockerfile)
- `devops/helm/**` (Helm charts)
- `infrastructure/helm-values.yaml`
- `requirements.txt`
- `WMS/models/production_current.json`

Orkiestruje deployment przy zmianach kodu (nie danych). Sekwencja: start EC2 → deploy → stop EC2. Wymaga, żeby model Production istniał już w MLflow — w przeciwnym razie zakończy się błędem.

### `deploy-model.yaml` — Reużywalny workflow deploymentu

Wyzwalacz: wywoływany przez inne workflow (`workflow_call`) lub ręcznie

Wykonuje faktyczne kroki deploymentu. Używany zarówno przez `training-data-pipeline.yaml` (po poprawie modelu) jak i `release-deploy.yaml` (przy zmianie kodu). Kroki:

1. Logowanie do ECR (przez boto3 + IAM role EC2)
2. Build i push obrazu Docker do ECR
3. Odświeżenie ECR imagePullSecret w k3s
4. Walidacja że model Production istnieje w MLflow
5. Deploy przez Helm (`wms-model`)
6. Weryfikacja poda i health check
7. Cleanup starych namespace'ów `model-*`

Uruchamia się na self-hosted runner (EC2) — wymaga dostępu do k3s i MLflow.

### `ec2-control.yaml` — Reużywalny start/stop EC2

Wyzwalacz: wywoływany przez inne workflow (`workflow_call`)

Uruchamia lub zatrzymuje instancję EC2 i czeka na jej gotowość (SSH, GitHub Actions runner). Używany przez wszystkie workflowy wymagające EC2.

### `ec2-manual-control.yaml` — Ręczne zarządzanie EC2

Wyzwalacz: ręczny (`workflow_dispatch`) z wyborem akcji (start/stop)

Do ręcznego uruchamiania i zatrzymywania EC2 z poziomu GitHub Actions UI. Przydatne przy debugowaniu lub oszczędzaniu kosztów.

Jak uruchomić:

1. GitHub → **Actions** → **"Manual EC2 Control"**
2. Kliknij **"Run workflow"**
3. Z dropdownu wybierz `start` lub `stop`
4. Kliknij **"Run workflow"**

Po uruchomieniu z opcją `start` w zakładce **Summary** wyświetli się publiczne IP, URL do MLflow i komenda SSH.

### `ci.yaml` — Continuous Integration

Wyzwalacz: push do `main` lub `develop`, oraz pull request do `main`

Sprawdzenia jakości kodu: linting, testy jednostkowe, walidacja konfiguracji Helm/Terraform.

## Zależności między workflow

| Workflow                      | Wywołuje                                |
| ----------------------------- | --------------------------------------- |
| `training-data-pipeline.yaml` | `ec2-control.yaml`, `deploy-model.yaml` |
| `release-deploy.yaml`         | `ec2-control.yaml`, `deploy-model.yaml` |
| `deploy-model.yaml`           | — (endpoint, nie wywołuje innych)       |
| `ec2-control.yaml`            | — (endpoint, nie wywołuje innych)       |
| `ec2-manual-control.yaml`     | —                                       |
| `ci.yaml`                     | —                                       |

## Wymagane sekrety

| Sekret                  | Używany przez      | Opis                  |
| ----------------------- | ------------------ | --------------------- |
| `AWS_ACCESS_KEY_ID`     | wszystkie          | AWS credentials       |
| `AWS_SECRET_ACCESS_KEY` | wszystkie          | AWS credentials       |
| `AWS_SESSION_TOKEN`     | wszystkie          | AWS session (Academy) |
| `EC2_INSTANCE_ID`       | `ec2-control.yaml` | ID instancji EC2      |
| `EC2_HOST`              | `ec2-control.yaml` | IP/hostname EC2       |
| `EC2_SSH_KEY`           | `ec2-control.yaml` | Klucz SSH do EC2      |
