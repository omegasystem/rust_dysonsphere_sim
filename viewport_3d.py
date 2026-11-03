#!/usr/bin/env python3
"""
viewport_3d.py - PyQt6 2.5D ~ 3D Holographic Renderer (Earth -> Solar System -> Dyson Shell)
=============================================================================================
Supports interactive 3D camera orbit (Left-Click Drag), Zoom (Mouse Wheel), and 3 View Modes:
  1. `earth_25d`      : 🌍 地球赤道微電網與化工基地 (2.5D/3D Planetary Horizon + H2/Oil Tanks + EM Railguns)
  2. `solar_3d`       : ☀️ 太陽系星際軌道與戴森雲 (3D Helios Star + Planetary Orbits + Swarm Rings + Launch Beams)
  3. `dyson_shell_3d` : 🪐 恆星級戴森球測地線殼面 (3D Geodesic Dyson Nodes/Panels + Photon Beams + Artificial Sun)
"""

import math
from typing import Any, Dict, List, Tuple

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
    QRadialGradient,
)
from PyQt6.QtWidgets import QWidget


class DysonCosmos3DViewport(QWidget):
    """Interactive 2.5D ~ 3D Perspective Viewport for `rust_dysonsphere_sim`."""

    def __init__(self, parent: QWidget = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(680, 500)
        self.view_mode: str = "earth_25d"  # "earth_25d" | "solar_3d" | "dyson_shell_3d"
        self.auto_follow_stage: bool = True

        # 3D Camera Spherical Coordinates
        self.cam_yaw: float = 0.55
        self.cam_pitch: float = 0.42
        self.cam_zoom: float = 1.0
        self._last_mouse_pos = None
        self.anim_phase: float = 0.0
        self.is_paused_for_ai: bool = False
        self.state: Dict[str, Any] = {}

        # Precompute geodesic icosahedron/sphere vertices for Dyson Shell & High-Density Hawking Quantum Mesh
        self._geodesic_nodes: List[Tuple[float, float, float]] = self._build_geodesic_nodes(48)
        self._quantum_mesh_nodes: List[Tuple[float, float, float]] = self._build_geodesic_nodes(168)
        self._stars_bg: List[Tuple[float, float, float, int]] = self._build_starfield(140)

        # 3D Lorenz Phase-Space Attractor Trajectory Buffer:
        # Each entry: (x, y, z, stage, is_crisis, is_ai_intervention, tick)
        self.phase_trail: List[Tuple[float, float, float, int, bool, bool, int]] = []
        self._lx: float = 0.8
        self._ly: float = 0.2
        self._lz: float = 1.0
        self._pending_ai_star: bool = False
        self._last_recorded_tick: int = -1

        # Stage Ascension Cinematic Transition State (0.0 = inactive, >0.0 = countdown frames)
        self.ascension_anim_frames: int = 0
        self.ascension_total_frames: int = 75
        self.ascension_from_stage: int = 1
        self.ascension_to_stage: int = 2
        self.ascension_title: str = ""
        self.ascension_lore: str = ""

        # Custom Declarative High-Dimensional Particle Program (Sequence + Function List)
        self.custom_particle_program: Dict[str, Any] = self.default_particle_program_for_stage(7)

    @staticmethod
    def default_particle_program_for_stage(st: int) -> Dict[str, Any]:
        """Returns a Stage-specific declarative Sequence + Function List for High-Dimensional States."""
        if st <= 6:
            return {"enabled": False, "particle_count": 240, "connect_stride": 0, "color_palette": ["#38bdf8", "#c084fc"], "function_list": []}
        presets = {
            7: {
                "enabled": True,
                "name": "Stage 7: 普朗克膜與真空泡沫序列",
                "particle_count": 280,
                "connect_stride": 7,
                "color_palette": ["#38bdf8", "#a855f7", "#facc15"],
                "function_list": [
                    {"fn": "torus_knot", "p": 2, "q": 5, "radius": 1.25, "tube": 0.28, "speed": 1.0},
                    {"fn": "vacuum_foam_pulse", "freq": 6.0, "amp": 0.12, "use_dim_exponent": True},
                ],
            },
            8: {
                "enabled": True,
                "name": "Stage 8: 卡拉比-丘 6D 流形摺疊序列",
                "particle_count": 340,
                "connect_stride": 8,
                "color_palette": ["#e879f9", "#38bdf8", "#f43f5e"],
                "function_list": [
                    {"fn": "hypersphere_4d", "radius": 1.20, "w_speed": 1.2, "proj_d": 2.2},
                    {"fn": "calabi_yau_fold", "n_fold": 6, "amp": 0.25, "speed": 1.4},
                    {"fn": "lorentz_twist", "axis": "y", "strength": 0.55},
                ],
            },
            9: {
                "enabled": True,
                "name": "Stage 9: 超膜蟲洞泡沫與霍普夫纖維叢",
                "particle_count": 380,
                "connect_stride": 9,
                "color_palette": ["#00f5d4", "#facc15", "#c084fc"],
                "function_list": [
                    {"fn": "wormhole_throat", "throat_r": 0.55, "flare": 0.85, "height": 1.35},
                    {"fn": "hopf_fibration", "eta": 0.72, "scale": 0.24, "speed": 1.3},
                    {"fn": "vacuum_foam_pulse", "freq": 8.0, "amp": 0.10, "use_dim_exponent": True},
                ],
            },
            10: {
                "enabled": True,
                "name": "Stage 10: 歐米伽全息超膜奇點結",
                "particle_count": 420,
                "connect_stride": 6,
                "color_palette": ["#facc15", "#38bdf8", "#f472b6"],
                "function_list": [
                    {"fn": "torus_knot", "p": 3, "q": 8, "radius": 1.32, "tube": 0.35, "speed": 1.2},
                    {"fn": "calabi_yau_fold", "n_fold": 8, "amp": 0.20, "speed": 1.6},
                    {"fn": "hopf_fibration", "eta": 0.85, "scale": 0.22, "speed": 1.5},
                ],
            },
            11: {
                "enabled": True,
                "name": "Stage 11: 真真空相變多重宇宙泡沫",
                "particle_count": 450,
                "connect_stride": 5,
                "color_palette": ["#34d399", "#38bdf8", "#e879f9"],
                "function_list": [
                    {"fn": "hypersphere_4d", "radius": 1.35, "w_speed": 1.6, "proj_d": 1.95},
                    {"fn": "torus_knot", "p": 5, "q": 9, "radius": 0.45, "tube": 0.22, "speed": 1.8},
                    {"fn": "vacuum_foam_pulse", "freq": 10.0, "amp": 0.14, "use_dim_exponent": True},
                ],
            },
            12: {
                "enabled": True,
                "name": "Stage 12: 閉時曲線 (CTC) 莫比烏斯時間環路",
                "particle_count": 480,
                "connect_stride": 4,
                "color_palette": ["#fbbf24", "#06b6d4", "#ec4899"],
                "function_list": [
                    {"fn": "ctc_time_loop", "loops": 3, "radius": 1.38, "twist_speed": 1.5},
                    {"fn": "calabi_yau_fold", "n_fold": 6, "amp": 0.18, "speed": 2.0},
                    {"fn": "lorentz_twist", "axis": "z", "strength": 0.65},
                    {"fn": "vacuum_foam_pulse", "freq": 12.0, "amp": 0.08, "use_dim_exponent": True},
                ],
            },
        }
        if st in presets:
            return presets[st]
        # Stage 13+: Brane-World Omniscience Hyper-Manifold
        return {
            "enabled": True,
            "name": f"Stage {st}: 超膜維度摺疊與全域意識共鳴場",
            "particle_count": 520,
            "connect_stride": 5,
            "color_palette": ["#fde047", "#22d3ee", "#e879f9", "#fb7185"],
            "function_list": [
                {"fn": "ctc_time_loop", "loops": 4 + (st % 3), "radius": 1.42, "twist_speed": 1.8},
                {"fn": "hypersphere_4d", "radius": 0.55, "w_speed": 2.1, "proj_d": 2.0},
                {"fn": "calabi_yau_fold", "n_fold": 8, "amp": 0.22, "speed": 2.2},
                {"fn": "hopf_fibration", "eta": 0.9, "scale": 0.20, "speed": 1.7},
                {"fn": "vacuum_foam_pulse", "freq": 14.0, "amp": 0.10, "use_dim_exponent": True},
            ],
        }

    def trigger_ascension_transition(self, from_stage: int, to_stage: int, title: str, lore: str = "") -> None:
        """Triggers a 75-frame (~3.5s) Hyperspace Collapse -> Supernova -> Dimensional Unfold ceremony."""
        self.ascension_from_stage = from_stage
        self.ascension_to_stage = to_stage
        self.ascension_title = title
        self.ascension_lore = lore
        self.ascension_total_frames = 75
        self.ascension_anim_frames = 75
        self.update()

    def set_custom_particle_program(self, prog: Dict[str, Any]) -> None:
        if isinstance(prog, dict) and "function_list" in prog:
            self.custom_particle_program = prog
            self.update()

    @staticmethod
    def _build_geodesic_nodes(n: int) -> List[Tuple[float, float, float]]:
        pts = []
        phi = math.pi * (3.0 - math.sqrt(5.0))
        for i in range(n):
            y = 1.0 - (i / float(max(1, n - 1))) * 2.0
            r = math.sqrt(max(0.0, 1.0 - y * y))
            theta = phi * i
            pts.append((math.cos(theta) * r, y, math.sin(theta) * r))
        return pts

    @staticmethod
    def _build_starfield(n: int) -> List[Tuple[float, float, float, int]]:
        pts = []
        for i in range(n):
            fx = ((i * 73) % 997) / 997.0
            fy = ((i * 191) % 991) / 991.0
            b = 90 + ((i * 43) % 155)
            pts.append((fx, fy, 1.0 + (i % 3) * 0.6, b))
        return pts

    def mark_ai_intervention(self) -> None:
        """Marks the next phase-space point as an AI Saddle-Flip / Parameter Intervention Star."""
        self._pending_ai_star = True

    def compute_and_record_lorenz_point(self, state: Dict[str, Any]) -> Tuple[float, float, float, bool]:
        """
        Couples real Dyson Sphere telemetry (η, H2%, EROEI, EXP_rate, AI control params)
        into a 3D Dual-Wing Lorenz Strange Attractor phase space (X, Y, Z).
        """
        eta = float(state.get("grid_satisfaction", 1.0))
        h2 = float(state.get("hydrogen_tank_pct", 40.0)) / 100.0
        exp_rate = float(state.get("stage_exp_rate_per_tick", 0.1))
        eroei = float(state.get("eroei", 1.2))
        st = int(state.get("stage", 1))
        tick = int(state.get("tick", 0))
        is_crisis = bool(
            state.get("fault_brownout_spiral")
            or state.get("fault_h2_deadlock")
            or state.get("fault_seu_bitflip")
            or state.get("fault_dust_storm", 0.0) > 0.25
            or exp_rate < 0.0
        )

        # Coupled Lorenz-Telemetry Differential Step (dt = 0.012)
        # Right Wing (+X) = Autopoietic Growth; Left Wing (-X) = Crisis / Deadlock Spiral
        dt = 0.012
        sigma = 10.0
        rho = 28.0 + min(8.0, math.log1p(max(0.0, eroei)) * 2.0)
        beta = 8.0 / 3.0

        # Telemetry forcing nudges trajectory toward Right Wing when healthy, or Left Wing during crisis
        wing_drive = -2.2 if is_crisis else 1.8 * min(1.3, eta)
        chem_drive = (h2 - 0.55) * 4.5

        dx = sigma * (self._ly - self._lx) + wing_drive
        dy = self._lx * (rho - self._lz) - self._ly + chem_drive
        dz = self._lx * self._ly - beta * self._lz + exp_rate * 3.0

        self._lx = max(-25.0, min(25.0, self._lx + dx * dt))
        self._ly = max(-30.0, min(30.0, self._ly + dy * dt))
        self._lz = max(2.0, min(48.0, self._lz + dz * dt))

        # Normalize into viewport [-1.45 .. +1.45] 3D box
        nx = self._lx / 14.0
        ny = (self._lz - 24.0) / 16.0
        nz = self._ly / 16.0

        ai_star = self._pending_ai_star
        self._pending_ai_star = False
        self.phase_trail.append((nx, ny, nz, st, is_crisis, ai_star, tick))
        if len(self.phase_trail) > 1600:
            self.phase_trail.pop(0)
        return nx, ny, nz, is_crisis

    def update_sim_state(self, state: Dict[str, Any], paused_for_ai: bool = False) -> None:
        self.state = state
        self.is_paused_for_ai = paused_for_ai
        cur_tick = int(state.get("tick", -1)) if state else -1
        # Advance Ascension Transition Ceremony even when paused waiting for AI!
        if self.ascension_anim_frames > 0:
            self.ascension_anim_frames -= 1
            self.anim_phase += 0.045
        # Strictly advance Lorenz Attractor & orbital animations ONLY when a new physics Tick actually occurred!
        elif not paused_for_ai and state and cur_tick > 0 and cur_tick != self._last_recorded_tick:
            self._last_recorded_tick = cur_tick
            self.compute_and_record_lorenz_point(state)
            self.anim_phase += 0.035
        # Only keep view locked when user explicitly chose `lorenz_3d`; otherwise follow stage!
        if self.view_mode != "lorenz_3d" and self.auto_follow_stage:
            self.sync_view_to_stage(int(state.get("stage", 1)))
        self.update()

    def sync_view_to_stage(self, st: int) -> None:
        if st in (1, 2):
            self.view_mode = "earth_25d"
        elif st == 3:
            self.view_mode = "solar_3d"
        elif st == 4:
            self.view_mode = "dyson_shell_3d"
        elif st == 5:
            self.view_mode = "matrioshka_3d"
        else:
            self.view_mode = "blackhole_3d"

    def project_3d(self, x: float, y: float, z: float, cx: float, cy: float, scale: float) -> Tuple[float, float, float]:
        """Rotates (x, y, z) by (cam_yaw, cam_pitch) and applies perspective projection."""
        cos_y, sin_y = math.cos(self.cam_yaw), math.sin(self.cam_yaw)
        x1 = x * cos_y - z * sin_y
        z1 = x * sin_y + z * cos_y

        cos_p, sin_p = math.cos(self.cam_pitch), math.sin(self.cam_pitch)
        y2 = y * cos_p - z1 * sin_p
        z2 = y * sin_p + z1 * cos_p

        fov_dist = 4.2
        depth = max(0.6, fov_dist + z2)
        persp = (fov_dist / depth) * scale * self.cam_zoom
        return cx + x1 * persp, cy - y2 * persp, z2

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._last_mouse_pos = event.position()

    def mouseMoveEvent(self, event) -> None:
        if self._last_mouse_pos is not None:
            pos = event.position()
            dx = pos.x() - self._last_mouse_pos.x()
            dy = pos.y() - self._last_mouse_pos.y()
            self.cam_yaw += dx * 0.008
            self.cam_pitch = max(-1.35, min(1.35, self.cam_pitch + dy * 0.008))
            self._last_mouse_pos = pos
            self.update()

    def mouseReleaseEvent(self, event) -> None:
        self._last_mouse_pos = None

    def wheelEvent(self, event) -> None:
        delta = event.angleDelta().y()
        factor = 1.12 if delta > 0 else 0.89
        self.cam_zoom = max(0.45, min(2.8, self.cam_zoom * factor))
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = float(self.width()), float(self.height())
        cx, cy = w * 0.5, h * 0.52

        # Deep space background gradient
        bg = QLinearGradient(0, 0, 0, h)
        bg.setColorAt(0.0, QColor(4, 8, 20))
        bg.setColorAt(0.6, QColor(8, 15, 32))
        bg.setColorAt(1.0, QColor(12, 22, 44))
        p.fillRect(self.rect(), bg)

        # Starfield
        for fx, fy, sz, b in self._stars_bg:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(b, b + 10, 255, 180))
            p.drawEllipse(QPointF(fx * w, fy * h), sz, sz)

        # Compute Ascension Warp Scale Multiplier (Implosion -> Burst -> Unfold)
        scene_scale = min(w, h) * 0.36
        if self.ascension_anim_frames > 0:
            prog_t = 1.0 - (self.ascension_anim_frames / float(max(1, self.ascension_total_frames)))
            if prog_t < 0.28:
                # Phase 1: Gravitational Collapse into Singularity
                scene_scale *= max(0.12, 1.0 - (prog_t / 0.28) * 0.88)
            elif prog_t < 0.65:
                # Phase 2: Dimensional Supernova Unfolding
                u_t = (prog_t - 0.28) / 0.37
                scene_scale *= 0.12 + 1.08 * (1.0 - (1.0 - u_t) ** 3)
            else:
                # Phase 3: Settle to 1.0
                s_t = (prog_t - 0.65) / 0.35
                scene_scale *= 1.20 - 0.20 * s_t

        if self.view_mode == "earth_25d":
            self._draw_earth_base_25d(p, cx, cy, scene_scale * 0.94)
        elif self.view_mode == "solar_3d":
            self._draw_solar_system_3d(p, cx, cy, scene_scale)
        elif self.view_mode == "lorenz_3d":
            self._draw_lorenz_attractor_3d(p, cx, cy, scene_scale)
        elif self.view_mode == "matrioshka_3d":
            self._draw_matrioshka_cluster_3d(p, cx, cy, scene_scale)
        elif self.view_mode == "blackhole_3d":
            self._draw_kerr_blackhole_3d(p, cx, cy, scene_scale)
        else:
            self._draw_dyson_shell_3d(p, cx, cy, scene_scale)

        # Render Declarative High-Dimensional Particle Manifold (Sequence + Function List)
        self._draw_declarative_particle_manifold(p, cx, cy, scene_scale)

        self._draw_hud_overlay(p, w, h)

        # Render Stage Ascension Transition Ceremony Overlay (Shockwaves + Lore Decree)
        if self.ascension_anim_frames > 0:
            self._draw_ascension_transition_overlay(p, w, h, cx, cy)
        p.end()

    def _draw_earth_base_25d(self, p: QPainter, cx: float, cy: float, scale: float) -> None:
        s = self.state
        eta = float(s.get("grid_satisfaction", 1.0))
        dust = float(s.get("fault_dust_storm", 0.0))
        h2_pct = float(s.get("hydrogen_tank_pct", 40.0))
        oil_pct = float(s.get("refined_oil_tank_pct", 35.0))
        sails = float(s.get("active_solar_sails", 120.0))

        # 1. Draw 2.5D/3D Tilted Planetary Equatorial Grid
        grid_color = QColor(34, 211, 238, 70) if eta >= 0.85 else QColor(244, 63, 94, 110)
        p.setPen(QPen(grid_color, 1.0))
        for gx in range(-6, 7):
            x_val = gx * 0.25
            sx1, sy1, _ = self.project_3d(x_val, -0.35, -1.5, cx, cy, scale)
            sx2, sy2, _ = self.project_3d(x_val, -0.35, 1.5, cx, cy, scale)
            p.drawLine(QPointF(sx1, sy1), QPointF(sx2, sy2))
        for gz in range(-6, 7):
            z_val = gz * 0.25
            sx1, sy1, _ = self.project_3d(-1.5, -0.35, z_val, cx, cy, scale)
            sx2, sy2, _ = self.project_3d(1.5, -0.35, z_val, cx, cy, scale)
            p.drawLine(QPointF(sx1, sy1), QPointF(sx2, sy2))

        # 2. Equatorial Solar Panel Ring (Outer Ring)
        n_solar = min(36, max(8, int(s.get("solar_panels", 24) / 3)))
        for i in range(n_solar):
            ang = (2.0 * math.pi * i) / n_solar
            rx, rz = 1.28 * math.cos(ang), 1.28 * math.sin(ang)
            px, py, _ = self.project_3d(rx, -0.32, rz, cx, cy, scale)
            c = QColor(56, 189, 248, int(210 * (1.0 - dust * 0.7)))
            p.setBrush(c)
            p.setPen(QPen(QColor(186, 230, 253), 1.0))
            p.drawRect(QRectF(px - 5, py - 3, 10, 6))

        # 3. 3D Storage Cylinders for H2 Tank & Refined Oil Tank (Anchored to 3D Base Point `bx, by` so liquid is 100% centered at any camera angle!)
        for idx, (label, pct, tx, tz, base_col) in enumerate([
            ("H2 儲槽", h2_pct, -0.65, 0.25, QColor(56, 189, 248) if h2_pct < 95 else QColor(244, 63, 94)),
            ("精煉油槽", oil_pct, -0.25, 0.45, QColor(251, 191, 36)),
        ]):
            bx, by, _ = self.project_3d(tx, -0.32, tz, cx, cy, scale)
            cyl_w = 28.0 * max(0.75, min(1.35, self.cam_zoom))
            cyl_h = 115.0 * max(0.75, min(1.35, self.cam_zoom))
            top_y = by - cyl_h
            clamped_pct = max(0.0, min(100.0, pct))
            fill_h = (cyl_h - 4.0) * (clamped_pct / 100.0)
            fill_y = by - 2.0 - fill_h

            # Outer Glass Cylinder Frame
            p.setPen(QPen(QColor(148, 163, 184, 180), 1.5))
            p.setBrush(QColor(15, 23, 42, 185))
            p.drawRoundedRect(QRectF(bx - cyl_w * 0.5, top_y, cyl_w, cyl_h), 4, 4)

            # Inner Liquid Level Bar (Strictly centered inside `bx`!)
            if fill_h > 0.5:
                inner_w = cyl_w - 4.0
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(base_col)
                p.drawRoundedRect(QRectF(bx - inner_w * 0.5, fill_y, inner_w, fill_h), 2, 2)

            p.setPen(QColor(226, 232, 240))
            p.setFont(QFont("SansSerif", 8, QFont.Weight.Bold))
            p.drawText(QPointF(bx - cyl_w * 0.7, top_y - 8), f"{label} {pct:.0f}%")

        # 4. Central Mini-Fusion & Thermal Power Core Domes
        core_x, core_y, _ = self.project_3d(0.25, -0.20, -0.10, cx, cy, scale)
        glow_r = 28.0 * self.cam_zoom
        grad = QRadialGradient(QPointF(core_x, core_y), glow_r)
        if eta >= 0.85:
            grad.setColorAt(0.0, QColor(52, 211, 153, 240))
            grad.setColorAt(1.0, QColor(16, 185, 129, 0))
        else:
            grad.setColorAt(0.0, QColor(244, 63, 94, 240))
            grad.setColorAt(1.0, QColor(225, 29, 72, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(grad)
        p.drawEllipse(QPointF(core_x, core_y), glow_r, glow_r)

        # 5. Equatorial EM Rail Ejectors firing Solar Sails into Sky
        em_rate = float(s.get("params", {}).get("em_ejector_rate", 0.3))
        if em_rate > 0.05 and eta > 0.4:
            for k in range(3):
                ex, ey, _ = self.project_3d(0.75 + k * 0.22, -0.30, -0.45 + k * 0.3, cx, cy, scale)
                sky_x, sky_y, _ = self.project_3d(1.2 + k * 0.3, 1.35, -0.9, cx, cy, scale)
                p.setPen(QPen(QColor(250, 204, 21, 190), 2.0, Qt.PenStyle.DashLine))
                p.drawLine(QPointF(ex, ey), QPointF(sky_x, sky_y))
                t_prog = (self.anim_phase * 1.8 + k * 0.33) % 1.0
                px = ex + (sky_x - ex) * t_prog
                py = ey + (sky_y - ey) * t_prog
                p.setBrush(QColor(254, 240, 138))
                p.drawEllipse(QPointF(px, py), 4.0, 4.0)

        # 6. Distant Helios Sun & Dyson Swarm Preview in Upper Sky
        sun_x, sun_y, _ = self.project_3d(0.0, 1.15, -1.2, cx, cy, scale)
        sun_grad = QRadialGradient(QPointF(sun_x, sun_y), 36.0)
        sun_grad.setColorAt(0.0, QColor(254, 249, 195, 255))
        sun_grad.setColorAt(0.5, QColor(251, 146, 60, 180))
        sun_grad.setColorAt(1.0, QColor(234, 88, 12, 0))
        p.setBrush(sun_grad)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(sun_x, sun_y), 36.0, 36.0)
        n_sky_sails = min(40, int(sails / 25))
        p.setBrush(QColor(56, 189, 248, 210))
        for i in range(n_sky_sails):
            a = self.anim_phase + i * (2.0 * math.pi / max(1, n_sky_sails))
            p.drawEllipse(QPointF(sun_x + math.cos(a) * 44.0, sun_y + math.sin(a) * 16.0), 2.2, 2.2)

    def _draw_solar_system_3d(self, p: QPainter, cx: float, cy: float, scale: float) -> None:
        s = self.state
        sails = float(s.get("active_solar_sails", 850.0))
        nodes = float(s.get("dyson_shell_nodes", 10.0))

        # 1. Central Star Helios
        sx, sy, _ = self.project_3d(0.0, 0.0, 0.0, cx, cy, scale)
        r_sun = 44.0 * self.cam_zoom
        sun_grad = QRadialGradient(QPointF(sx, sy), r_sun * 1.6)
        sun_grad.setColorAt(0.0, QColor(255, 255, 220, 255))
        sun_grad.setColorAt(0.35, QColor(251, 191, 36, 230))
        sun_grad.setColorAt(0.75, QColor(234, 88, 12, 110))
        sun_grad.setColorAt(1.0, QColor(234, 88, 12, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(sun_grad)
        p.drawEllipse(QPointF(sx, sy), r_sun * 1.6, r_sun * 1.6)

        # 2. 3 Inclined Dyson Swarm Rings around Helios
        n_sails_draw = min(140, max(16, int(sails / 18)))
        for i in range(n_sails_draw):
            ring_idx = i % 3
            ang = self.anim_phase * (1.2 - ring_idx * 0.25) + (i * 2.0 * math.pi / max(1, n_sails_draw))
            rad = 0.42 + ring_idx * 0.11
            tilt = (ring_idx - 1) * 0.48
            ox = rad * math.cos(ang)
            oy = rad * math.sin(ang) * math.sin(tilt)
            oz = rad * math.sin(ang) * math.cos(tilt)
            px, py, _ = self.project_3d(ox, oy, oz, cx, cy, scale)
            p.setBrush(QColor(56, 189, 248, 220) if ring_idx != 1 else QColor(250, 204, 21, 220))
            p.drawEllipse(QPointF(px, py), 2.5, 2.5)

        # 3. Planetary Orbits (Mercury, Venus, Earth, Mars)
        planets = [
            ("水星", 0.72, 1.9, QColor(148, 163, 184), 4.5),
            ("金星", 1.02, 1.25, QColor(251, 191, 36), 6.5),
            ("🌍 地球 (基地)", 1.38, 0.85, QColor(56, 189, 248), 8.5),
            ("火星", 1.72, 0.55, QColor(248, 113, 113), 6.0),
        ]
        earth_pos = (cx, cy)
        for name, orbit_r, speed, col, p_rad in planets:
            path = QPainterPath()
            for step in range(65):
                a = (2.0 * math.pi * step) / 64.0
                ox, oy, _ = self.project_3d(orbit_r * math.cos(a), 0.0, orbit_r * math.sin(a), cx, cy, scale)
                if step == 0:
                    path.moveTo(ox, oy)
                else:
                    path.lineTo(ox, oy)
            p.setPen(QPen(QColor(71, 85, 105, 110), 1.0, Qt.PenStyle.DotLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)

            pang = self.anim_phase * speed + orbit_r * 2.1
            px, py, _ = self.project_3d(orbit_r * math.cos(pang), 0.0, orbit_r * math.sin(pang), cx, cy, scale)
            if "地球" in name:
                earth_pos = (px, py)
            p.setPen(QPen(QColor(255, 255, 255, 180), 1.0))
            p.setBrush(col)
            p.drawEllipse(QPointF(px, py), p_rad, p_rad)
            p.setFont(QFont("SansSerif", 8, QFont.Weight.Bold))
            p.drawText(QPointF(px + 9, py + 4), name)

        # 4. Launch Beam from Earth to Dyson Swarm + Power Beam back to Earth
        ex, ey = earth_pos
        p.setPen(QPen(QColor(52, 211, 153, 180), 2.0, Qt.PenStyle.DashLine))
        p.drawLine(QPointF(ex, ey), QPointF(sx, sy))
        if nodes > 2:
            p.setPen(QPen(QColor(168, 85, 247, 170), 1.5))
            p.drawEllipse(QPointF(sx, sy), r_sun * 0.9, r_sun * 0.9)

    def _draw_dyson_shell_3d(self, p: QPainter, cx: float, cy: float, scale: float) -> None:
        s = self.state
        nodes_built = int(s.get("dyson_shell_nodes", 38))
        cov_pct = float(s.get("dyson_shell_coverage_pct", 12.5))

        sx, sy, _ = self.project_3d(0.0, 0.0, 0.0, cx, cy, scale)
        r_core = 65.0 * self.cam_zoom
        grad = QRadialGradient(QPointF(sx, sy), r_core * 1.4)
        grad.setColorAt(0.0, QColor(224, 242, 254, 255))
        grad.setColorAt(0.4, QColor(56, 189, 248, 220))
        grad.setColorAt(0.8, QColor(147, 51, 234, 140))
        grad.setColorAt(1.0, QColor(15, 23, 42, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(grad)
        p.drawEllipse(QPointF(sx, sy), r_core * 1.4, r_core * 1.4)

        # Project geodesic shell vertices
        proj_pts: List[Tuple[float, float, float, bool]] = []
        active_cnt = max(4, min(len(self._geodesic_nodes), int(len(self._geodesic_nodes) * (cov_pct / 100.0)) + nodes_built // 3))
        for idx, (nx, ny, nz) in enumerate(self._geodesic_nodes):
            ang = self.anim_phase * 0.35
            rx = nx * math.cos(ang) - nz * math.sin(ang)
            rz = nx * math.sin(ang) + nz * math.cos(ang)
            px, py, pz = self.project_3d(rx * 1.15, ny * 1.15, rz * 1.15, cx, cy, scale)
            proj_pts.append((px, py, pz, idx < active_cnt))

        # Draw geodesic struts between nearby nodes
        for i in range(len(proj_pts)):
            x1, y1, z1, act1 = proj_pts[i]
            for j in range(i + 1, len(proj_pts)):
                x2, y2, z2, act2 = proj_pts[j]
                dist_sq = (x1 - x2) ** 2 + (y1 - y2) ** 2
                if dist_sq < (72.0 * self.cam_zoom) ** 2:
                    if act1 and act2:
                        p.setPen(QPen(QColor(56, 189, 248, 175), 1.6))
                    else:
                        p.setPen(QPen(QColor(71, 85, 105, 70), 0.8, Qt.PenStyle.DotLine))
                    p.drawLine(QPointF(x1, y1), QPointF(x2, y2))

        for x1, y1, _, act in proj_pts:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(250, 204, 21, 240) if act else QColor(100, 116, 139, 110))
            r_pt = 4.2 if act else 2.2
            p.drawEllipse(QPointF(x1, y1), r_pt, r_pt)

    def _draw_kerr_blackhole_3d(self, p: QPainter, cx: float, cy: float, scale: float) -> None:
        """Stage 6: Kerr Black-Hole Penrose Generator + Relativistic Jets + Doppler Accretion Disk."""
        sx, sy, _ = self.project_3d(0.0, 0.0, 0.0, cx, cy, scale)

        # 1. Relativistic Polar Jets along Spin Axis (+Y / -Y)
        for sign_y in (-1.0, 1.0):
            jx, jy, _ = self.project_3d(0.0, sign_y * 1.65, 0.0, cx, cy, scale)
            jet_grad = QLinearGradient(sx, sy, jx, jy)
            jet_grad.setColorAt(0.0, QColor(224, 242, 254, 240))
            jet_grad.setColorAt(0.5, QColor(56, 189, 248, 180))
            jet_grad.setColorAt(1.0, QColor(147, 51, 234, 0))
            p.setPen(QPen(QBrush(jet_grad), 9.0 * self.cam_zoom, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(sx, sy), QPointF(jx, jy))

        # 2. Tilted Relativistic Accretion Disk (Blue-shifted left, Orange-shifted right)
        for ring in range(18):
            rad = 0.48 + ring * 0.055
            for seg in range(36):
                a1 = self.anim_phase * (2.2 - ring * 0.08) + (2.0 * math.pi * seg) / 36.0
                ox, oz = rad * math.cos(a1), rad * math.sin(a1)
                px, py, _ = self.project_3d(ox, 0.08 * math.sin(a1 * 2.0), oz, cx, cy, scale)
                col = QColor(56, 189, 248, 190) if ox < 0 else QColor(251, 146, 60, 190)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(col)
                p.drawEllipse(QPointF(px, py), 2.8, 2.8)

        # 3. Outer Penrose Ergosphere Mirror Cage Nodes
        for k, (nx, ny, nz) in enumerate(self._geodesic_nodes):
            ang = -self.anim_phase * 0.6
            rx = nx * math.cos(ang) - nz * math.sin(ang)
            rz = nx * math.sin(ang) + nz * math.cos(ang)
            px, py, _ = self.project_3d(rx * 1.15, ny * 0.85, rz * 1.15, cx, cy, scale)
            p.setBrush(QColor(250, 204, 21, 210))
            p.drawEllipse(QPointF(px, py), 3.2, 3.2)

        # 4. High-Density Semi-Transparent Hawking Nanomechanical Quantum Mesh tightly hugging the Black Hole Horizon
        r_eh = 38.0 * self.cam_zoom
        q_pts = []
        for idx, (nx, ny, nz) in enumerate(self._quantum_mesh_nodes):
            ang = self.anim_phase * 0.85
            rx = nx * math.cos(ang) - nz * math.sin(ang)
            rz = nx * math.sin(ang) + nz * math.cos(ang)
            # Radius 0.255 tightly hugs the Event Horizon & Photon Ring!
            px, py, pz = self.project_3d(rx * 0.255, ny * 0.255, rz * 0.255, cx, cy, scale)
            q_pts.append((px, py, pz))

        max_strut_dist_sq = (14.5 * self.cam_zoom) ** 2

        # 5. Gravitational Lensing Photon Ring & Pure-Black Event Horizon Shadow
        lens_grad = QRadialGradient(QPointF(sx, sy), r_eh * 1.45)
        lens_grad.setColorAt(0.0, QColor(0, 0, 0, 255))
        lens_grad.setColorAt(0.68, QColor(0, 0, 0, 255))
        lens_grad.setColorAt(0.76, QColor(254, 240, 138, 255))
        lens_grad.setColorAt(0.88, QColor(56, 189, 248, 180))
        lens_grad.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(lens_grad)
        p.drawEllipse(QPointF(sx, sy), r_eh * 1.45, r_eh * 1.45)

        # 6. Gossamer Semi-Transparent Front-Hemisphere Quantum Circuit Mesh hugging the Stretched Horizon
        for i in range(len(q_pts)):
            x1, y1, z1 = q_pts[i]
            if z1 < -0.02:
                continue
            for j in range(i + 1, len(q_pts)):
                x2, y2, z2 = q_pts[j]
                if z2 < -0.02:
                    continue
                if (x1 - x2) ** 2 + (y1 - y2) ** 2 < max_strut_dist_sq:
                    p.setPen(QPen(QColor(192, 132, 252, 72), 0.75))
                    p.drawLine(QPointF(x1, y1), QPointF(x2, y2))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(56, 189, 248, 130) if i % 2 == 0 else QColor(244, 63, 94, 120))
            p.drawEllipse(QPointF(x1, y1), 1.3, 1.3)

    def _draw_declarative_particle_manifold(self, p: QPainter, cx: float, cy: float, scale: float) -> None:
        """
        Evaluates & Renders the customizable High-Dimensional Particle Pipeline defined via
        a Sequence (`u in [0, 1)`) + `function_list` (Composable Basis Functions, zero raw code required!).
        """
        prog = self.custom_particle_program
        if not isinstance(prog, dict) or not prog.get("enabled", True):
            return
        fn_list = prog.get("function_list", [])
        if not isinstance(fn_list, list) or not fn_list:
            return

        n_pts = max(16, min(1200, int(prog.get("particle_count", 320))))
        stride = max(0, int(prog.get("connect_stride", 7)))
        palette_hex = prog.get("color_palette", ["#38bdf8", "#e879f9", "#facc15"])
        if not palette_hex:
            palette_hex = ["#38bdf8"]
        palette = [QColor(c) for c in palette_hex]

        dim_exp = 1.0
        if self.state and isinstance(self.state.get("params"), dict):
            dim_exp = float(self.state["params"].get("dimensional_exponent", 1.0))
        dim_scale = min(2.4, 0.85 + 0.18 * math.log1p(max(0.5, dim_exp)))

        t = self.anim_phase
        proj_coords: List[Tuple[float, float, float, QColor]] = []

        for i in range(n_pts):
            u = i / float(n_pts)
            theta = 2.0 * math.pi * u
            phi = 2.0 * math.pi * ((i * 0.61803398875) % 1.0)
            x, y, z = 0.0, 0.0, 0.0

            # Sequentially pipe (u, theta, phi, t) through every basis operator in `function_list`!
            for step in fn_list:
                if not isinstance(step, dict):
                    continue
                fn_name = str(step.get("fn", "")).strip().lower()
                spd = float(step.get("speed", 1.0))
                phase = t * spd

                if fn_name == "torus_knot":
                    kp = float(step.get("p", 3.0))
                    kq = float(step.get("q", 7.0))
                    rad = float(step.get("radius", 1.2))
                    tube = float(step.get("tube", 0.3))
                    r_k = rad + tube * math.cos(kq * theta + phase)
                    x += r_k * math.cos(kp * theta + phase * 0.4)
                    z += r_k * math.sin(kp * theta + phase * 0.4)
                    y += tube * math.sin(kq * theta + phase)

                elif fn_name == "calabi_yau_fold":
                    nf = float(step.get("n_fold", 6.0))
                    amp = float(step.get("amp", 0.24))
                    x += amp * math.cos(nf * theta + phase) * math.cos(phi)
                    y += amp * math.sin(nf * theta - phase) * math.sin(phi)
                    z += amp * math.sin((nf * 0.5) * (theta + phi) + phase)

                elif fn_name == "hypersphere_4d":
                    rad4 = float(step.get("radius", 1.15))
                    w_spd = float(step.get("w_speed", 1.3))
                    proj_d = max(1.3, float(step.get("proj_d", 2.1)))
                    # 4D Clifford Torus (x4, y4, z4, w4) rotated in XW & YZ planes then stereographically projected
                    a1 = theta + t * w_spd
                    a2 = phi - t * w_spd * 0.7
                    x4 = math.cos(a1) / math.sqrt(2.0)
                    y4 = math.sin(a1) / math.sqrt(2.0)
                    z4 = math.cos(a2) / math.sqrt(2.0)
                    w4 = math.sin(a2) / math.sqrt(2.0)
                    rot_w = t * 0.8 * w_spd
                    xw = x4 * math.cos(rot_w) - w4 * math.sin(rot_w)
                    ww = x4 * math.sin(rot_w) + w4 * math.cos(rot_w)
                    s4 = rad4 / max(0.35, proj_d - ww)
                    x += xw * s4
                    y += y4 * s4
                    z += z4 * s4

                elif fn_name == "wormhole_throat":
                    tr = float(step.get("throat_r", 0.52))
                    fl = float(step.get("flare", 0.85))
                    ht = float(step.get("height", 1.35))
                    v_h = (u * 2.0 - 1.0) * ht
                    r_wh = tr * math.cosh(v_h * fl)
                    ang_w = phi * 3.0 + phase + v_h * 1.8
                    x += r_wh * math.cos(ang_w)
                    z += r_wh * math.sin(ang_w)
                    y += v_h

                elif fn_name == "ctc_time_loop":
                    loops = float(step.get("loops", 3.0))
                    rad_c = float(step.get("radius", 1.35))
                    tw = float(step.get("twist_speed", 1.5))
                    # Closed Timelike Curve (Lemniscate / Möbius Temporal Ribbon in 3D)
                    ang_c = theta + t * tw * 0.5
                    denom = 1.0 + math.sin(ang_c) ** 2
                    lx = rad_c * math.cos(ang_c) / denom
                    lz = rad_c * math.sin(ang_c) * math.cos(ang_c) / denom
                    ly = 0.38 * math.sin(loops * ang_c + t * tw)
                    x += lx
                    y += ly
                    z += lz

                elif fn_name == "hopf_fibration":
                    eta_h = float(step.get("eta", 0.7))
                    sc_h = float(step.get("scale", 0.25))
                    xi1 = theta + phase
                    xi2 = phi - phase * 0.6
                    denom_h = max(0.35, 1.0 - math.cos(eta_h) * math.sin(xi1))
                    x += sc_h * (math.sin(eta_h) * math.cos(xi2)) / denom_h
                    y += sc_h * (math.sin(eta_h) * math.sin(xi2)) / denom_h
                    z += sc_h * (math.cos(eta_h) * math.cos(xi1)) / denom_h

                elif fn_name == "vacuum_foam_pulse":
                    freq = float(step.get("freq", 8.0))
                    amp_v = float(step.get("amp", 0.10))
                    if step.get("use_dim_exponent", True):
                        amp_v *= dim_scale
                    wave = math.sin(freq * theta + phase * 2.2) * math.cos(freq * 0.5 * phi - phase)
                    r_norm = math.sqrt(x * x + y * y + z * z)
                    if r_norm > 1e-4:
                        x += (x / r_norm) * amp_v * wave
                        y += (y / r_norm) * amp_v * wave
                        z += (z / r_norm) * amp_v * wave
                    else:
                        x += amp_v * wave

                elif fn_name == "lorentz_twist":
                    strength = float(step.get("strength", 0.5))
                    axis = str(step.get("axis", "y")).lower()
                    ang_tw = (y if axis == "y" else (z if axis == "z" else x)) * strength + phase * 0.3
                    ca, sa = math.cos(ang_tw), math.sin(ang_tw)
                    if axis == "y":
                        x, z = x * ca - z * sa, x * sa + z * ca
                    elif axis == "z":
                        x, y = x * ca - y * sa, x * sa + y * ca
                    else:
                        y, z = y * ca - z * sa, y * sa + z * ca

            px, py, pz = self.project_3d(x, y, z, cx, cy, scale)
            col = palette[i % len(palette)]
            proj_coords.append((px, py, pz, col))

        # Draw High-Dimensional Phase Filaments (Connect Stride)
        if stride > 0 and len(proj_coords) > stride:
            for i in range(len(proj_coords)):
                x1, y1, z1, c1 = proj_coords[i]
                x2, y2, z2, _ = proj_coords[(i + stride) % len(proj_coords)]
                line_col = QColor(c1.red(), c1.green(), c1.blue(), 75)
                p.setPen(QPen(line_col, 0.9))
                p.drawLine(QPointF(x1, y1), QPointF(x2, y2))

        # Draw High-Dimensional Quantum Particles
        for px, py, pz, col in proj_coords:
            p.setPen(Qt.PenStyle.NoPen)
            pt_col = QColor(col.red(), col.green(), col.blue(), 215 if pz >= 0 else 125)
            p.setBrush(pt_col)
            r_sz = (2.8 if pz >= 0 else 1.8) * self.cam_zoom
            p.drawEllipse(QPointF(px, py), r_sz, r_sz)

    def _draw_ascension_transition_overlay(self, p: QPainter, w: float, h: float, cx: float, cy: float) -> None:
        """Renders the 3.5-second Stage Ascension Warp Transition Ceremony (Implosion -> Brane Flash -> Decree)."""
        prog = 1.0 - (self.ascension_anim_frames / float(max(1, self.ascension_total_frames)))
        max_r = math.hypot(w, h) * 0.65

        # 1. Radial Hyperspace Warp Streaks & Expanding Brane Shockwave Rings
        for ring_i in range(4):
            r_prog = (prog * 1.35 - ring_i * 0.14) % 1.0
            if r_prog > 0.0:
                rad = r_prog * max_r
                alpha = int(max(0.0, (1.0 - r_prog) * 220))
                col = QColor(250, 204, 21, alpha) if ring_i % 2 == 0 else QColor(56, 189, 248, alpha)
                p.setPen(QPen(col, 3.2 * (1.0 - r_prog * 0.5)))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(QPointF(cx, cy), rad, rad)

        # 2. Singularity Core Supernova Flash at peak (prog ~ 0.30)
        flash_intensity = max(0.0, 1.0 - abs(prog - 0.32) / 0.25)
        if flash_intensity > 0.0:
            fl_grad = QRadialGradient(QPointF(cx, cy), max_r * 0.85)
            fl_grad.setColorAt(0.0, QColor(255, 255, 255, int(235 * flash_intensity)))
            fl_grad.setColorAt(0.35, QColor(192, 132, 252, int(170 * flash_intensity)))
            fl_grad.setColorAt(1.0, QColor(0, 0, 0, 0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(fl_grad)
            p.drawRect(QRectF(0, 0, w, h))

        # 3. Holographic Ascension Ceremony Banner in Center
        banner_alpha = int(min(1.0, min(prog * 4.0, (1.0 - prog) * 3.2)) * 240)
        if banner_alpha > 20:
            bw = min(w - 60, 760.0)
            bh = 138.0
            bx, by = cx - bw * 0.5, cy - bh * 0.5
            p.setBrush(QColor(10, 15, 35, banner_alpha))
            p.setPen(QPen(QColor(250, 204, 21, banner_alpha), 2.4))
            p.drawRoundedRect(QRectF(bx, by, bw, bh), 12, 12)

            p.setFont(QFont("SansSerif", 11, QFont.Weight.Bold))
            p.setPen(QColor(56, 189, 248, banner_alpha))
            p.drawText(
                QRectF(bx + 16, by + 12, bw - 32, 26),
                Qt.AlignmentFlag.AlignCenter,
                f"⚡ DIMENSIONAL ASCENSION CEREMONY : STAGE {self.ascension_from_stage} ➔ STAGE {self.ascension_to_stage} ⚡",
            )

            p.setFont(QFont("SansSerif", 14, QFont.Weight.Bold))
            p.setPen(QColor(254, 240, 138, banner_alpha))
            p.drawText(
                QRectF(bx + 16, by + 42, bw - 32, 32),
                Qt.AlignmentFlag.AlignCenter,
                self.ascension_title or f"Stage {self.ascension_to_stage} 超維躍遷啟動",
            )

            if self.ascension_lore:
                p.setFont(QFont("SansSerif", 9))
                p.setPen(QColor(226, 232, 240, banner_alpha))
                lore_short = self.ascension_lore if len(self.ascension_lore) <= 92 else self.ascension_lore[:90] + "..."
                p.drawText(
                    QRectF(bx + 22, by + 78, bw - 44, 48),
                    Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                    f"📜 「{lore_short}」",
                )

    def _draw_matrioshka_cluster_3d(self, p: QPainter, cx: float, cy: float, scale: float) -> None:
        """Stage 5: 3-Layer Nested Matrioshka Brain Shells + Interstellar Warp Grid to Neighbor Stars."""
        self._draw_dyson_shell_3d(p, cx, cy, scale * 0.65)
        sx, sy, _ = self.project_3d(0.0, 0.0, 0.0, cx, cy, scale)

        # Draw Outer Nested Matrioshka Computing Shells (Layers 2 & 3)
        for layer_idx, (rad_m, speed_m, col) in enumerate([
            (1.32, -0.45, QColor(52, 211, 153, 180)),
            (1.68, 0.28, QColor(232, 121, 249, 175)),
        ]):
            ang = self.anim_phase * speed_m
            for k in range(0, len(self._geodesic_nodes), 2):
                nx, ny, nz = self._geodesic_nodes[k]
                rx = nx * math.cos(ang) - nz * math.sin(ang)
                rz = nx * math.sin(ang) + nz * math.cos(ang)
                px, py, _ = self.project_3d(rx * rad_m, ny * rad_m, rz * rad_m, cx, cy, scale)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(col)
                p.drawEllipse(QPointF(px, py), 3.2, 3.2)

        # Interstellar Warp Relay Beams to Neighboring Star Systems (Alpha Centauri / Sirius / Vega)
        sister_stars = [
            ("✨ 半人馬座 α (Warp Node)", -1.55, 0.65, -0.5, QColor(56, 189, 248)),
            ("✨ 天狼星 B (Neutron Forge)", 1.58, -0.55, 0.4, QColor(250, 204, 21)),
            ("✨ 織女星 (Matrioshka Link)", 0.45, 1.35, -0.8, QColor(232, 121, 249)),
        ]
        p.setFont(QFont("SansSerif", 8, QFont.Weight.Bold))
        for s_name, ox, oy, oz, scol in sister_stars:
            tx, ty, _ = self.project_3d(ox, oy, oz, cx, cy, scale)
            p.setPen(QPen(scol, 2.2, Qt.PenStyle.DashDotLine))
            p.drawLine(QPointF(sx, sy), QPointF(tx, ty))
            p.setBrush(scol)
            p.setPen(QPen(QColor(255, 255, 255), 1.2))
            p.drawEllipse(QPointF(tx, ty), 8.0, 8.0)
            p.setPen(scol.lighter(135))
            p.drawText(QPointF(tx + 10, ty + 4), s_name)

    def _draw_lorenz_attractor_3d(self, p: QPainter, cx: float, cy: float, scale: float) -> None:
        # 1. Draw 3D Phase-Space Axes & Wing Attractor Centers
        axes = [
            ((-1.5, 0.0, 0.0), (1.5, 0.0, 0.0), "X: 電網淨通量 (左翼災難 ◄─► 右翼正循環)", QColor(56, 189, 248, 130)),
            ((0.0, -1.2, 0.0), (0.0, 1.2, 0.0), "Z: AI 負熵調控高度 / EROEI", QColor(168, 85, 247, 130)),
            ((0.0, 0.0, -1.4), (0.0, 0.0, 1.4), "Y: 化工熵壓 (H2% 梯度)", QColor(251, 191, 36, 130)),
        ]
        p.setFont(QFont("SansSerif", 8, QFont.Weight.Bold))
        for (x1, y1, z1), (x2, y2, z2), lbl, col in axes:
            sx1, sy1, _ = self.project_3d(x1, y1, z1, cx, cy, scale)
            sx2, sy2, _ = self.project_3d(x2, y2, z2, cx, cy, scale)
            p.setPen(QPen(col, 1.2, Qt.PenStyle.DashLine))
            p.drawLine(QPointF(sx1, sy1), QPointF(sx2, sy2))
            p.setPen(col.lighter(135))
            p.drawText(QPointF(sx2 + 6, sy2), lbl)

        # Draw Left & Right Wing Attractor Cores
        for wx, wy, wz, wlbl, wcol in [
            (0.65, 0.10, 0.45, "🟢 右翼: 正循環吸引中心", QColor(52, 211, 153, 180)),
            (-0.65, -0.10, -0.45, "🔴 左翼: 死鎖/雪崩吸引中心", QColor(244, 63, 94, 180)),
        ]:
            px, py, _ = self.project_3d(wx, wy, wz, cx, cy, scale)
            grad = QRadialGradient(QPointF(px, py), 26.0 * self.cam_zoom)
            grad.setColorAt(0.0, wcol)
            grad.setColorAt(1.0, QColor(0, 0, 0, 0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(grad)
            p.drawEllipse(QPointF(px, py), 26.0 * self.cam_zoom, 26.0 * self.cam_zoom)
            p.setPen(wcol.lighter(130))
            p.drawText(QPointF(px - 45, py - 14), wlbl)

        # 2. Draw 3D Lorenz Trajectory Ribbon & AI Intervention Saddle Stars
        n_pts = len(self.phase_trail)
        if n_pts >= 2:
            prev_sx, prev_sy, _ = self.project_3d(
                self.phase_trail[0][0], self.phase_trail[0][1], self.phase_trail[0][2], cx, cy, scale
            )
            for i in range(1, n_pts):
                nx, ny, nz, st, is_crisis, ai_star, _ = self.phase_trail[i]
                sx, sy, _ = self.project_3d(nx, ny, nz, cx, cy, scale)
                alpha = int(45 + 210 * (i / float(n_pts)))
                width = 1.2 + 1.8 * (i / float(n_pts))
                if is_crisis:
                    col = QColor(244, 63, 94, alpha)
                elif st == 1:
                    col = QColor(56, 189, 248, alpha)
                elif st == 2:
                    col = QColor(52, 211, 153, alpha)
                elif st == 3:
                    col = QColor(250, 204, 21, alpha)
                else:
                    col = QColor(192, 132, 252, alpha)
                p.setPen(QPen(col, width))
                p.drawLine(QPointF(prev_sx, prev_sy), QPointF(sx, sy))
                if ai_star:
                    p.setPen(QPen(QColor(255, 255, 255, 230), 1.2))
                    p.setBrush(QColor(250, 204, 21, 245))
                    p.drawEllipse(QPointF(sx, sy), 5.5, 5.5)
                prev_sx, prev_sy = sx, sy

            # Current Phase Head Pulse
            p.setPen(QPen(QColor(255, 255, 255), 2.0))
            p.setBrush(QColor(56, 189, 248))
            p.drawEllipse(QPointF(prev_sx, prev_sy), 7.0, 7.0)

    def _draw_hud_overlay(self, p: QPainter, w: float, h: float) -> None:
        s = self.state
        if not s:
            return
        p.setFont(QFont("SansSerif", 10, QFont.Weight.Bold))
        mode_names = {
            "earth_25d": "🌍 視角: 地球赤道基地 (2.5D/3D Planetary Grid)",
            "solar_3d": "☀️ 視角: 太陽系戴森雲軌道 (3D Solar System)",
            "dyson_shell_3d": "🪐 視角: 恆星級戴森球測地線殼面 (3D Geodesic Shell)",
            "matrioshka_3d": "🌌 視角: Stage 5 俄羅斯套娃腦與跨星系曲速網格 (3D Matrioshka Cluster)",
            "blackhole_3d": "🕳️ 視角: Stage 6 克爾黑洞彭羅斯發電機與相對論噴流 (3D Kerr Black Hole)",
            "lorenz_3d": "🦋 視角: 3D 勞倫茲雙翼相空間吸引子 (Lorenz Strange Attractor | ⭐金點=AI控制介入)",
        }
        p.setPen(QColor(56, 189, 248))
        p.drawText(QPointF(14, 24), f"{mode_names.get(self.view_mode, '')}  |  🖱️ 左鍵拖曳 3D 旋轉 / 滾輪縮放")

        # Lockstep AI Sync Status Banner + Stage EXP Energy Bar
        exp_pct = float(s.get("stage_exp_pct", 0.0))
        exp_rate = float(s.get("stage_exp_rate_per_tick", 0.0))
        banner_rect = QRectF(14, 34, w - 28, 30)
        if self.is_paused_for_ai:
            p.setBrush(QColor(124, 45, 18, 210))
            p.setPen(QPen(QColor(251, 191, 36), 1.5))
            p.drawRoundedRect(banner_rect, 6, 6)
            p.setPen(QColor(254, 240, 138))
            p.drawText(
                QPointF(24, 54),
                f"⏸️ [HEARTBEAT SYNC PAUSED @ Tick #{s.get('tick', 0)} | EXP {exp_pct:.1f}%] 等待地端 31B + 16-LoRA 依據能量條進度微調參數百分比...",
            )
        else:
            p.setBrush(QColor(15, 23, 42, 185))
            p.setPen(QPen(QColor(52, 211, 153), 1.2))
            p.drawRoundedRect(banner_rect, 6, 6)
            p.setPen(QColor(167, 243, 208))
            p_val = float(s.get("p_gen_mw", 0.0))
            p_str = f"{p_val:.3e}" if abs(p_val) >= 1e9 else f"{p_val:,.1f}"
            er_val = float(s.get("eroei", 1.0))
            er_str = f"{er_val:.3e}" if abs(er_val) >= 1e9 else f"{er_val:,.2f}"
            p.drawText(
                QPointF(24, 54),
                f"▶️ [DYNAMIC TICK #{s.get('tick', 0)}]  P_gen={p_str} MW  |  供電率 η={s.get('grid_satisfaction', 1)*100:.0f}%  |  EROEI={er_str}",
            )

        # Draw Stage Ascension EXP Energy Bar right below the status banner!
        exp_bg_rect = QRectF(14, 70, w - 28, 22)
        p.setBrush(QColor(15, 23, 42, 210))
        p.setPen(QPen(QColor(56, 189, 248, 180), 1.2))
        p.drawRoundedRect(exp_bg_rect, 5, 5)
        fill_w = max(0.0, (w - 32) * min(1.0, exp_pct / 100.0))
        if fill_w > 1.0:
            exp_grad = QLinearGradient(16, 72, 16 + fill_w, 72)
            exp_grad.setColorAt(0.0, QColor(14, 165, 233, 230))
            exp_grad.setColorAt(0.6, QColor(52, 211, 153, 230))
            exp_grad.setColorAt(1.0, QColor(250, 204, 21, 240))
            p.setBrush(exp_grad)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(QRectF(16, 72, fill_w, 18), 4, 4)
        p.setPen(QColor(255, 255, 255))
        p.setFont(QFont("SansSerif", 9, QFont.Weight.Bold))
        p.drawText(
            QPointF(24, 85),
            f"🌟 Stage {s.get('stage', 1)} 躍遷經驗能量條 (EXP Bar): {exp_pct:.1f}% / 100.0%  ({exp_rate:+.2f}% / tick — 滿格自動晉升下一階段!)",
        )

        # Active Alerts Overlay at Bottom of Viewport
        alerts = s.get("active_alerts", [])
        if alerts:
            ay = h - 18 - len(alerts) * 22
            p.setBrush(QColor(69, 10, 10, 210))
            p.setPen(QPen(QColor(244, 63, 94), 1.5))
            p.drawRoundedRect(QRectF(14, ay - 18, w - 28, len(alerts) * 22 + 12), 6, 6)
            p.setPen(QColor(254, 202, 202))
            p.setFont(QFont("SansSerif", 9, QFont.Weight.Bold))
            for idx, al in enumerate(alerts):
                p.drawText(QPointF(24, ay + idx * 22), al)
