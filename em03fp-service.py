#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EM03 指纹驱动服务 v2 (桥接 deepin-authenticate ↔ 亚略特 OEM SDK 2024)
链路: D-Bus(com.deepin.test.VFingerprint) → libAraTrustFinger-em03.so
  - CaptureRawData  活帧采集(96x96@500)
  - ExtractFeature  活体模板(~16KB, 需先采集)
  - Verify(mode=1)  比对(同指~93分/异指0-2分, match出参)
模板: base64 存 /var/lib/em03fp/users/<uid>/<finger>.json
"""
import base64, ctypes, dbus, dbus.service, json, os, sys, threading, time

LIB = "/usr/lib/libAraTrustFinger-em03.so"
STORE = "/var/lib/em03fp"
W = H = 96
IMG_LEN = W * H
TPL_MIN = 10000        # 活体模板下限(基线存量298/活体16020)
ENROLL_STAGES = 5      # 录入按压次数
VERIFY_TIMEOUT = 18
CAP_UNIQ_MIN = 120     # 帧有效下限(未按压=全0xFF uniq=1)

libc = ctypes.CDLL("libc.so.6")
libc.calloc.restype = ctypes.c_void_p
libc.calloc.argtypes = [ctypes.c_size_t, ctypes.c_size_t]
libc.free.argtypes = [ctypes.c_void_p]

class SDK:
    def __init__(self):
        self.lib = ctypes.CDLL(LIB)
        f = self.lib.ARAFPSCAN_OpenDevice
        f.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_int]
        v = getattr(self.lib, "_Z16ARAFPSCAN_VerifyPviPhS0_PiS1_")
        v.argtypes = [ctypes.c_void_p, ctypes.c_int] + [ctypes.c_void_p]*4
        self._verify = v
        self.h = None
        self.lock = threading.Lock()

    def open(self):
        with self.lock:
            if self.h:
                return True
            self.lib.ARAFPSCAN_GlobalInit()
            self.lib.VFInitialize()
            h = ctypes.c_void_p(0)
            rc = self.lib.ARAFPSCAN_OpenDevice(ctypes.byref(h), ctypes.c_int(0))
            if rc != 0:
                return False
            self.h = h
            return True

    def close(self):
        with self.lock:
            if self.h:
                self.lib.ARAFPSCAN_CloseDevice(ctypes.byref(self.h))
                self.h = None

    def capture(self):
        with self.lock:
            if not self.h:
                raise RuntimeError("closed")
            buf = ctypes.create_string_buffer(20480)
            rc = self.lib.ARAFPSCAN_CaptureRawData(self.h, ctypes.c_int(0), buf)
            frame = buf.raw[:IMG_LEN]
            return len(set(frame)), frame

    def extract(self):
        with self.lock:
            if not self.h:
                raise RuntimeError("closed")
            p = ctypes.c_void_p(libc.calloc(1, 65536))
            try:
                rc = self.lib.ARAFPSCAN_ExtractFeature(self.h, ctypes.c_int(0), p)
                raw = ctypes.string_at(p, 65536)
                nz = len(raw.rstrip(b'\x00'))
                return rc == 0 and TPL_MIN < nz <= 65536, raw[:nz]
            finally:
                libc.free(p)

    def verify(self, a, b):
        with self.lock:
            if not self.h:
                raise RuntimeError("closed")
            pa = ctypes.c_void_p(libc.calloc(1, 65536))
            pb = ctypes.c_void_p(libc.calloc(1, 65536))
            s, m = ctypes.c_int(-9), ctypes.c_int(-9)
            try:
                ctypes.memmove(pa, bytes(a), len(a))
                ctypes.memmove(pb, bytes(b), len(b))
                rc = self._verify(self.h, ctypes.c_int(1), pa, pb,
                                  ctypes.cast(ctypes.byref(s), ctypes.c_void_p),
                                  ctypes.cast(ctypes.byref(m), ctypes.c_void_p))
                return (s.value if rc == 0 else -1), (m.value if rc == 0 else 0)
            finally:
                libc.free(pa); libc.free(pb)

def upath(uid):
    d = os.path.join(STORE, "users", uid)
    os.makedirs(d, exist_ok=True)
    return d

def save(uid, finger, tpls):
    p = os.path.join(upath(uid), finger + ".json")
    with open(p, "w") as f:
        json.dump({"tpls": [base64.b64encode(t).decode() for t in tpls]}, f)
    os.chmod(p, 0o600)

def load(uid, finger):
    p = os.path.join(upath(uid), finger + ".json")
    if not os.path.exists(p):
        return []
    with open(p) as f:
        return [base64.b64decode(x) for x in json.load(f).get("tpls", [])]

def fingers(uid):
    d = upath(uid)
    return [fn[:-5] for fn in os.listdir(d) if fn.endswith(".json")]

def delete(uid, finger):
    p = os.path.join(upath(uid), finger + ".json")
    if os.path.exists(p):
        os.unlink(p)

IFACE = "com.deepin.test.VFingerprint"
PATH = "/com/deepin/test/VFingerprint"

class FpService(dbus.service.Object):
    def __init__(self, bus, sdk):
        self.sdk = sdk
        self.user = None
        self.stop = threading.Event()
        self.workers = []
        dbus.service.Object.__init__(self, bus, PATH)

    @dbus.service.method("org.freedesktop.DBus.Properties",
                         in_signature="ss", out_signature="v")
    def Get(self, iface, prop):
        vals = {"Name": dbus.String("vdevice"), "State": dbus.Int32(1),
                "Type": dbus.Int32(1), "Capability": dbus.Int32(1)}
        return vals.get(prop, dbus.String(""))

    @dbus.service.method("org.freedesktop.DBus.Properties",
                         in_signature="s", out_signature="a{sv}")
    def GetAll(self, iface):
        return {"Name": dbus.String("vdevice"), "State": dbus.Int32(1),
                "Type": dbus.Int32(1), "Capability": dbus.Int32(1)}

    @dbus.service.method("org.freedesktop.DBus.Properties", in_signature="ssv")
    def Set(self, i, p, v):
        pass

    @dbus.service.method(IFACE, in_signature="sb")
    def Claim(self, uid, claimed):
        print("[Claim] %s %s" % (uid, claimed), flush=True)
        if claimed:
            self.user = str(uid)
            self.stop.clear()
            if not self.sdk.open():
                raise dbus.DBusException("open device failed")
        else:
            self.user = None
            self.stop.set()

    @dbus.service.method(IFACE, in_signature="ss")
    def Enroll(self, userId, finger):
        uid, fg = str(userId), str(finger)
        print("[Enroll] %s %s" % (uid, fg), flush=True)
        self.stop.clear()
        t = threading.Thread(target=self._enroll, args=(uid, fg))
        t.daemon = True
        t.start()
        self.workers.append(t)

    @dbus.service.method(IFACE)
    def StopEnroll(self):
        self.stop.set()

    def _wait_press(self):
        sess = self.user or "unknown"
        while not self.stop.is_set():
            try:
                uniq, _ = self.sdk.capture()
                if uniq < CAP_UNIQ_MIN:
                    time.sleep(0.15)
                    continue
                # 手指按下 → 发射 Touch(true) 驱动向导进度
                self.Touch(sess, dbus.Boolean(True))
                ok, tpl = self.sdk.extract()
                if ok:
                    self._wait_release()
                    return tpl
                # 采集/提取失败也发Touch(false)让向导复位
                self.Touch(sess, dbus.Boolean(False))
            except Exception as e:
                print("[worker] cap/extract: %s" % e, flush=True)
                self.sdk.close()
                time.sleep(0.5)
                self.sdk.open()
            time.sleep(0.15)
        return None

    def _wait_release(self):
        """等待手指离开并发射 Touch(false)"""
        sess = self.user or "unknown"
        t0 = time.time()
        while time.time() - t0 < 5 and not self.stop.is_set():
            try:
                uniq, _ = self.sdk.capture()
                if uniq < CAP_UNIQ_MIN:
                    print("[Enroll] 手指已抬起", flush=True)
                    self.Touch(sess, dbus.Boolean(False))
                    return
            except Exception:
                pass
            time.sleep(0.2)
        print("[Enroll] 等待抬起超时", flush=True)
        self.Touch(sess, dbus.Boolean(False))

    def _enroll(self, uid, fg):
        got = []
        sess = uid
        t0 = time.time()
        while len(got) < ENROLL_STAGES and time.time() - t0 < 90 \
                and not self.stop.is_set():
            tpl = self._wait_press()
            if tpl:
                got.append(tpl)
                # 协议(逆向确认): code=2 + 非空msg → 进度条平滑递增
                prog = min(99, int(len(got) * 100.0 / ENROLL_STAGES))
                if len(got) < ENROLL_STAGES:
                    self.EnrollStatus(sess, dbus.Int32(2),
                                      '{"progress": %d}' % prog)
                print("[Enroll] 采集%d/%d prog=%d" % (len(got), ENROLL_STAGES, prog), flush=True)
                if len(got) < ENROLL_STAGES:
                    print("[Enroll] 提示: 请调整手指角度再按(第%d次)" % (len(got)+1), flush=True)
        if len(got) >= ENROLL_STAGES:
            save(uid, fg, got)
            print("[Enroll] 已保存 %d 模板" % len(got), flush=True)
            self.EnrollStatus(sess, dbus.Int32(0), '{"progress": 100}')
        else:
            self.EnrollStatus(sess, dbus.Int32(3), "scan failed")

    @dbus.service.signal(IFACE, signature="sis")
    def EnrollStatus(self, i, c, m):
        pass

    @dbus.service.signal(IFACE, signature="sb")
    def Touch(self, i, p):
        pass

    @dbus.service.method(IFACE, in_signature="s")
    def Verify(self, finger):
        print("[Verify] %s" % finger, flush=True)
        self.stop.clear()
        t = threading.Thread(target=self._verify, args=(self.user, str(finger)))
        t.daemon = True
        t.start()
        self.workers.append(t)

    @dbus.service.method(IFACE)
    def StopVerify(self):
        self.stop.set()

    @dbus.service.method(IFACE)
    def SetStopVerify(self):
        self.stop.set()

    def _verify(self, uid, fg):
        sess = uid or "unknown"
        if fg == "any" and uid:
            refs = []
            for fn in fingers(uid):
                refs.extend(load(uid, fn))
            print("[Verify any] 加载全部%d个模板(来自%d个指纹)" % (len(refs), len(fingers(uid))), flush=True)
        else:
            refs = load(uid, fg) if uid else []
        print("[Verify] 参考模板 %d 个" % len(refs), flush=True)
        t0 = time.time()
        fail_streak = 0  # 连续低分帧计数
        FAIL_LIMIT = 3   # 连续3帧低于阈值 → 立即报失败
        while time.time() - t0 < VERIFY_TIMEOUT and not self.stop.is_set():
            try:
                uniq, _ = self.sdk.capture()
                if uniq < CAP_UNIQ_MIN:
                    time.sleep(0.15)
                    continue
                ok, tpl = self.sdk.extract()
            except Exception as e:
                print("[Verify] %s" % e, flush=True)
                self.sdk.close(); time.sleep(0.5); self.sdk.open()
                continue
            # 验证也发Touch事件(驱动锁屏的指纹动画)
            if ok:
                self.Touch(sess, dbus.Boolean(True))
                self.Touch(sess, dbus.Boolean(False))
            if not ok:
                time.sleep(0.15)
                continue
            best = -1
            for ref in refs:
                s, m = self.sdk.verify(tpl, ref)
                best = max(best, s)
                if m == 1 or s >= 60:
                    print("[Verify] 匹配 score=%d" % s, flush=True)
                    self.VerifyStatus(sess, dbus.Int32(0), "verify-match")
                    return
            # 有效帧但低于阈值 → 计入失败连击
            fail_streak += 1
            print("[Verify] 帧得分=%d 连续失败%d/%d" % (best, fail_streak, FAIL_LIMIT), flush=True)
            if fail_streak >= FAIL_LIMIT:
                print("[Verify] 连续%d帧低分, 判定不匹配" % fail_streak, flush=True)
                self.VerifyStatus(sess, dbus.Int32(1), "verify-no-match")
                return
            time.sleep(0.2)
        self.VerifyStatus(sess, dbus.Int32(1), "verify-no-match")

    @dbus.service.signal(IFACE, signature="sis")
    def VerifyStatus(self, i, c, m):
        pass

    @dbus.service.signal(IFACE)
    def SetStopVerifySig(self):
        pass

    @dbus.service.method(IFACE, in_signature="s", out_signature="as")
    def ListFingers(self, uid):
        return fingers(str(uid))

    @dbus.service.method(IFACE, in_signature="ss")
    def DeleteFinger(self, uid, fg):
        delete(str(uid), str(fg))

    @dbus.service.method(IFACE, in_signature="s")
    def DeleteAllFingers(self, uid):
        for x in fingers(str(uid)):
            delete(str(uid), x)

    @dbus.service.method(IFACE, in_signature="sss")
    def RenameFinger(self, uid, old, new):
        t = load(str(uid), str(old))
        if t:
            delete(str(uid), str(old))
            save(str(uid), str(new), t)

def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--selftest":
        sdk = SDK()
        print("open:", sdk.open())
        uniq, _ = sdk.capture()
        print("capture uniq:", uniq)
        ok, tpl = sdk.extract()
        print("extract ok=%s len=%d" % (ok, len(tpl)))
        sdk.close()
        return
    from dbus.mainloop.glib import DBusGMainLoop
    from gi.repository import GLib
    DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()
    global _bus_name
    _bus_name = dbus.service.BusName(IFACE, bus)  # 必须持引用, 否则GC释放总线名
    FpService(bus, SDK())
    print("EM03 v2 service ready (com.deepin.test.VFingerprint)", flush=True)
    GLib.MainLoop().run()

if __name__ == "__main__":
    main()
