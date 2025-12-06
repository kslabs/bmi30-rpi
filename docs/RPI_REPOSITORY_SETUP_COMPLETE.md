# 📦 RPI Repository Setup Complete

## ✅ GitHub Integration for Raspberry Pi Deployment

Your Raspberry Pi deployment package is now fully synced with GitHub:

**Repository**: https://github.com/kslabs/bmi30-rpi  
**Status**: ✅ All files synchronized  
**Total Commits**: 3  
**Latest**: e9c95c0 (docs: Add Git setup guide for RPI deployment)  

---

## 📊 What's on GitHub (bmi30-rpi)

✅ **Deployment scripts** (run_setup.sh, run_test.sh)  
✅ **USB tools** (vendor_stream_read.py)  
✅ **Documentation** (START_HERE.md + RPI_GIT_SETUP.md)  
✅ **Firmware location** (firmware/ directory)  
✅ **.gitignore** (Python cache, temp files excluded)  

---

## 🚀 On Raspberry Pi - Quick Start

### 1. Clone repository

```bash
git clone https://github.com/kslabs/bmi30-rpi.git
cd bmi30-rpi
```

### 2. Setup environment

```bash
chmod +x run_setup.sh
./run_setup.sh
```

### 3. Get latest firmware

```bash
git pull
```

### 4. Run tests

```bash
chmod +x run_test.sh
./run_test.sh
```

---

## 💾 RPI Git Workflow

### Check what changed

```bash
git status
```

### Get latest from GitHub

```bash
git pull
```

### Update scripts (on RPi)

```bash
git add scripts/
git commit -m "Fix: Improved USB speed logging"
git push
```

### See history

```bash
git log --oneline -5
```

---

## 📋 Repository Structure

```
bmi30-rpi/
├── .gitignore                    ✅ Git ignore rules
├── .git/                         ✅ Git repository (3 commits)
├── START_HERE.md                 ✅ Quick start guide
├── RPI_GIT_SETUP.md              ✅ This guide
├── run_setup.sh                  ✅ Setup script
├── run_test.sh                   ✅ Test runner
├── scripts/
│   └── vendor_stream_read.py     ✅ USB streaming tool
└── firmware/                     ✅ For compiled ELF files
```

---

## 🔗 Two Linked Repositories

Now you have two synchronized Git repos:

| Repository | Purpose | URL |
|------------|---------|-----|
| **BMI30.stm32h7** | Main firmware source (Windows) | https://github.com/kslabs/BMI30.stm32h7 |
| **bmi30-rpi** | Deployment + testing (RPi) | https://github.com/kslabs/bmi30-rpi |

**Workflow**:
1. Develop on Windows → Commit to BMI30.stm32h7
2. Push firmware → Download on RPI_DEPLOY
3. Test on RPi → Clone bmi30-rpi
4. Updates → Git pull on both sides

---

## ✨ Benefits of This Setup

✅ **Automatic backups** on GitHub  
✅ **Version tracking** for all changes  
✅ **Easy RPi deployment** (just clone)  
✅ **Script sharing** (same tools on Windows + RPi)  
✅ **History preservation** (git log shows everything)  
✅ **Collaboration ready** (add team members anytime)  

---

## 🔐 Security

✅ No secrets in either repository  
✅ All Python scripts scanned  
✅ Safe to share GitHub URLs  

---

## 📚 Documentation Files

**In BMI30.stm32h7 repository**:
- GIT_CHEATSHEET.md — Daily commands
- QUICK_GIT_SETUP.md — 5-minute setup
- README_GIT_SETUP.md — Setup summary

**In bmi30-rpi repository**:
- RPI_GIT_SETUP.md — This guide
- START_HERE.md — RPi quick start

---

## 🎯 Next Steps

1. **Test on actual RPi** (git clone the bmi30-rpi repo)
2. **Run setup.sh** to install dependencies
3. **Execute tests** with run_test.sh
4. **Commit improvements** (git add + commit + push)
5. **Pull updates** when firmware changes on Windows

---

## 💡 Typical Workflow

**On Windows (BMI30.stm32h7 repo)**:
```powershell
# 1. Make changes to firmware
# 2. Build and test locally
git add .
git commit -m "Feature: New USB speed optimization"
git push
```

**Then on Raspberry Pi (bmi30-rpi repo)**:
```bash
# 1. Pull latest firmware
git pull

# 2. Copy new ELF file to RPI_DEPLOY/firmware/

# 3. Test with updated firmware
./run_test.sh

# 4. If you modify test scripts:
git add scripts/
git commit -m "Improve: Added diagnostic output to tests"
git push
```

**Back on Windows**:
```powershell
# Pull improvements from RPi team
cd .\RPI_DEPLOY\
git pull
```

---

## ✅ Verification

Check both repositories:

```bash
# On Windows
cd BMI30.stm32h7
git log --oneline -3

# For RPI deployment
cd RPI_DEPLOY
git log --oneline -3
```

Both should show commits on `main` branch.

---

**Status**: ✅ Two GitHub repositories fully synchronized and ready for collaborative development!

- **Main firmware**: https://github.com/kslabs/BMI30.stm32h7
- **RPI deployment**: https://github.com/kslabs/bmi30-rpi
