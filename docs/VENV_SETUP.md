# Virtual Environment Setup Guide

## Why Virtual Environment?

**Problem:** Conflicting package versions across different tools (DVC vs black vs boto3).

**Solution:** Isolated Python environment with consistent dependencies.

---

## Quick Setup (Recommended)

### 1. Create Virtual Environment

```bash
# Navigate to project root
cd Water-Meters-Segmentation-Autimatization

# Create venv
python -m venv venv

# Activate
# Windows (PowerShell):
.\venv\Scripts\Activate.ps1

# Windows (CMD):
.\venv\Scripts\activate.bat

# Linux/Mac:
source venv/bin/activate
```

### 2. Install Dependencies

```bash
# Upgrade pip first
python -m pip install --upgrade pip

# Install project dependencies
pip install -r requirements.txt

# For local DVC work (Python 3.14 compatibility fix):
pip install -r requirements-local.txt
```

### 3. Verify Installation

```bash
# Check DVC works
dvc version

# Check Python version
python --version

# Check installed packages
pip list
```

---

## Recommended: Python 3.12 (not 3.14)

**Why?** Python 3.14 is bleeding edge - many ML libraries not fully compatible yet.

### Option 1: Use pyenv (Linux/Mac)

```bash
# Install pyenv
curl https://pyenv.run | bash

# Install Python 3.12
pyenv install 3.12.8

# Set for this project
pyenv local 3.12.8

# Create venv with Python 3.12
python -m venv venv
```

### Option 2: Download Python 3.12 (Windows)

1. Download from: https://www.python.org/downloads/release/python-3128/
2. Install (make sure to check "Add to PATH")
3. Create venv:
   ```bash
   py -3.12 -m venv venv
   ```

---

## Fix DVC Import Error (Python 3.14)

If you see:
```
ERROR: cannot import name '_DIR_MARK' from 'pathspec.patterns.gitwildmatch'
```

**Quick fix:**

```bash
# Activate venv first
.\venv\Scripts\Activate.ps1

# Install compatible versions
pip install "pathspec==0.11.2"
pip install "dvc[s3]==3.55.2"

# Or use requirements-local.txt:
pip install -r requirements-local.txt
```

---

## Daily Workflow

### Starting Work

```bash
# Activate venv
.\venv\Scripts\Activate.ps1  # Windows
# source venv/bin/activate    # Linux/Mac

# You should see (venv) in your prompt:
# (venv) PS D:\school\bsc\...>
```

### Adding New Packages

```bash
# Install package
pip install package-name

# Update requirements.txt
pip freeze > requirements-freeze.txt

# Then manually add to requirements.txt if needed
```

### Deactivating

```bash
deactivate
```

---

## .gitignore Updates

Make sure venv is ignored:

```gitignore
# Virtual environments
venv/
.venv/
env/
ENV/
```

✅ Already in .gitignore!

---

## For CI/CD & Docker

**Important:** CI/CD and Docker should NOT use venv.

They use requirements.txt directly:
- ✅ GitHub Actions: `pip install -r requirements.txt`
- ✅ Docker: `RUN pip install -r requirements.txt`

Virtual env is **only for local development**.

---

## Troubleshooting

### "Scripts\Activate.ps1 cannot be loaded"

**Cause:** PowerShell execution policy.

**Solution:**
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### "pip: command not found"

**Cause:** Python not in PATH.

**Solution:**
```bash
# Use python -m pip instead
python -m pip install -r requirements.txt
```

### Packages conflicting

**Solution:**
```bash
# Delete venv and recreate
rm -r venv
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

---

## Best Practices

1. ✅ **Always activate venv** before working
2. ✅ **Keep requirements.txt** updated (but don't pin versions yet)
3. ✅ **Don't commit venv/** to Git
4. ✅ **Use Python 3.12** (not 3.14) for stability
5. ✅ **Document any special install steps** in this file

---

## For Your Thesis

### Reproducibility Section

Mention in thesis:
- Virtual environments for dependency isolation
- requirements.txt for reproducible installations
- Version locking for production deployments
- CI/CD uses containerized environments (Docker)

### Comparison: Manual vs Automated

| Aspect | Manual Setup | Virtual Env + Requirements |
|--------|--------------|---------------------------|
| Setup time | Varies | 2 minutes |
| Consistency | Low (each dev different) | High (same packages) |
| Conflicts | Common | Rare |
| Reproducibility | Poor | Excellent |

---

## Next Steps

1. ✅ Create venv: `python -m venv venv`
2. ✅ Activate: `.\venv\Scripts\Activate.ps1`
3. ✅ Install deps: `pip install -r requirements.txt`
4. ✅ Fix DVC: `pip install -r requirements-local.txt`
5. ✅ Test: `dvc version` should work
6. ✅ Try git push again!
