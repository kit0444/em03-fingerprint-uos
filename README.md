# EM03 Fingerprint Driver (UOS)

Fingerprint driver for the **Aratek EM03** sensor (USB `28ED:2031`) found in
**Lenovo KaiTian N80z G2e (N8 Pro)** laptops, for **UOS 20 Professional** only.

> **This is NOT a general-purpose Linux fingerprint driver.** It only works
> with the UOS `deepin-authenticate` framework and the specific
> hardware configuration of this laptop model.

## Background

This laptop ships with a broken fingerprint setup on UOS: the pre-installed
driver from UOS repos is a 2022 build that doesn't recognize the newer EM03
module. The matching driver only exists in Kylin OS OEM repositories, which
are not accessible from UOS.

## AI-Generated Driver — Read Before Using

**The entire reverse engineering and driver implementation was performed by
an AI assistant .** No human driver developer was involved.

What this means for you:

- The protocol was reverse engineered from binary disassembly — there may be
  errors or edge cases not covered
- The D-Bus signal codes were determined by analyzing framework binaries,
  not from official documentation
- The SDK library is a closed-source proprietary binary extracted from a
  Kylin OS factory image — its exact behavior is not fully understood
- **Use at your own risk.** While it has been tested working on the author's
  machine, there is no warranty, no guarantee of correctness, and no support

If something breaks, you get to keep both pieces.

## What This Does

```
Control Center / Lock Screen (UOS native)
  └── deepin-authenticate framework (UOS native)
      └── em03fp-service (this project, Python)
          └── libAraTrustFinger-em03.so (Aratek 2024 OEM SDK, closed source)
              └── EM03 fingerprint sensor (USB 28ED:2031)
```

The Python bridge service (`em03fp-service.py`, ~350 lines) translates between
UOS's D-Bus authentication framework and the vendor SDK library.

## Install

```bash
sudo dpkg -i em03fp-driver_1.0.0_amd64.deb
```

The old broken driver (if present) is automatically replaced. Go to
**Control Center → Account → Fingerprint** to enroll.

## Prerequisites

| Requirement | Value |
|---|---|
| Laptop model | Lenovo KaiTian N80z G2e (N8 Pro) |
| Fingerprint sensor | Aratek EM03 (check: `lsusb \| grep 28ed` shows `28ed:2031`) |
| OS | UOS 20 Professional (1070/eagle), amd64 |
| Python | python3 + python3-dbus + python3-gi (UOS 20 default) |

## Features

- Fingerprint enrollment (5 presses, angle guidance)
- Lock screen fingerprint unlock
- Wrong fingerprint rejection (~2s)
- Enrollment progress bar
- Auto-start on boot (D-Bus activation)
- Templates persist across driver reinstall

## Technical Details

### Protocol (reverse engineered)

| Layer | Details |
|---|---|
| USB frame | `FF AA [cmd] [addr16] [param16] [pad×3] [XOR]` |
| Commands | `0x00/0x0CF0` init, `0x00/0x0C90` arm, `0x68/0x010A` capture |
| Sensor | 96×96 @500dpi, 9216 bytes per frame |
| Auth | Session handshake inside SDK (closed source, not bypassed) |
| Template | PRECISE format, ~16KB per finger |
| Matching | Host-side, score ≥60 = match (same finger ~93, different ≤16) |

### D-Bus signals (reverse engineered)

| Action | Signal | Notes |
|---|---|---|
| Stage pass | `code=2, msg='{"progress": N}'` | Progress bar advances |
| Enroll done | `code=0, msg='{"progress": 100}'` | Wizard shows success |
| Duplicate | `code=2, msg=''` | Empty msg = duplicate |
| Verify match | `code=0` | Lock screen unlocks |
| Verify fail | `code=1` | After 3 consecutive low-score frames |

## Files

| File | Description |
|---|---|
| `em03fp-service.py` | Bridge service source code |
| `libAraTrustFinger-em03.so` | Aratek 2024 OEM SDK library (closed source) |
| `em03fp-driver_1.0.0_amd64.deb` | Pre-built installation package |
| `build.sh` | Rebuild the .deb from source files |

## About the SDK Library

`libAraTrustFinger-em03.so` is a proprietary binary from Aratek Biometrics
Technology Co., Ltd. It was originally distributed inside Kylin OS OEM driver
packages (`biometric-driver-aratek-trustfinger-common 0.1.19.1`). It is
included here solely for hardware interoperability. All rights to this
library belong to its respective owner.
