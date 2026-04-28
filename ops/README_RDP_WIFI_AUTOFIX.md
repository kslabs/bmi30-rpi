# RDP + Wi-Fi Startup Autofix (BMI30)

This directory stores deployment artifacts for:
- XRDP startup auto-recovery with dependency healing.
- Startup-focused timer behavior (stops itself when RDP is healthy or when an active RDP session is present).
- Wi-Fi policy preferring `VinetaBMI 5GHz` and auto-escaping `VinetaBMI 2,4GHz`.

## Files

- `ops/scripts/bmi30-rdp-autofix.sh`
- `ops/systemd/bmi30-rdp-autofix.service`
- `ops/systemd/bmi30-rdp-autofix.timer`
- `ops/networkmanager/dispatcher.d/99-bmi30-prefer-vineta-5g.sh`

## Apply On Host

```bash
sudo install -m 0755 ops/scripts/bmi30-rdp-autofix.sh /usr/local/bin/bmi30-rdp-autofix.sh
sudo install -m 0644 ops/systemd/bmi30-rdp-autofix.service /etc/systemd/system/bmi30-rdp-autofix.service
sudo install -m 0644 ops/systemd/bmi30-rdp-autofix.timer /etc/systemd/system/bmi30-rdp-autofix.timer
sudo install -m 0755 ops/networkmanager/dispatcher.d/99-bmi30-prefer-vineta-5g.sh /etc/NetworkManager/dispatcher.d/99-bmi30-prefer-vineta-5g.sh

sudo systemctl daemon-reload
sudo systemctl enable --now bmi30-rdp-autofix.timer
sudo systemctl restart NetworkManager
```

## Wi-Fi profile policy

```bash
nmcli connection modify "VinetaBMI 5GHz" connection.autoconnect yes connection.autoconnect-priority 100 802-11-wireless.band a
nmcli connection modify "IOT configuration" connection.autoconnect no || true
nmcli connection modify "preconfigured" connection.autoconnect no || true
nmcli connection modify "VinetaBMI 2,4GHz" connection.autoconnect no || true
```
