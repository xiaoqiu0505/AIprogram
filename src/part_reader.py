# -*- coding: utf-8 -*-
"""
part_reader.py — 读取零件文件，提取几何信息用于预览
=====================================================
支持格式：
  · SolidWorks  .SLDPRT / .SLDASM
  · STEP        .step / .stp
  · IGES        .igs / .iges
  · STL         .stl（三角网格，可直接拿到点云）
  · 3MF         .3mf（zip 包，读内嵌 STL）

输出统一结构：
    {
        "path": 原始路径,
        "name": 文件名,
        "ext":  扩展名,
        "ok":   True/False,
        "error": 错误信息,
        "bbox": (w, h, d) 毫米,
        "volume_mm3": 体积,
        "faces": 面数,
        "triangles": 三角形列表 [(v0,v1,v2), ...]，用于 3D 渲染,
        "preview_png": 预览图路径（可选）,
    }

说明：
  · SLDPRT / STEP / IGES 通过 SolidWorks COM 读取（本机装了 SW）
  · STL 直接解析二进制文件，不需要 SolidWorks
  · 解析失败时返回 ok=False，界面上显示占位图
"""
import os
import struct
import math


# ==================== STL 解析（不需要 SolidWorks）====================
def read_stl(path):
    """
    解析 STL 文件，返回三角形列表。

    兼容：
      · 二进制 STL（80 字节头 + 4 字节数量 + 每面 50 字节）
      · ASCII STL（"solid" 开头，文本格式）
    """
    tris = []
    try:
        with open(path, "rb") as f:
            data = f.read()

        # 判断是 ASCII 还是二进制
        head = data[:80].lstrip()
        is_ascii = head[:5].lower() == b"solid"
        if is_ascii:
            # 有时二进制文件也以 solid 开头，用大小校验
            if len(data) > 84:
                n = struct.unpack("<I", data[80:84])[0]
                expect = 84 + n * 50
                if abs(len(data) - expect) < 100:
                    is_ascii = False

        if not is_ascii:
            if len(data) < 84:
                return tris
            n = struct.unpack("<I", data[80:84])[0]
            if n <= 0 or n > 5_000_000:
                return tris
            off = 84
            for _ in range(n):
                if off + 50 > len(data):
                    break
                # 法向(3) 顶点A(3) 顶点B(3) 顶点C(3) 属性(1) = 12 float + 2 byte
                vals = struct.unpack("<12fH", data[off:off + 50])
                v0 = (vals[3], vals[4], vals[5])
                v1 = (vals[6], vals[7], vals[8])
                v2 = (vals[9], vals[10], vals[11])
                tris.append((v0, v1, v2))
                off += 50
        else:
            # ASCII
            txt = data.decode("utf-8", errors="ignore")
            verts = []
            for line in txt.splitlines():
                line = line.strip()
                if line.lower().startswith("vertex"):
                    parts = line.split()
                    if len(parts) >= 4:
                        try:
                            verts.append((float(parts[1]),
                                          float(parts[2]),
                                          float(parts[3])))
                        except ValueError:
                            pass
            for i in range(0, len(verts) - 2, 3):
                tris.append((verts[i], verts[i + 1], verts[i + 2]))
    except Exception:
        pass
    return tris


def triangulate_obj(path):
    """简单 OBJ 解析（只取面）"""
    tris = []
    try:
        verts = []
        faces = []
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if line.startswith("v "):
                    p = line.split()
                    verts.append((float(p[1]), float(p[2]), float(p[3])))
                elif line.startswith("f "):
                    p = line.split()[1:]
                    idx = []
                    for tok in p:
                        n = int(tok.split("/")[0])
                        idx.append(n - 1 if n > 0 else len(verts) + n)
                    for i in range(1, len(idx) - 1):
                        faces.append((idx[0], idx[i], idx[i + 1]))
        for (a, b, c) in faces:
            if all(0 <= i < len(verts) for i in (a, b, c)):
                tris.append((verts[a], verts[b], verts[c]))
    except Exception:
        pass
    return tris


# ==================== 通过 SolidWorks 读取 ====================
def read_via_solidworks(path, log=None):
    """
    用 SolidWorks 打开文件并提取几何。

    返回: (bbox, volume_mm3, faces, tris) 或抛异常
    """
    import pythoncom
    import win32com.client

    # 本函数应在已 CoInitialize 的线程里调用

    sw = None
    try:
        sw = win32com.client.GetActiveObject("SldWorks.Application")
    except Exception:
        try:
            sw = win32com.client.Dispatch("SldWorks.Application")
        except Exception as e:
            raise RuntimeError(f"无法连接 SolidWorks：{e}")

    ext = os.path.splitext(path)[1].lower()

    # 扩展名 → SolidWorks 打开类型
    type_map = {
        ".sldprt": 1,
        ".sldasm": 2,
        ".step": 237, ".stp": 237,
        ".igs": 33, ".iges": 33,
        ".x_t": 12, ".x_b": 12,
        ".sat": 39,
        ".stl": 78,
    }
    dtype = type_map.get(ext, 1)

    doc = None
    try:
        doc = sw.OpenDoc6(path, dtype, 1, "", 0, 0)
    except Exception as e:
        # 老接口兜底
        try:
            doc = sw.OpenDoc(path, dtype)
        except Exception:
            raise RuntimeError(f"打开文件失败：{e}")

    if not doc:
        raise RuntimeError("SolidWorks 无法打开这个文件（格式不支持或版本过高）")

    try:
        bbox = None
        vol = 0.0
        nface = 0
        tris = []

        # 如果是装配体，先尝试取包围盒
        try:
            mp = doc.Extension.CreateMassProperty()
            vol = float(mp.Volume) * 1e9      # m³ → mm³
        except Exception:
            vol = 0.0

        # 取实体包围盒
        try:
            part = doc
            bodies = None
            try:
                bodies = part.GetBodies2(0, True)
            except Exception:
                # 装配体没有 GetBodies2，跳过
                bodies = None

            if bodies:
                xs, ys, zs = [], [], []
                for b in bodies:
                    try:
                        bb = b.GetBodyBox()
                        if bb:
                            xs += [bb[0], bb[3]]
                            ys += [bb[1], bb[4]]
                            zs += [bb[2], bb[5]]
                        nface += int(b.GetFaceCount())
                    except Exception:
                        pass
                if xs:
                    bbox = ((max(xs) - min(xs)) * 1000,
                            (max(ys) - min(ys)) * 1000,
                            (max(zs) - min(zs)) * 1000)
        except Exception:
            pass

        # 尝试导出 STL 拿三角面（用于 3D 渲染）
        try:
            tmp_stl = os.path.join(
                os.environ.get("TEMP", "."),
                f"_swprev_{abs(hash(path)) % 100000}.stl")
            # 设置 STL 输出
            doc.Extension.SetUserPreferenceInteger(78, 0, 1)   # 二进制
            doc.Extension.SetUserPreferenceDouble(2, 0, 0.1)   # 偏差
            ok = False
            try:
                ok = doc.SaveAs4(tmp_stl, 0, 1)
            except Exception:
                try:
                    ok = doc.SaveAs3(tmp_stl, 0, 1)
                except Exception:
                    ok = False
            if ok and os.path.exists(tmp_stl):
                tris = read_stl(tmp_stl)
                try:
                    os.remove(tmp_stl)
                except Exception:
                    pass
        except Exception:
            pass

        return bbox, vol, nface, tris
    finally:
        try:
            sw.CloseDoc(doc.GetTitle())
        except Exception:
            pass


# ==================== 统一入口 ====================
SUPPORTED_EXTS = {
    ".sldprt", ".sldasm",
    ".step", ".stp",
    ".igs", ".iges",
    ".x_t", ".x_b",
    ".sat",
    ".stl",
    ".obj",
}

MESH_EXTS = {".stl", ".obj"}


def read_part(path, log=None, need_mesh=True):
    """
    读取零件文件，返回统一结构。

    参数：
        path:      文件路径
        log:       日志回调 func(str)
        need_mesh: 是否需要三角网格（3D 渲染用）
    """
    def _log(msg):
        if log:
            try:
                log(msg)
            except Exception:
                pass

    result = {
        "path": path,
        "name": os.path.basename(path),
        "ext": os.path.splitext(path)[1].lower(),
        "ok": False,
        "error": "",
        "bbox": None,
        "volume_mm3": 0.0,
        "faces": 0,
        "triangles": [],
    }

    if not os.path.isfile(path):
        result["error"] = "文件不存在"
        return result

    if result["ext"] not in SUPPORTED_EXTS:
        result["error"] = f"不支持的格式 {result['ext']}"
        return result

    # ---- 网格格式：直接解析 ----
    if result["ext"] in MESH_EXTS:
        _log(f"  解析网格 {result['name']} …")
        if result["ext"] == ".stl":
            tris = read_stl(path)
        else:
            tris = triangulate_obj(path)

        if not tris:
            result["error"] = "解析失败（文件可能损坏或为空）"
            return result

        result["triangles"] = tris
        result["ok"] = True

        xs = [v[0] for t in tris for v in t]
        ys = [v[1] for t in tris for v in t]
        zs = [v[2] for t in tris for v in t]
        result["bbox"] = (max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))
        result["volume_mm3"] = _mesh_volume(tris)
        result["faces"] = len(tris)
        return result

    # ---- CAD 格式：走 SolidWorks ----
    _log(f"  用 SolidWorks 打开 {result['name']} …")
    try:
        bbox, vol, nface, tris = read_via_solidworks(path, log)
        result["bbox"] = bbox
        result["volume_mm3"] = vol
        result["faces"] = nface
        if need_mesh:
            result["triangles"] = tris
        result["ok"] = True
    except Exception as e:
        result["error"] = str(e)[:120]
        _log(f"  ✗ {result['error']}")

    return result


def _mesh_volume(tris):
    """用散度定理算三角网格体积（单位：与输入一致，STL 是 mm）"""
    v = 0.0
    for (a, b, c) in tris:
        v += (a[0] * (b[1] * c[2] - b[2] * c[1])
              - a[1] * (b[0] * c[2] - b[2] * c[0])
              + a[2] * (b[0] * c[1] - b[1] * c[0])) / 6.0
    return abs(v)


# ==================== 预览图生成 ====================
def make_preview_png(part, out_path, size=(200, 150), bg=(255, 255, 255)):
    """
    生成零件预览图（等轴测投影 + 简单光照）。

    参数：
        part:     read_part 的返回值
        out_path: 输出 PNG 路径
    """
    try:
        from PIL import Image, ImageDraw
    except Exception:
        return False

    tris = part.get("triangles") or []
    W, H = size
    img = Image.new("RGB", (W, H), bg)
    draw = ImageDraw.Draw(img)

    if not tris:
        # 没有网格：画一个带文件名的占位框
        draw.rectangle([2, 2, W - 3, H - 3], outline=(200, 205, 215))
        draw.text((10, H // 2 - 6), "无预览", fill=(150, 155, 165))
        img.save(out_path, "PNG")
        return True

    # 等轴测投影
    ca, sa = math.cos(math.radians(35.264)), math.sin(math.radians(35.264))
    cb, sb = math.cos(math.radians(45)), math.sin(math.radians(45))

    def proj(p):
        x, y, z = p
        # 绕 Y 转 45°，再绕 X 转 35.264°
        x1 = x * cb + z * sb
        z1 = -x * sb + z * cb
        y1 = y
        x2 = x1
        y2 = y1 * ca - z1 * sa
        return x2, y2

    pts2 = [proj(v) for t in tris for v in t]
    xs = [p[0] for p in pts2]
    ys = [p[1] for p in pts2]
    minx, maxx = min(xs), max(xs)
    miny, maxy = min(ys), max(ys)
    w = max(1e-6, maxx - minx)
    h = max(1e-6, maxy - miny)
    scale = min((W - 20) / w, (H - 20) / h)
    ox = (W - w * scale) / 2 - minx * scale
    oy = (H - h * scale) / 2 - miny * scale

    def to_screen(p):
        sx, sy = proj(p)
        return (sx * scale + ox, sy * scale + oy)

    # 按深度排序（远的先画）
    def depth(t):
        return sum(v[0] * sb * 0 + v[2] for v in t) / 3

    # 光照方向
    lx, ly, lz = 0.4, 0.7, 0.6
    ln = math.sqrt(lx * lx + ly * ly + lz * lz)
    lx, ly, lz = lx / ln, ly / ln, lz / ln

    order = sorted(tris, key=depth)
    base = (110, 135, 180)
    for (a, b, c) in order:
        # 法向
        ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
        vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
        nx = uy * vz - uz * vy
        ny = uz * vx - ux * vz
        nz = ux * vy - uy * vx
        nn = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
        nx, ny, nz = nx / nn, ny / nn, nz / nn

        lam = abs(nx * lx + ny * ly + nz * lz)
        shade = 0.35 + 0.65 * lam
        col = tuple(min(255, int(ch * shade)) for ch in base)

        try:
            draw.polygon([to_screen(a), to_screen(b), to_screen(c)],
                         fill=col, outline=None)
        except Exception:
            pass

    img.save(out_path, "PNG")
    return True
