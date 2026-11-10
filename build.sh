#!/bin/bash
# Build em03fp-driver deb package
set -e
cd "$(dirname "$0")"

PKG=em03fp-deploy
rm -rf $PKG em03fp-driver_1.0.0_amd64.deb

mkdir -p $PKG/DEBIAN
mkdir -p $PKG/usr/local/bin
mkdir -p $PKG/usr/lib
mkdir -p $PKG/usr/share/dbus-1/system-services
mkdir -p $PKG/usr/share/dbus-1/system.d
mkdir -p $PKG/usr/share/deepin-authentication/interfaces

cat > $PKG/DEBIAN/control << 'EOF'
Package: em03fp-driver
Version: 1.0.0
Architecture: amd64
Maintainer: community <em03@community>
Depends: python3, python3-dbus, python3-gi, libusb-1.0-0
Conflicts: com.aratek.fp.driver
Replaces: com.aratek.fp.driver
Provides: com.aratek.fp.driver
Section: utils
Priority: optional
Description: Aratek EM03 fingerprint driver for Lenovo KaiTian N80z G2e
 Bridge service connecting the Aratek EM03 fingerprint module (USB 28ED:2031)
 to the deepin-authenticate framework on UOS 20.
 .
 Hardware: Lenovo KaiTian N80z G2e (N8 Pro), Aratek EM03 sensor
 Supported OS: UOS 20 Professional (1070/eagle) amd64
EOF

cat > $PKG/DEBIAN/postinst << 'POST'
#!/bin/bash
set -e
mkdir -p /var/lib/em03fp/users
chmod 700 /var/lib/em03fp
pkill -f em03fp-service 2>/dev/null || true
pkill -x vfingerprint-service 2>/dev/null || true
sleep 1
nohup /usr/local/bin/em03fp-service > /var/log/em03fp.log 2>&1 &
sleep 2
systemctl restart deepin-authenticate 2>/dev/null || true
echo ""
echo "EM03 fingerprint driver installed."
echo "Enroll via: Control Center -> Account -> Fingerprint"
exit 0
POST
chmod 755 $PKG/DEBIAN/postinst

cat > $PKG/DEBIAN/prerm << 'PRE'
#!/bin/bash
pkill -f em03fp-service 2>/dev/null || true
systemctl restart deepin-authenticate 2>/dev/null || true
exit 0
PRE
chmod 755 $PKG/DEBIAN/prerm

cp em03fp-service.py $PKG/usr/local/bin/em03fp-service
chmod 755 $PKG/usr/local/bin/em03fp-service
cp libAraTrustFinger-em03.so $PKG/usr/lib/
chmod 644 $PKG/usr/lib/libAraTrustFinger-em03.so

cat > $PKG/usr/share/dbus-1/system-services/com.deepin.test.VFingerprint.service << 'EOF'
[D-BUS Service]
Name=com.deepin.test.VFingerprint
Exec=/usr/local/bin/em03fp-service
User=root
EOF

cat > $PKG/usr/share/dbus-1/system.d/com.deepin.test.VFingerprint.conf << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE busconfig PUBLIC
 "-//freedesktop//DTD D-BUS Bus Configuration 1.0//EN"
 "http://www.freedesktop.org/standards/dbus/1.0/busconfig.dtd">
<busconfig>
  <policy user="root">
    <allow own="com.deepin.test.VFingerprint"/>
  </policy>
  <policy context="default">
    <allow send_destination="com.deepin.test.VFingerprint"/>
  </policy>
</busconfig>
EOF

cat > $PKG/usr/share/deepin-authentication/interfaces/vfAdaptation.conf << 'EOF'
{
    "service": "com.deepin.test.VFingerprint",
    "path": "/com/deepin/test/VFingerprint",
    "interface": "com.deepin.test.VFingerprint",
    "type": 1,
    "storage_type": 1
}
EOF

dpkg-deb --build $PKG em03fp-driver_1.0.0_amd64.deb
rm -rf $PKG
echo "Built: $(ls -lh em03fp-driver_1.0.0_amd64.deb | awk '{print $5, $NF}')"
