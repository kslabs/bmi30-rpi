#!/usr/bin/env python3
import numpy as np
import sys

filepath = sys.argv[1] if len(sys.argv) > 1 else 'capture_1757501741.npz'
print(f"Loading: {filepath}")

data = np.load(filepath)
print(f"Keys: {list(data.keys())}")
print()
for key in list(data.keys())[:10]:
    arr = data[key]
    print(f"{key:20s} shape={str(arr.shape):20s} dtype={arr.dtype}")
