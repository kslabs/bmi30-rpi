# 📦 RPI_DEPLOY - Git Setup Guide

## Overview

The `RPI_DEPLOY` folder contains everything needed to run BMI30 firmware tests on Raspberry Pi.

**Repository**: https://github.com/kslabs/bmi30-rpi  
**Branch**: main  
**Purpose**: Host firmware, scripts, and documentation for RPi deployment

---

## 📁 Structure

```
RPI_DEPLOY/
├── .gitignore              # Git ignore rules
├── START_HERE.md           # RPi quick start guide
├── run_setup.sh            # Setup script for RPi
├── run_test.sh             # Test execution script
├── scripts/
│   └── vendor_stream_read.py # Python USB streaming tool
├── firmware/               # Compiled firmware files
├── docs/                   # Additional documentation
└── .git/                   # Git repository
```

---

## 🚀 Usage on Raspberry Pi

### 1. Clone the repository

```bash
git clone https://github.com/kslabs/bmi30-rpi.git
cd bmi30-rpi
```

### 2. Run setup

```bash
chmod +x run_setup.sh
./run_setup.sh
```

### 3. Run tests

```bash
chmod +x run_test.sh
./run_test.sh
```

### 4. Manual testing

```bash
python3 scripts/vendor_stream_read.py
```

---

## 💾 Git Workflow for RPI Repository

### Check status

```bash
git status
```

### Pull latest firmware

```bash
git pull
```

### Add updates

```bash
git add scripts/
git commit -m "Update: Improved USB reading stability"
git push
```

### Create a backup branch

```bash
git checkout -b backup-$(date +%Y%m%d)
git push origin backup-$(date +%Y%m%d)
```

---

## 📋 Files Included

| File | Purpose |
|------|---------|
| **START_HERE.md** | Quick start guide for RPi users |
| **run_setup.sh** | Auto-setup script (installs dependencies) |
| **run_test.sh** | Runs complete test suite |
| **vendor_stream_read.py** | USB vendor mode streaming tool |
| **.gitignore** | Excludes binaries and temp files |

---

## ✅ Current Sync Status

- ✅ Repository initialized
- ✅ First commit created
- ✅ Merged with GitHub repository
- ✅ All files synchronized
- ✅ Ready for RPi deployment

---

## 🔄 Synchronization

This folder is automatically synced with GitHub repository `bmi30-rpi`.

**To get latest firmware on RPi**:
```bash
cd bmi30-rpi
git pull
./run_setup.sh    # If setup changed
./run_test.sh     # Run tests
```

**To push updates from RPi**:
```bash
git add .
git commit -m "Description of changes"
git push
```

---

## 📌 Important Notes

- All scripts are tracked in Git
- Firmware files (.elf) are included (size ~2.5 MB)
- Python dependencies in `run_setup.sh`
- CI/CD can be added later if needed

---

## 🔗 Related Repositories

- **Main firmware**: https://github.com/kslabs/BMI30.stm32h7
- **RPI deployment**: https://github.com/kslabs/bmi30-rpi (this repo)

---

For more details, see `START_HERE.md` or `run_setup.sh`.
