# -*- coding: utf-8 -*-
"""
sw_builder.py — SolidWorks 自动建模
=====================================
把 AI 返回的 JSON 描述转换成实际的 SolidWorks 零件。

关键实现要点（都是实测踩出来的）：
  - 必须用 makepy 生成静态 COM 绑定，否则参数传递会失败
  - 类型库 spec 必须是 4 元组 (guid, lcid, major, minor)
  - 选边/选面要用原始 CDispatch 的 Select()，不能用包装后的对象
  - 保存用 SaveAs3(path, 0, 1) 静默保存，避免弹框
"""
import math
import os
import time
import glob
import importlib
import sys

MM = 0.001   # mm -> m

# ---- API 常量 ----
SAVE_SILENT = 1
swStartSketchPlane = 0      # T0: 从草图平面开始
swStartSurface = 1          # T0: 从曲面开始
swStartVertex = 2           # T0: 从顶点开始
swStartOffset = 3           # T0: 从草图平面偏移开始
swEndCondBlind = 0          # 给定深度
swEndCondThroughAll = 1     # 完全贯穿
swEndCondThroughNext = 2    # 成形到下一面
swEndCondUpToVertex = 3     # 成形到顶点
swEndCondUpToSurface = 4    # 成形到一面
swEndCondOffsetFromSurface = 5   # 成形到一面并偏移
swEndCondMidPlane = 6       # 两侧对称
swEndCondUpToBody = 7       # 成形到实体
FILLET_OPTS_UNIFORM = 2
FILLET_TYPE_SIMPLE = 0
CHAMFER_ANGLE_DIST = 1
CHAMFER_EQUAL_DIST = 16

FOLDER_TYPES = {
    "FavoriteFolder", "HistoryFolder", "SelectionSetFolder", "SensorFolder",
    "DocsFolder", "DetailCabinet", "InkMarkupFolder", "EnvFolder",
    "SolidBodyFolder", "SurfaceBodyFolder", "CommentsFolder",
    "EqnFolder", "MaterialFolder", "OriginProfileFeature", "ConfigTableFolder",
    "RefPlane",
}


class BuildError(Exception):
    pass


class SolidWorksBuilder:
    """SolidWorks 建模器"""

    def __init__(self, template_path=None, log_func=print):
        self.log = log_func
        self.mod = None
        self.sw = None
        self.doc = None
        self.template = template_path or self._find_template()

    # ---------------- COM 绑定 ----------------
    @staticmethod
    def _find_template():
        """找国标零件模板"""
        candidates = []
        for base in [r"C:\ProgramData\SOLIDWORKS", r"D:\SOLIDWORKS",
                     r"C:\Program Files\SOLIDWORKS Corp"]:
            if os.path.isdir(base):
                candidates += glob.glob(
                    os.path.join(base, "**", "gb_part.prtdot"), recursive=True)
                candidates += glob.glob(
                    os.path.join(base, "**", "*.prtdot"), recursive=True)
        # 排除 MBD 模板
        candidates = [c for c in candidates if "MBD" not in c]
        return candidates[0] if candidates else None

    def connect(self):
        """
        连接 SolidWorks（生成静态绑定）。

        注意：SolidWorks COM 接口在工作线程中调用前，
        必须先调用 CoInitialize。这里统一处理，避免
        「尚未调用 CoInitialize」错误。
        """
        import pythoncom

        # ---- 关键：初始化当前线程的 COM 环境 ----
        # 主线程通常已由 tkinter 初始化，子线程必须自己 init。
        self._com_initialized = False
        try:
            pythoncom.CoInitialize()
            self._com_initialized = True
        except Exception:
            # 已经初始化过（返回 S_FALSE 或 RPC_E_CHANGED_MODE）也可以继续
            self._com_initialized = True

        from win32com.client import makepy
        import win32com
        import win32com.client

        # 找 SolidWorks 安装的 tlb
        tlb = None
        for p in [r"D:\SOLIDWORKS\sldworks.tlb", r"C:\Program Files\SolidWorks Corp\sldworks.tlb"]:
            if os.path.exists(p):
                tlb = p
                break
        if not tlb:
            hits = glob.glob(r"D:\**\sldworks.tlb", recursive=False)
            hits += glob.glob(r"C:\Program Files\**\sldworks.tlb", recursive=False)
            tlb = hits[0] if hits else None
        if not tlb:
            raise BuildError("未找到 SolidWorks 类型库 sldworks.tlb，请确认已安装 SolidWorks")

        # 生成静态绑定
        try:
            lib = pythoncom.LoadTypeLib(tlb)
            gi, lcid, _sk, major, minor, _fl = lib.GetLibAttr()
            spec = (str(gi), lcid, major, minor)   # 必须是 4 元组！
            makepy.GenerateFromTypeLibSpec(spec, verboseLevel=0, bForDemand=False)
        except Exception as e:
            self.log(f"  类型库绑定警告: {e}")

        genp = win32com.__gen_path__
        cands = glob.glob(os.path.join(genp, "*.py"))

        # 打包后：gen_py 被放到 sys._MEIPASS/gen_py，需加进搜索路径
        if getattr(sys, "frozen", False):
            meipass = getattr(sys, "_MEIPASS", "")
            bundled = os.path.join(meipass, "gen_py")
            if os.path.isdir(bundled):
                if bundled not in sys.path:
                    sys.path.insert(0, bundled)
                cands = glob.glob(os.path.join(bundled, "*.py")) + cands
            # 捆绑目录下的 .py 可能被压缩，也尝试直接导入
            try:
                if os.path.dirname(genp) not in sys.path:
                    sys.path.insert(0, os.path.dirname(genp))
            except Exception:
                pass

        sld_mod = None
        for c in cands:
            try:
                name = os.path.splitext(os.path.basename(c))[0]
                d = os.path.dirname(c)
                if d not in sys.path:
                    sys.path.insert(0, d)
                m = importlib.import_module(name)
                if hasattr(m, "ISldWorks"):
                    sld_mod = m
                    break
            except Exception:
                continue
        if sld_mod is None:
            raise BuildError("无法加载 SolidWorks COM 绑定")

        self.mod = sld_mod

        # 连接
        try:
            raw = win32com.client.GetActiveObject("SldWorks.Application")
        except Exception:
            # 没开就启动
            raw = win32com.client.Dispatch("SldWorks.Application")
            time.sleep(3)
        self.sw = sld_mod.ISldWorks(raw._oleobj_)
        self.log(f"  已连接 SolidWorks {self.sw.RevisionNumber()}")

    # ---------------- 工具函数 ----------------
    def _features(self):
        out, f, n = [], self.doc.FirstFeature(), 0
        while f is not None and n < 400:
            ff = self.wrap(f, "IFeature")
            try:
                out.append((ff.Name, ff.GetTypeName2(), ff, f))
            except Exception:
                break
            try:
                f = ff.GetNextFeature()
            except Exception:
                break
            n += 1
        return out

    def wrap(self, obj, hint=None):
        """把 CDispatch 包装成静态接口"""
        if obj is None:
            return None
        tname = type(obj).__name__
        if tname.startswith("I") and len(tname) > 1 and tname[1].isupper():
            return obj
        try:
            ole = obj._oleobj_
        except AttributeError:
            return obj
        names = ([hint] if hint else []) + [
            "IModelDoc2", "IFeatureManager", "ISketchManager", "IModelDocExtension",
            "ISelectionManager", "IFeature", "ISketch", "IMassProperty",
            "IBody2", "IPartDoc", "IModelView", "IFace2", "IEdge", "IVertex",
            "ISurface", "ICurve",
        ]
        for nm in names:
            cls = getattr(self.mod, nm, None)
            if cls is None:
                continue
            try:
                return cls(ole)
            except Exception:
                continue
        return obj

    def _new_part(self):
        """新建零件"""
        # 关闭已有文档
        docs = self.sw.GetDocuments()
        if docs:
            for d in list(docs):
                try:
                    self.sw.CloseDoc(d.GetTitle())
                except Exception:
                    pass
        tpl = self.template
        self.sw.NewDocument(tpl, 0, 0, 0)
        self.doc = self.mod.IModelDoc2(self.sw.ActiveDoc._oleobj_)
        self.ext = self.doc.Extension
        self.fm = self.doc.FeatureManager
        self.skm = self.doc.SketchManager
        self.log(f"  新建零件: {self.doc.GetTitle()}")

    def _select_plane(self, plane="front"):
        """选基准面"""
        name_map = {"front": "前视基准面", "top": "上视基准面", "right": "右视基准面"}
        target = name_map.get(plane, "前视基准面")
        for nm, tp, feat, raw in self._features():
            if tp == "RefPlane" and nm == target:
                self.doc.ClearSelection2(True)
                if feat.Select2(False, 0):
                    return True
                return False
        return False

    def _vol_mm3(self):
        return self.ext.CreateMassProperty().Volume * 1e9

    def _circular_edges(self):
        """返回 [(x, y, z, radius, raw_edge)]"""
        part = self.mod.IPartDoc(self.doc._oleobj_)
        bodies = part.GetBodies2(0, True)
        if not bodies:
            return []
        body = self.mod.IBody2(bodies[0]._oleobj_)
        out = []
        for e in body.GetEdges():
            edge = self.mod.IEdge(e._oleobj_)
            try:
                cv = edge.GetCurve()
                if not cv:
                    continue
                icv = self.mod.ICurve(cv._oleobj_)
                if not icv.IsCircle():
                    continue
                cx, cy, cz, nx, ny, nz, rad = icv.CircleParams
                out.append((cx, cy, cz, rad, e))
            except Exception:
                continue
        return out

    def _line_edges(self):
        """返回 [(p1, p2, raw_edge)] 直线边"""
        part = self.mod.IPartDoc(self.doc._oleobj_)
        bodies = part.GetBodies2(0, True)
        if not bodies:
            return []
        body = self.mod.IBody2(bodies[0]._oleobj_)
        out = []
        for e in body.GetEdges():
            edge = self.mod.IEdge(e._oleobj_)
            try:
                cv = edge.GetCurve()
                if not cv:
                    continue
                icv = self.mod.ICurve(cv._oleobj_)
                if icv.IsCircle():
                    continue
                v1 = edge.GetStartVertex()
                v2 = edge.GetEndVertex()
                if not v1 or not v2:
                    continue
                p1 = self.mod.IVertex(v1._oleobj_).GetPoint()
                p2 = self.mod.IVertex(v2._oleobj_).GetPoint()
                out.append((p1, p2, e))
            except Exception:
                continue
        return out

    @staticmethod
    def _sel(raw):
        """选边/面：必须用原始 CDispatch 的 Select"""
        try:
            return bool(raw.Select(True))
        except Exception:
            try:
                return bool(raw.Select2(True, 0))
            except Exception:
                return False

    # ---------------- 草图 ----------------
    def _draw_sketch(self, sketch_def):
        """在草图里画图形"""
        shape = sketch_def.get("shape", "rectangle").lower()
        p = sketch_def.get("params", {})

        cx = float(p.get("center_x", 0)) * MM
        cy = float(p.get("center_y", 0)) * MM

        if shape == "rectangle":
            w = float(p["width"]) * MM
            h = float(p["height"]) * MM
            hw, hh = w / 2, h / 2
            pts = [(cx - hw, cy - hh), (cx + hw, cy - hh),
                   (cx + hw, cy + hh), (cx - hw, cy + hh)]
            for i in range(4):
                x1, y1 = pts[i]
                x2, y2 = pts[(i + 1) % 4]
                self.skm.CreateLine(x1, y1, 0.0, x2, y2, 0.0)
            return f"矩形 {p['width']}×{p['height']}mm"

        elif shape == "circle":
            r = float(p["radius"]) * MM
            self.skm.CreateCircleByRadius(cx, cy, 0.0, r)
            return f"圆 φ{float(p['radius'])*2:.2f}mm"

        elif shape == "polygon":
            sides = int(p.get("sides", 6))
            # 支持外接圆半径 或 对边宽度
            if "circumradius" in p:
                R = float(p["circumradius"]) * MM
            elif "across_flats" in p:
                R = (float(p["across_flats"]) / 2) / math.cos(math.radians(30)) * MM
            else:
                raise BuildError("多边形需要 circumradius 或 across_flats 参数")
            start_angle = float(p.get("start_angle", 30))
            pts = []
            for i in range(sides):
                a = math.radians(start_angle + 360.0 / sides * i)
                pts.append((cx + R * math.cos(a), cy + R * math.sin(a)))
            for i in range(sides):
                x1, y1 = pts[i]
                x2, y2 = pts[(i + 1) % sides]
                self.skm.CreateLine(x1, y1, 0.0, x2, y2, 0.0)
            return f"{sides}边形 (外接圆R{R/MM:.2f}mm)"

        elif shape == "profile":
            prof = p.get("profile", [])
            if len(prof) < 3:
                raise BuildError("profile 轮廓至少需要 3 个点")
            pts = [(float(x) * MM, float(y) * MM) for x, y in prof]
            for i in range(len(pts)):
                x1, y1 = pts[i]
                x2, y2 = pts[(i + 1) % len(pts)]
                self.skm.CreateLine(x1, y1, 0.0, x2, y2, 0.0)
            return f"轮廓 {len(pts)} 点"

        raise BuildError(f"不支持的图形: {shape}")

    # ---------------- 表面偏移计算 ----------------
    def _surface_offset(self, plane, flip=False):
        """
        计算从草图平面到零件表面的距离（沿切削方向）。

        草图平面（front/top/right）都通过原点：
          · front = XY 平面，切削沿 ±Z
          · top   = XZ 平面，切削沿 ±Y
          · right = YZ 平面，切削沿 ±X

        零件居中于原点时，表面到原点的距离 = 该方向半尺寸。
        """
        try:
            part = self.mod.IPartDoc(self.doc._oleobj_)
            bodies = part.GetBodies2(0, True)
            if not bodies:
                return 0.0
            body = self.mod.IBody2(bodies[0]._oleobj_)
            box = body.GetBodyBox()
            if not box:
                return 0.0
            xmin, ymin, zmin, xmax, ymax, zmax = box

            plane = (plane or "front").lower()

            if plane == "front":
                v = zmax if not flip else abs(zmin)
            elif plane == "top":
                v = ymax if not flip else abs(ymin)
            elif plane == "right":
                v = xmax if not flip else abs(xmin)
            elif plane == "back":
                v = abs(zmin) if not flip else zmax
            elif plane == "bottom":
                v = abs(ymin) if not flip else ymax
            else:
                v = zmax

            return max(0.0, v)
        except Exception:
            return 0.0

    def _find_face_by_normal(self, axis, positive=True):
        """
        按法向找零件表面。

        参数：
            axis: "x" | "y" | "z"
            positive: True 找正向面（如 Y=+50），False 找负向面（Y=-50）

        返回：原始 CDispatch（可用于 Select），找不到返回 None
        """
        try:
            part = self.mod.IPartDoc(self.doc._oleobj_)
            bodies = part.GetBodies2(0, True)
            if not bodies:
                return None
            body = self.mod.IBody2(bodies[0]._oleobj_)

            # 该方向的极值
            box = body.GetBodyBox()
            if not box:
                return None
            lim = {
                "x": (box[3], box[0]),
                "y": (box[4], box[1]),
                "z": (box[5], box[2]),
            }[axis.lower()]
            target = lim[0] if positive else lim[1]

            idx = {"x": 0, "y": 1, "z": 2}[axis.lower()]
            best = None
            for fc in (body.GetFaces() or []):
                face = self.mod.IFace2(fc._oleobj_)
                try:
                    surf = self.mod.ISurface(face.GetSurface()._oleobj_)
                    if surf.Identity() not in (4001, 1):   # 只要平面
                        continue
                    bp = face.GetBox()
                    if not bp:
                        continue
                    lo, hi = bp[idx], bp[idx + 3]
                    # 该面在目标方向上是个平面
                    if abs(lo - target) < 1e-6 and abs(hi - target) < 1e-6:
                        # 面积最大的那个（避免选到小碎面）
                        area = 0
                        try:
                            area = face.GetArea()
                        except Exception:
                            pass
                        if best is None or area > best[0]:
                            best = (area, fc)
                except Exception:
                    continue
            return best[1] if best else None
        except Exception:
            return None

    def _axis_for_plane(self, plane):
        """基准面 → 法向轴 + 正负"""
        plane = (plane or "front").lower()
        if plane in ("front", "back"):
            return "z", plane == "front"
        if plane in ("top", "bottom"):
            return "y", plane == "top"
        if plane in ("right", "left"):
            return "x", plane == "right"
        return "z", True

    def _add_extrude(self, feat, is_cut=False):
        """
        拉伸凸台 / 切除

        关键约定（与 AI 提示词保持一致）：
          · 草图平面在 Z=0
          · 拉伸凸台默认"两侧对称"，使实体在 Z 方向居中于原点
            → 立方体 100 建成 Z: -50 ~ +50，而不是 0 ~ 100
          · 这样 AI 按"零件中心在原点"规划的坑位才能对上
        """
        sk = feat.get("sketch", {})
        plane = sk.get("plane", "front")
        if not self._select_plane(plane):
            raise BuildError(f"找不到基准面 {plane}")
        self.skm.InsertSketch(True)
        desc = self._draw_sketch(sk)
        self.skm.InsertSketch(True)
        time.sleep(0.4)

        # 找最后一个草图
        sketches = [f for nm, tp, f, raw in self._features()
                    if tp in ("ProfileFeature", "Sketch")]
        if not sketches:
            raise BuildError("草图创建失败")
        sk_feat = sketches[-1]
        self.doc.ClearSelection2(True)
        sk_feat.Select2(False, 0)

        depth = float(feat.get("depth", 10)) * MM
        direction = str(feat.get("direction", "blind")).lower()

        # 凸台是否居中（默认居中，与 AI 的"零件中心在原点"假设一致）
        centered = bool(feat.get("centered", True))

        if is_cut:
            # ---- 切除 ----
            flip = bool(feat.get("flip", False))

            if direction == "through_all":
                # 完全贯穿：双向都贯穿，确保一定切透
                v_before = self._vol_mm3()
                r = self.fm.FeatureCut4(
                    False, flip, False,
                    swEndCondThroughAll, swEndCondThroughAll,
                    0.0, 0.0,
                    False, False, False, False, 0.0, 0.0,
                    False, False, False, False,
                    False, False, True,
                    False, False, False,
                    swStartSketchPlane, 0.0, False, True
                )
                time.sleep(0.5)
                v_after = self._vol_mm3()
                if abs(v_after - v_before) < 0.001:
                    raise BuildError("贯穿切除未生效")
                return f"贯穿切除 {desc}"

            # ---- 盲孔切除 ----
            #
            # ★ 核心事实（实测确认）：
            #   SolidWorks 的「给定深度」切除是**从草图平面起算**，不是从实体表面。
            #
            #   所以草图在 top 基准面（Y=0）、零件表面在 Y=+50 时，
            #   直接切 depth=15 只会切掉 Y=-15~0 —— 坑开在零件内部，表面完好。
            #
            # ★ 正确做法（和人在 SolidWorks 里操作一致）：
            #   直接选零件表面建草图，然后朝内切。
            #   这样草图平面就在表面上，切除自然从表面开始。
            self.doc.ClearSelection2(True)
            v_before = self._vol_mm3()

            axis, positive = self._axis_for_plane(plane)
            cut_done = False

            try:
                face = self._find_face_by_normal(axis, positive)
                if face is not None and face.Select(False):
                    time.sleep(0.2)
                    self.skm.InsertSketch(True)
                    self._draw_sketch(sk)
                    self.skm.InsertSketch(True)
                    time.sleep(0.4)

                    # 选刚建的草图
                    sks = [f for nm, tp, f, raw in self._features()
                           if tp in ("ProfileFeature", "Sketch")]
                    if sks:
                        self.doc.ClearSelection2(True)
                        sks[-1].Select2(False, 0)
                        # 朝内切：方向与表面法向相反
                        self.fm.FeatureCut4(
                            True,
                            not positive,     # 朝内
                            False,
                            swEndCondBlind, swEndCondBlind,
                            depth, 0.0,
                            False, False, False, False, 0.0, 0.0,
                            False, False, False, False,
                            False, False, True,
                            False, False, False,
                            swStartSketchPlane, 0.0, False, True
                        )
                        time.sleep(0.5)
                        v_after = self._vol_mm3()
                        if abs(v_after - v_before) > 1e-6:
                            cut_done = True
            except Exception as e:
                self.log(f"      表面建草图失败({str(e)[:30]})")

            if not cut_done:
                # 兜底：从基准面直接切（位置可能不理想，但不至于失败）
                self.log("      改用基准面直接切除")
                self.doc.ClearSelection2(True)
                sk_feat.Select2(False, 0)
                v_before = self._vol_mm3()
                self.fm.FeatureCut4(
                    True, flip, False,
                    swEndCondBlind, swEndCondBlind,
                    depth, 0.0,
                    False, False, False, False, 0.0, 0.0,
                    False, False, False, False,
                    False, False, True,
                    False, False, False,
                    swStartSketchPlane, 0.0, False, True
                )
                time.sleep(0.5)
                v_after = self._vol_mm3()
                if abs(v_after - v_before) < 1e-6:
                    raise BuildError("切除未生效（草图形状可能没落在实体上）")

            return f"切除 {desc} 深{float(feat.get('depth',10))}mm"

        # ---- 凸台拉伸 ----
        if centered:
            # 两侧对称：实体在 Z 方向居中
            sd_flag = False
            t1 = swEndCondBlind
            t2 = swEndCondBlind
            d1 = depth / 2
            d2 = depth / 2
        elif direction == "through_all":
            sd_flag = False
            t1 = swEndCondThroughAll
            t2 = swEndCondThroughAll
            d1 = 0.0
            d2 = 0.0
        else:
            sd_flag = True
            t1 = swEndCondBlind
            t2 = swEndCondBlind
            d1 = depth
            d2 = 0.0

        v_before = self._vol_mm3()
        r = self.fm.FeatureExtrusion3(
            sd_flag,
            bool(feat.get("flip", False)),
            False,
            t1, t2,
            d1, d2,
            False, False, False, False, 0.0, 0.0,
            False, False, False, False,
            True, False, False,
            swStartSketchPlane, 0.0, False
        )
        time.sleep(0.5)

        v_after = self._vol_mm3()
        if v_after < 0.001:
            raise BuildError("拉伸未生成实体")

        mode = "两侧对称" if centered else "单向"
        return f"拉伸 {desc} 深{float(feat.get('depth',10))}mm ({mode})"

    def _add_fillet(self, feat):
        """圆角"""
        radius = float(feat.get("radius", 2)) * MM
        target = str(feat.get("target", "vertical_edges")).lower()
        self.doc.ClearSelection2(True)
        n = self._select_edges_by_target(target)
        if n == 0:
            raise BuildError("圆角未选中任何边")
        v_b = self._vol_mm3()
        r = self.fm.FeatureFillet3(
            FILLET_OPTS_UNIFORM, radius, 0.0, 0.0,
            FILLET_TYPE_SIMPLE, 0, 0,
            None, None, None, None, None, None, None
        )
        time.sleep(0.5)
        if not r:
            raise BuildError("圆角创建失败")
        return f"圆角 R{float(feat.get('radius',2))}mm ({n}条边)"

    def _add_chamfer(self, feat):
        """倒角"""
        dist = float(feat.get("distance", 1)) * MM
        ang = math.radians(float(feat.get("angle", 45)))
        target = str(feat.get("target", "vertical_edges")).lower()
        self.doc.ClearSelection2(True)
        n = self._select_edges_by_target(target)
        if n == 0:
            raise BuildError("倒角未选中任何边")
        r = self.fm.InsertFeatureChamfer(0, CHAMFER_ANGLE_DIST, dist, ang, dist, 0.0, 0.0, 0.0)
        time.sleep(0.5)
        if not r:
            raise BuildError("倒角创建失败")
        return f"倒角 C{float(feat.get('distance',1))} ({n}条边)"

    def _select_edges_by_target(self, target):
        """按目标类型选边"""
        n = 0
        if target in ("vertical_edges", "all_edges"):
            for p1, p2, e in self._line_edges():
                # 竖直边：XY 相同，Z 变化
                if abs(p1[0] - p2[0]) < 1e-9 and abs(p1[1] - p2[1]) < 1e-9 \
                        and abs(p1[2] - p2[2]) > 1e-9:
                    if self._sel(e):
                        n += 1
        if target == "top_edges":
            # 顶面圆边：所有圆形边
            for cx, cy, cz, rad, e in self._circular_edges():
                if self._sel(e):
                    n += 1
        if target == "all_edges" and n == 0:
            for cx, cy, cz, rad, e in self._circular_edges():
                if self._sel(e):
                    n += 1
        if target == "horizontal_edges":
            for p1, p2, e in self._line_edges():
                if abs(p1[2] - p2[2]) < 1e-9 and \
                        not (abs(p1[0]-p2[0]) < 1e-9 and abs(p1[1]-p2[1]) < 1e-9):
                    if self._sel(e):
                        n += 1
        return n

    # ---------------- 旋转 ----------------
    def _add_revolve(self, feat):
        """
        旋转特征：草图画剖面轮廓，绕轴旋转成回转体。

        feat 结构：
            {
              "type": "revolve",
              "desc": "...",
              "angle": 360,              # 旋转角度（默认 360，可小于 360 做部分回转）
              "profile": [[x,y], ...],   # 剖面点位（mm），x=半径方向, y=轴向
              "plane": "front"           # 草图基准面
            }
        """
        angle_deg = float(feat.get("angle", 360))
        profile = feat.get("profile", [])
        if len(profile) < 3:
            raise BuildError("旋转需要至少 3 个轮廓点")

        plane = feat.get("plane", "front")
        if not self._select_plane(plane):
            raise BuildError(f"找不到基准面 {plane}")

        self.skm.InsertSketch(True)
        pts = [(float(x) * MM, float(y) * MM) for x, y in profile]

        # 画闭合轮廓
        for i in range(len(pts)):
            x1, y1 = pts[i]
            x2, y2 = pts[(i + 1) % len(pts)]
            self.skm.CreateLine(x1, y1, 0.0, x2, y2, 0.0)

        # 中心线作为旋转轴：沿 Y 轴（竖直），即 x=0 的线。
        # 约定：profile 的 x = 半径（>=0），y = 高度。
        # 这样旋转出来是竖立的回转体，高度沿 Y，直径在 XZ 平面。
        ymin = min(p[1] for p in pts) - 1 * MM
        ymax = max(p[1] for p in pts) + 1 * MM
        try:
            self.skm.CreateCenterLine(0.0, ymin, 0.0, 0.0, ymax, 0.0)
        except Exception:
            pass

        self.skm.InsertSketch(True)
        time.sleep(0.4)

        # 找草图和轴线
        sketches = [f for nm, tp, f, raw in self._features()
                    if tp in ("ProfileFeature", "Sketch")]
        if not sketches:
            raise BuildError("旋转草图创建失败")
        sk_feat = sketches[-1]

        self.doc.ClearSelection2(True)
        sk_feat.Select2(False, 0)

        v_before = self._vol_mm3()
        r = self.fm.FeatureRevolve2(
            True,                       # SingleDir 单向
            True,                       # IsSolid 实体
            False,                      # IsThin 薄壁
            False,                      # IsCut 不切除
            False,                      # ReverseDir
            False,                      # BothDirectionUpToSameEntity
            0,                          # Dir1Type = swEndCondBlind
            0,                          # Dir2Type
            math.radians(angle_deg),    # Dir1Angle
            0.0,                        # Dir2Angle
            False, False,               # OffsetReverse1/2
            0.0, 0.0,                   # OffsetDistance1/2
            0,                          # ThinType
            0.0, 0.0,                   # ThinThickness1/2
            True,                       # Merge
            False,                      # UseFeatScope
            False                       # UseAutoSelect
        )
        time.sleep(0.6)

        if not r:
            # 重试：用 2π 而非 radians（某些版本对精确值敏感）
            self.doc.ClearSelection2(True)
            sk_feat.Select2(False, 0)
            r = self.fm.FeatureRevolve2(
                True, True, False, False, False, False,
                0, 0, 2 * math.pi, 0.0,
                False, False, 0.0, 0.0, 0, 0.0, 0.0,
                True, False, False
            )
            time.sleep(0.6)

        if not r:
            raise BuildError("旋转失败（轮廓可能不闭合或与轴相交）")

        v_after = self._vol_mm3()
        if abs(v_after - v_before) < 0.001:
            raise BuildError("旋转未生成实体")
        return f"旋转 {len(pts)}点轮廓 转{angle_deg:.0f}°"

    # ---------------- 抽壳 ----------------
    def _add_shell(self, feat):
        """
        抽壳：把实体挖空成薄壁。

        feat 结构：
            {
              "type": "shell",
              "desc": "...",
              "thickness": 3,          # 壁厚 mm
              "outward": False,        # True=向外加厚，False=向内
              "remove_faces": "top"    # 要开口的面：top/bottom/none/auto
            }
        """
        thickness = float(feat.get("thickness", 2)) * MM
        outward = bool(feat.get("outward", False))
        remove = str(feat.get("remove_faces", "top")).lower()

        self.doc.ClearSelection2(True)

        # 选中要开口的面
        n_removed = 0
        if remove != "none":
            n_removed = self._select_faces_by_role(remove)
            if n_removed == 0:
                # 没选中也继续（整体抽壳）
                self.doc.ClearSelection2(True)

        v_before = self._vol_mm3()
        try:
            r = self.doc.InsertFeatureShell(thickness, outward)
        except Exception as e:
            raise BuildError(f"抽壳 API 调用失败: {e}")
        time.sleep(0.6)

        v_after = self._vol_mm3()
        if abs(v_after - v_before) < 0.001:
            raise BuildError("抽壳未生效（体积未变化）")
        opened = f" 开口{n_removed}个面" if n_removed else ""
        return f"抽壳 {float(feat.get('thickness',2))}mm{opened}"

    def _select_faces_by_role(self, role):
        """
        按角色选面。

        坐标系说明（旋转体）：
          · Y = 高度方向（旋转轴方向）
          · X / Z = 直径方向
        所以找「顶面/底面」要看 Y 范围，不是 Z。
        """
        part = self.mod.IPartDoc(self.doc._oleobj_)
        bodies = part.GetBodies2(0, True)
        if not bodies:
            return 0
        body = self.mod.IBody2(bodies[0]._oleobj_)

        faces = []
        for fc in (body.GetFaces() or []):
            face = self.mod.IFace2(fc._oleobj_)
            try:
                bp = face.GetBox()
                if not bp:
                    continue
                surf = self.mod.ISurface(face.GetSurface()._oleobj_)
                # GetBox 返回 [xmin, ymin, zmin, xmax, ymax, zmax]
                xmin, ymin, zmin, xmax, ymax, zmax = bp
                faces.append({
                    "raw": fc,
                    "face": face,
                    "type": surf.Identity(),
                    "xmin": xmin, "xmax": xmax,
                    "ymin": ymin, "ymax": ymax,
                    "zmin": zmin, "zmax": zmax,
                    "area": face.GetArea() if hasattr(face, "GetArea") else 0,
                })
            except Exception:
                continue

        if not faces:
            return 0

        ymin_all = min(f["ymin"] for f in faces)
        ymax_all = max(f["ymax"] for f in faces)
        tol = 1e-5

        def is_horizontal_plane(f, y_val):
            """判断是否为 y = y_val 处的水平平面"""
            if f["type"] not in (4001, 1):
                return False
            return abs(f["ymin"] - y_val) < tol and abs(f["ymax"] - y_val) < tol

        n = 0
        if role == "top":
            # 顶面：水平面且位于最高处
            for f in faces:
                if is_horizontal_plane(f, ymax_all):
                    if self._sel(f["raw"]):
                        n += 1
            # 兜底：如果没有水平顶面（例如已经开口），找最高处任何面
            if n == 0:
                cands = [f for f in faces if abs(f["ymax"] - ymax_all) < 1e-5]
                for f in cands:
                    if self._sel(f["raw"]):
                        n += 1

        elif role == "bottom":
            for f in faces:
                if is_horizontal_plane(f, ymin_all):
                    if self._sel(f["raw"]):
                        n += 1

        elif role == "largest":
            f = max(faces, key=lambda x: x["area"])
            if self._sel(f["raw"]):
                n = 1

        elif role == "auto":
            # 自动：选最高的水平平面（通常就是开口面）
            for f in faces:
                if is_horizontal_plane(f, ymax_all):
                    if self._sel(f["raw"]):
                        n += 1
            if n == 0:
                cands = [f for f in faces if abs(f["ymax"] - ymax_all) < 1e-5]
                for f in cands:
                    if self._sel(f["raw"]):
                        n += 1

        elif role == "all":
            for f in faces:
                if self._sel(f["raw"]):
                    n += 1

        return n

    # ---------------- 圆角(通用) ----------------
    def _add_fillet_general(self, feat):
        """圆角：支持按边类型或全选"""
        radius = float(feat.get("radius", 2)) * MM
        target = str(feat.get("target", "vertical_edges")).lower()
        self.doc.ClearSelection2(True)
        n = self._select_edges_by_target(target)
        if n == 0:
            # 兜底：选所有边
            n = self._select_all_edges()
        if n == 0:
            raise BuildError("圆角未选中任何边")
        r = self.fm.FeatureFillet3(
            FILLET_OPTS_UNIFORM, radius, 0.0, 0.0,
            FILLET_TYPE_SIMPLE, 0, 0,
            None, None, None, None, None, None, None
        )
        time.sleep(0.5)
        if not r:
            raise BuildError("圆角创建失败")
        return f"圆角 R{float(feat.get('radius',2))}mm ({n}条边)"

    def _select_all_edges(self):
        """选中实体的所有边"""
        n = 0
        part = self.mod.IPartDoc(self.doc._oleobj_)
        bodies = part.GetBodies2(0, True)
        if not bodies:
            return 0
        body = self.mod.IBody2(bodies[0]._oleobj_)
        for e in body.GetEdges():
            if self._sel(e):
                n += 1
        return n

    # ---------------- 主流程 ----------------
    def build(self, spec: dict, save_path: str):
        """
        根据 spec 建模并保存。

        返回 dict: {path, volume_mm3, area_mm2, faces, edges, steps}
        """
        self.connect()
        self._new_part()

        steps = []
        features = spec.get("features", [])
        if not features:
            raise BuildError("AI 没有给出建模步骤")

        for i, feat in enumerate(features, 1):
            ftype = str(feat.get("type", "")).lower()
            self.log(f"  [{i}/{len(features)}] {ftype}: {feat.get('desc','')}")
            try:
                if ftype == "extrude":
                    desc = self._add_extrude(feat, is_cut=False)
                elif ftype == "cut":
                    desc = self._add_extrude(feat, is_cut=True)
                elif ftype in ("revolve", "旋转"):
                    desc = self._add_revolve(feat)
                elif ftype in ("shell", "抽壳"):
                    desc = self._add_shell(feat)
                elif ftype in ("fillet", "圆角"):
                    desc = self._add_fillet(feat)
                elif ftype in ("chamfer", "倒角"):
                    desc = self._add_chamfer(feat)
                else:
                    self.log(f"    跳过不支持的特征: {ftype}")
                    continue
                steps.append(desc)
            except BuildError as e:
                self.log(f"    [警告] {e}")
                steps.append(f"[跳过] {feat.get('desc', ftype)}: {e}")

        # 统计
        part = self.mod.IPartDoc(self.doc._oleobj_)
        bodies = part.GetBodies2(0, True)
        if not bodies:
            raise BuildError("模型没有生成任何实体")

        mp = self.ext.CreateMassProperty()
        body = self.mod.IBody2(bodies[0]._oleobj_)

        # 保存
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        self.doc.SaveAs3(save_path, 0, SAVE_SILENT)
        time.sleep(1.5)

        if not os.path.exists(save_path):
            raise BuildError(f"文件保存失败: {save_path}")

        return {
            "path": save_path,
            "volume_mm3": mp.Volume * 1e9,
            "area_mm2": mp.SurfaceArea * 1e6,
            "faces": body.GetFaceCount(),
            "edges": body.GetEdgeCount(),
            "steps": steps,
        }

    # ---------------- 3D 打印导出 ----------------
    def export_stl(self, stl_path: str, quality="fine") -> dict:
        """
        把当前零件导出为 STL（3D 打印格式）。

        参数：
            stl_path: 输出路径（.stl）
            quality:  "fine"（精细，推荐打印）| "medium" | "coarse"

        返回：{"path":..., "size_mb":...}
        """
        if self.doc is None:
            raise BuildError("没有打开的文档")

        # 设置 STL 导出参数（先设偏好，再保存）
        try:
            # swSTLQuality: 1=Coarse 2=Fine 3=Custom
            q = {"coarse": 1, "medium": 2, "fine": 2}.get(quality, 2)
            self.sw.SetUserPreferenceIntegerValue(78, q)        # swSTLQuality
            self.sw.SetUserPreferenceToggle(69, True)           # swSTLBinaryFormat
            self.sw.SetUserPreferenceDoubleValue(2, 0.05)       # swSTLDeviation (mm)
            self.sw.SetUserPreferenceDoubleValue(3, 10.0)       # swSTLAngleTolerance (deg)
            self.sw.SetUserPreferenceToggle(70, False)          # 不显示保存信息
        except Exception as e:
            self.log(f"  STL 参数设置警告: {e}")

        os.makedirs(os.path.dirname(stl_path) or ".", exist_ok=True)

        ok = False
        try:
            r = self.doc.SaveAs3(stl_path, 0, SAVE_SILENT)
            # SaveAs3 返回 0 表示成功
            ok = os.path.exists(stl_path)
        except Exception as e:
            self.log(f"  SaveAs3 导出 STL 失败: {e}")

        # 备用：SaveAs4 / SaveAs
        if not ok:
            for meth in ("SaveAs4", "SaveAs"):
                try:
                    fn = getattr(self.doc, meth, None)
                    if fn is None:
                        continue
                    if meth == "SaveAs4":
                        fn(stl_path, 0, SAVE_SILENT, 0, 0)
                    else:
                        fn(stl_path)
                    if os.path.exists(stl_path):
                        ok = True
                        break
                except Exception:
                    continue

        if not ok or not os.path.exists(stl_path):
            raise BuildError("STL 导出失败，请确认零件有效")

        size_mb = os.path.getsize(stl_path) / 1024 / 1024
        return {"path": stl_path, "size_mb": size_mb}

