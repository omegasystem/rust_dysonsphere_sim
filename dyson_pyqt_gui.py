#!/usr/bin/env python3
"""
dyson_pyqt_gui.py - Standalone PyQt6 2.5D~3D Dyson Sphere Simulator & Lockstep AI Console
==========================================================================================
Features:
  - Left/Center: `DysonCosmos3DViewport` (2.5D Earth Base <-> 3D Solar System <-> 3D Dyson Shell)
  - Top Bar: Stage Selector (Stage 1..4), View Switcher, Tick Speed, Chaos Fault Injection Buttons
  - Right Panel:
      * Live Thermodynamic Telemetry & Dynamic Control Parameter Sliders (updated by AI!)
      * TCP Lockstep Sync Server (`127.0.0.1:18960`) Status & Auto-Pause on Inference Sync
      * Real-Time AI Reasoning Stream & Parsed `<dyson_action>` Parameter Diff Log
"""

import datetime
import json
import sys
from pathlib import Path
from typing import Any, Dict

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from dyson_sim_engine import (
    STAGE_METADATA,
    DysonActionParser,
    DysonDynamicSimulator,
    register_ai_genesis_stage,
    reset_stage_list_to_base_6,
)
from tcp_lockstep_protocol import DEFAULT_TCP_HOST, DEFAULT_TCP_PORT, DysonTcpSyncServer
from viewport_3d import DysonCosmos3DViewport
from dyson_telemetry_db import DysonTelemetryDB, backfill_jsonl_sessions_to_db, batch_export_all_legacy_sessions


def fmt_num(val: Any, decimals: int = 1) -> str:
    """Formats numbers >= 10 digits (1e9) in compact scientific notation so UI never overflows!"""
    try:
        v = float(val)
    except Exception:
        return str(val)
    if abs(v) >= 1e9:
        return f"{v:.3e}"
    if decimals <= 0:
        return f"{v:,.0f}"
    return f"{v:,.{decimals}f}"


class DysonSphereSimWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.sim = DysonDynamicSimulator()
        self.tcp_server = DysonTcpSyncServer(host=DEFAULT_TCP_HOST, port=DEFAULT_TCP_PORT)
        self.tcp_server.start()

        # Automatic Session Recorder (`rust_dysonsphere_sim/sessions/`) & Save Dir (`saves/`)
        self.sess_dir = BASE_DIR / "sessions"
        self.sess_dir.mkdir(parents=True, exist_ok=True)
        self.saves_dir = BASE_DIR / "saves"
        self.saves_dir.mkdir(parents=True, exist_ok=True)
        ts_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.session_id = ts_str
        self.session_md_path = self.sess_dir / f"dyson_session_{ts_str}.md"
        self.session_jsonl_path = self.sess_dir / f"dyson_session_{ts_str}.jsonl"
        self._append_session_md(f"# 🪐 Dyson Sphere Dynamic Simulator Session ({ts_str})\n\n")

        # High-Performance RAM-Buffered Telemetry DB (Redis RAM + Pure-RAM Ring Buffer + Batch SQLite WAL)
        self.telemetry_db_path = self.sess_dir / "dyson_telemetry.db"
        try:
            batch_export_all_legacy_sessions(self.sess_dir, self.telemetry_db_path, max_excel_rows=1500)
        except Exception:
            pass
        self.telemetry_db = DysonTelemetryDB(
            db_path=self.telemetry_db_path,
            session_id=self.session_id,
            flush_every_n_ticks=500,  # Zero disk I/O during normal ticks; batch flush only every 500 ticks or on Stage/AI event!
        )

        self.sim_running: bool = True
        self.paused_waiting_ai: bool = False
        self.awaiting_initial_ai_action: bool = True
        self.sync_interval_ticks: int = 100
        self.ticks_since_last_sync: int = 0
        self.scheduled_action_queue: list = []
        self._updating_sliders: bool = False

        self.setWindowTitle(
            f"🪐 rust_dysonsphere_sim — 戴森球計畫 2.5D/3D 熱力學動態模擬器 [{self.sim.backend_name}] | TCP Sync :{DEFAULT_TCP_PORT}"
        )
        self.resize(1560, 920)
        self._apply_dark_theme()
        self._build_ui()

        # Simulation Physics Timer (10 Hz default)
        self.sim_timer = QTimer(self)
        self.sim_timer.timeout.connect(self._on_sim_tick)
        self.sim_timer.start(100)

        # TCP Event Poll Timer (30 Hz)
        self.tcp_timer = QTimer(self)
        self.tcp_timer.timeout.connect(self._poll_tcp_events)
        self.tcp_timer.start(35)

        self._refresh_ui_from_state(self.sim.get_state())

    def _apply_dark_theme(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background-color: #070d19; color: #e2e8f0; font-family: 'Segoe UI', 'Microsoft JhengHei', sans-serif; }
            QGroupBox { border: 1px solid #1e293b; border-radius: 6px; margin-top: 8px; padding-top: 10px; font-weight: bold; color: #38bdf8; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
            QPushButton { background-color: #1e293b; color: #f8fafc; border: 1px solid #334155; border-radius: 4px; padding: 5px 10px; font-weight: bold; }
            QPushButton:hover { background-color: #334155; border-color: #38bdf8; }
            QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit { background-color: #0f172a; color: #e2e8f0; border: 1px solid #334155; border-radius: 4px; padding: 3px; }
            """
        )

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root_v = QVBoxLayout(central)

        # Top Control Ribbon
        top_bar = QHBoxLayout()
        self.btn_play_pause = QPushButton("⏸️ 暫停模擬")
        self.btn_play_pause.clicked.connect(self._toggle_play_pause)
        top_bar.addWidget(self.btn_play_pause)

        top_bar.addWidget(QLabel("🎯 任務階段:"))
        self.cmb_stage = QComboBox()
        self.cmb_stage.setMaximumWidth(380)
        self._refresh_stage_combobox()
        self.cmb_stage.currentIndexChanged.connect(self._on_stage_selected)
        top_bar.addWidget(self.cmb_stage)

        top_bar.addWidget(QLabel("🎥 2.5D/3D 視角:"))
        self.cmb_camera = QComboBox()
        self.cmb_camera.addItem("🔀 自動跟隨階段 (Auto Stage)", "auto")
        self.cmb_camera.addItem("🌍 地球赤道基地 (2.5D/3D Planetary)", "earth_25d")
        self.cmb_camera.addItem("☀️ 太陽系戴森雲軌道 (3D Solar System)", "solar_3d")
        self.cmb_camera.addItem("🪐 恆星級戴森球殼 (3D Geodesic Shell)", "dyson_shell_3d")
        self.cmb_camera.addItem("🌌 俄羅斯套娃腦與跨星系曲速網 (3D Matrioshka)", "matrioshka_3d")
        self.cmb_camera.addItem("🕳️ 克爾黑洞彭羅斯發電機 (3D Kerr Black Hole)", "blackhole_3d")
        self.cmb_camera.addItem("🦋 3D 勞倫茲相空間吸引子 (固定視角)", "lorenz_3d")
        self.cmb_camera.currentIndexChanged.connect(self._on_camera_changed)
        top_bar.addWidget(self.cmb_camera)

        btn_save = QPushButton("💾 存檔進度")
        btn_save.setStyleSheet("background-color: #0f766e; color: white;")
        btn_save.clicked.connect(lambda: self._save_game_checkpoint(auto=False))
        top_bar.addWidget(btn_save)

        btn_load = QPushButton("📂 讀檔續關 (Latest)")
        btn_load.setStyleSheet("background-color: #4338ca; color: white;")
        btn_load.clicked.connect(self._load_game_checkpoint)
        top_bar.addWidget(btn_load)

        btn_crunch = QPushButton("💥 歸檔&大坍縮重啟 (Stage 25 Auto)")
        btn_crunch.setStyleSheet("background-color: #be123c; color: white; font-weight: bold;")
        btn_crunch.clicked.connect(lambda: self._trigger_big_crunch_epoch_reset("手動觸發宇宙大坍縮與新紀元大爆炸"))
        top_bar.addWidget(btn_crunch)

        top_bar.addWidget(QLabel("⏱️ AI 同步週期(Ticks):"))
        self.spn_sync_ticks = QSpinBox()
        self.spn_sync_ticks.setRange(5, 10000)
        self.spn_sync_ticks.setValue(100)
        self.spn_sync_ticks.valueChanged.connect(lambda v: setattr(self, "sync_interval_ticks", int(v)))
        top_bar.addWidget(self.spn_sync_ticks)

        top_bar.addWidget(QLabel("🧠 推論耗電係數(MWh/s):"))
        self.spn_ai_cost_coeff = QDoubleSpinBox()
        self.spn_ai_cost_coeff.setRange(0.0, 5000.0)
        self.spn_ai_cost_coeff.setSingleStep(2.0)
        self.spn_ai_cost_coeff.setDecimals(1)
        self.spn_ai_cost_coeff.setValue(10.0)
        self.spn_ai_cost_coeff.setStyleSheet("color: #f43f5e; font-weight: bold;")
        top_bar.addWidget(self.spn_ai_cost_coeff)

        self.chk_auto_stage = QCheckBox("🔓 達標自動晉升階段")
        self.chk_auto_stage.setChecked(True)
        self.chk_auto_stage.toggled.connect(self._on_toggle_auto_stage)
        top_bar.addWidget(self.chk_auto_stage)

        self.chk_auto_ai_sync = QCheckBox("🔗 Lockstep 自動同步")
        self.chk_auto_ai_sync.setChecked(True)
        top_bar.addWidget(self.chk_auto_ai_sync)

        self.chk_compact_mode = QCheckBox("⚡ 極速精簡模式 (預設ON / 關掉看完整作文)")
        self.chk_compact_mode.setChecked(True)
        self.chk_compact_mode.setStyleSheet("color: #facc15; font-weight: bold;")
        top_bar.addWidget(self.chk_compact_mode)

        self.chk_mining_econ = QCheckBox("⛏️ 基建&採礦耗材閉環")
        self.chk_mining_econ.setChecked(True)
        self.chk_mining_econ.setToolTip("開啟時：蓋基建需消耗原材料（隨 EXP% 級數增加），需調配 mining_rig_build_rate 增產採礦機；關閉時：免耗材直接擴建基建。")
        self.chk_mining_econ.setStyleSheet("color: #38bdf8; font-weight: bold;")
        self.chk_mining_econ.toggled.connect(self._on_toggle_mining_economy)
        top_bar.addWidget(self.chk_mining_econ)

        btn_force_sync = QPushButton("⚡ 立即請求 AI 決策 (Pause & Sync)")
        btn_force_sync.setStyleSheet("background-color: #0284c7; color: white;")
        btn_force_sync.clicked.connect(lambda: self._trigger_ai_lockstep_sync(reason="手動觸發同步"))
        top_bar.addWidget(btn_force_sync)

        btn_export_csv = QPushButton("📊 匯出全維度曲線 CSV")
        btn_export_csv.setToolTip(
            "平時 65 維度曲線全數駐留於 RAM Ring-Buffer / Redis 記憶體（零磁碟 I/O），點擊可一鍵匯出為 CSV 供畫圖與效益分析！"
        )
        btn_export_csv.setStyleSheet("background-color: #0f766e; color: white;")
        btn_export_csv.clicked.connect(self._on_export_telemetry_csv_clicked)
        top_bar.addWidget(btn_export_csv)

        root_v.addLayout(top_bar)

        # Chaos Fault Injection Bar
        fault_bar = QHBoxLayout()
        fault_bar.addWidget(QLabel("☄️ 太空災難與死鎖注入測試:"))
        for lbl, f_code, col in [
            ("☄️ 注入微隕石沙塵暴 + 電網雪崩", "brownout", "#b91c1c"),
            ("🧪 注入氫氣儲槽 99.8% 滿倉死鎖", "h2_deadlock", "#b45309"),
            ("☢️ 注入太陽閃焰 SEU 參數翻轉", "seu_bitflip", "#6d28d9"),
            ("🟢 清除災難 / 恢復穩態緩衝", "clear", "#047857"),
        ]:
            b = QPushButton(lbl)
            b.setStyleSheet(f"background-color: {col}; color: white; padding: 4px 8px;")
            b.clicked.connect(lambda checked=False, fc=f_code: self._inject_fault(fc))
            fault_bar.addWidget(b)
        root_v.addLayout(fault_bar)

        # Main Splitter: Left 3D Viewport | Right Telemetry & AI Bridge Console
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.viewport = DysonCosmos3DViewport()
        splitter.addWidget(self.viewport)

        right_panel = QWidget()
        right_panel.setMinimumWidth(480)
        right_panel.setMaximumWidth(680)
        rv = QVBoxLayout(right_panel)

        # 1. TCP & Lockstep Status Box
        grp_tcp = QGroupBox(f"🔌 AI 推論即時 TCP 同步通道 (127.0.0.1:{DEFAULT_TCP_PORT})")
        tcp_v = QVBoxLayout(grp_tcp)
        self.lbl_tcp_status = QLabel("🟡 等待地端 AI 橋接器連線 (`run_moe_bridge.sh` 或 `rust_localsleep-moe`)...")
        self.lbl_lockstep_state = QLabel("▶️ 模擬器狀態: RUNNING")
        tcp_v.addWidget(self.lbl_tcp_status)
        tcp_v.addWidget(self.lbl_lockstep_state)
        rv.addWidget(grp_tcp)

        # 2. Telemetry Summary Box
        grp_tele = QGroupBox("📊 星系熱力學與產線即時遙測")
        self.lbl_telemetry = QLabel("載入中...")
        self.lbl_telemetry.setWordWrap(True)
        grp_tele_l = QVBoxLayout(grp_tele)
        grp_tele_l.addWidget(self.lbl_telemetry)
        rv.addWidget(grp_tele)

        # 3. Dynamic System Control Parameters (AI-Controlled & Manual Override)
        grp_params = QGroupBox("🎛️ 動態系統控制參數 (AI Parse 自動更新 / 可手動微調)")
        form = QFormLayout(grp_params)
        self.param_spins: Dict[str, QDoubleSpinBox] = {}
        for key, label, lo, hi, step in [
            ("coal_throttle", "🔥 火力發電節流閥 (0~1.5)", 0.0, 1.5, 0.05),
            ("fusion_throttle", "⚛️ 重氫聚變節流閥 (0~1.5)", 0.0, 1.5, 0.05),
            ("antimatter_throttle", "☀️ 反物質太陽節流閥 (0~1.5)", 0.0, 1.5, 0.05),
            ("load_shed_non_essential", "🛡️ 非必要負載卸載率 (0~0.9)", 0.0, 0.9, 0.05),
            ("hydrogen_burn_valve", "🧪 氫氣溢流燃燒閥 (0~1.0)", 0.0, 1.0, 0.05),
            ("deuterium_fraction_rate", "💧 重氫分餾功率比 (0~1.0)", 0.0, 1.0, 0.05),
            ("em_ejector_rate", "🚀 電磁彈射太陽帆率 (0~1.0)", 0.0, 1.0, 0.05),
            ("rocket_launch_rate", "🛰️ 戴森結構火箭發射率 (0~1.0)", 0.0, 1.0, 0.05),
            ("ray_receiver_photon_ratio", "⚡ 接收站高能光子比 (0~1.0)", 0.0, 1.0, 0.05),
            ("mining_rig_build_rate", "⛏️ 採礦設備增產率 (0~1.5)", 0.0, 1.5, 0.05),
            ("dimensional_exponent", "🌀 多維空間非線性指數 α (0.5~2.5)", 0.5, 2.5, 0.05),
        ]:
            sp = QDoubleSpinBox()
            sp.setRange(lo, hi)
            sp.setSingleStep(step)
            sp.setDecimals(2)
            sp.valueChanged.connect(self._on_manual_param_edited)
            self.param_spins[key] = sp
            form.addRow(label, sp)

        self.cmb_build_focus = QComboBox()
        for bf in [
            "balanced",
            "mining",
            "fission",
            "thermal",
            "geothermal",
            "ocean_current",
            "refinery",
            "fusion",
            "swarm",
            "shell",
            "hyper_structure",
            "causal_loop_stabilizer",
        ]:
            self.cmb_build_focus.addItem(bf, bf)
        self.cmb_build_focus.currentTextChanged.connect(self._on_manual_param_edited)
        form.addRow("🏗️ 自動擴建重心 (build_focus)", self.cmb_build_focus)
        rv.addWidget(grp_params)

        # 3.5 High-Dimensional Particle Pipeline Editor (Declarative Sequence + Function List) & Ascension Preview
        grp_part = QGroupBox("🧬 高維度狀態粒子序列接口 (Sequence + Function List 免寫 Code)")
        part_v = QVBoxLayout(grp_part)
        part_top = QHBoxLayout()
        self.cmb_particle_preset = QComboBox()
        for st_p in range(7, 14):
            pr_meta = DysonCosmos3DViewport.default_particle_program_for_stage(st_p)
            self.cmb_particle_preset.addItem(pr_meta.get("name", f"Stage {st_p} 粒子序列"), st_p)
        self.cmb_particle_preset.currentIndexChanged.connect(self._on_particle_preset_selected)
        part_top.addWidget(QLabel("預設序列:"))
        part_top.addWidget(self.cmb_particle_preset, stretch=1)

        btn_add_fn = QComboBox()
        btn_add_fn.addItem("➕ 插入基底算子 (Function)...", "")
        for fn_label, fn_obj in [
            ("🌀 torus_knot (超環面結 p,q)", {"fn": "torus_knot", "p": 3, "q": 7, "radius": 1.25, "tube": 0.30, "speed": 1.1}),
            ("🌺 calabi_yau_fold (卡拉比-丘 6D 摺疊)", {"fn": "calabi_yau_fold", "n_fold": 6, "amp": 0.22, "speed": 1.4}),
            ("🔮 hypersphere_4d (4D 超球面投影)", {"fn": "hypersphere_4d", "radius": 1.20, "w_speed": 1.3, "proj_d": 2.1}),
            ("🕳️ wormhole_throat (蟲洞雙曲喉道)", {"fn": "wormhole_throat", "throat_r": 0.55, "flare": 0.85, "height": 1.3}),
            ("⏳ ctc_time_loop (閉時曲線莫比烏斯環)", {"fn": "ctc_time_loop", "loops": 3, "radius": 1.35, "twist_speed": 1.5}),
            ("🧬 hopf_fibration (S³→S² 霍普夫纖維叢)", {"fn": "hopf_fibration", "eta": 0.72, "scale": 0.22, "speed": 1.3}),
            ("⚡ vacuum_foam_pulse (真空泡沫非線性脈動)", {"fn": "vacuum_foam_pulse", "freq": 8.0, "amp": 0.12, "use_dim_exponent": True}),
            ("🌪️ lorentz_twist (相對論參考系拖曳扭轉)", {"fn": "lorentz_twist", "axis": "y", "strength": 0.55}),
        ]:
            btn_add_fn.addItem(fn_label, fn_obj)
        btn_add_fn.currentIndexChanged.connect(self._on_insert_particle_fn)
        part_top.addWidget(btn_add_fn)
        part_v.addLayout(part_top)

        self.txt_particle_json = QPlainTextEdit()
        self.txt_particle_json.setMaximumHeight(105)
        self.txt_particle_json.setPlainText(
            json.dumps(self.viewport.custom_particle_program, ensure_ascii=False, indent=2)
        )
        part_v.addWidget(self.txt_particle_json)

        part_btn_row = QHBoxLayout()
        btn_apply_part = QPushButton("⚡ 即時套用粒子 Function List")
        btn_apply_part.setStyleSheet("background-color: #0284c7; color: white; font-weight: bold; padding: 3px 8px;")
        btn_apply_part.clicked.connect(self._on_apply_particle_json)
        part_btn_row.addWidget(btn_apply_part)

        btn_preview_asc = QPushButton("🎬 預覽階段躍遷轉場動畫 (Ascension Warp)")
        btn_preview_asc.setStyleSheet("background-color: #9333ea; color: white; font-weight: bold; padding: 3px 8px;")
        btn_preview_asc.clicked.connect(self._on_preview_ascension_clicked)
        part_btn_row.addWidget(btn_preview_asc)
        part_v.addLayout(part_btn_row)
        rv.addWidget(grp_part)

        # 4. AI Stream & Parsed Action Console
        grp_log = QGroupBox("🧠 地端 MoE 推論串流與參數 Parse 紀錄")
        log_v = QVBoxLayout(grp_log)
        self.txt_ai_log = QPlainTextEdit()
        self.txt_ai_log.setReadOnly(True)
        log_v.addWidget(self.txt_ai_log)
        rv.addWidget(grp_log, stretch=1)

        splitter.addWidget(right_panel)
        splitter.setSizes([960, 600])
        root_v.addWidget(splitter, stretch=1)

    def _append_session_md(self, text: str) -> None:
        try:
            with open(self.session_md_path, "a", encoding="utf-8") as f:
                f.write(text)
        except Exception:
            pass

    def _append_session_jsonl(self, record: Dict[str, Any]) -> None:
        try:
            with open(self.session_jsonl_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def _save_game_checkpoint(self, auto: bool = False) -> None:
        state = self.sim.get_state()
        payload = {
            "saved_at": datetime.datetime.now().isoformat(),
            "state": state,
            "lorenz_state": [self.viewport._lx, self.viewport._ly, self.viewport._lz],
            "phase_trail": self.viewport.phase_trail[-800:],
        }
        latest_path = self.saves_dir / "latest_dyson_save.json"
        latest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        if not auto:
            snap_name = f"save_stage{state.get('stage', 1)}_tick{state.get('tick', 0)}_exp{int(state.get('stage_exp_pct', 0))}.json"
            snap_path = self.saves_dir / snap_name
            snap_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            self.txt_ai_log.appendPlainText(f"\n💾 [Checkpoint Saved]: 已儲存續關檔案至 saves/{snap_name} 與 saves/latest_dyson_save.json！")

    def _load_game_checkpoint(self) -> None:
        latest_path = self.saves_dir / "latest_dyson_save.json"
        target_path = latest_path
        if not latest_path.exists():
            fn, _ = QFileDialog.getOpenFileName(self, "選擇戴森球存檔", str(self.saves_dir), "JSON Files (*.json)")
            if not fn:
                return
            target_path = Path(fn)
        try:
            data = json.loads(target_path.read_text(encoding="utf-8"))
            st_dict = data.get("state") or data
            new_state = self.sim.load_full_state_dict(st_dict)
            if "lorenz_state" in data and len(data["lorenz_state"]) == 3:
                self.viewport._lx, self.viewport._ly, self.viewport._lz = [float(x) for x in data["lorenz_state"]]
            if "phase_trail" in data and isinstance(data["phase_trail"], list):
                self.viewport.phase_trail = [tuple(x) for x in data["phase_trail"]]
            self.ticks_since_last_sync = 0
            self._refresh_ui_from_state(new_state)
            self.txt_ai_log.appendPlainText(
                f"\n📂 [Checkpoint Loaded]: 已成功載入續關進度 (Stage {new_state.get('stage')} | Tick #{new_state.get('tick')} | EXP {new_state.get('stage_exp_pct', 0):.1f}% | P_gen={new_state.get('p_gen_mw', 0):.1f} MW)！"
            )
        except Exception as e:
            self.txt_ai_log.appendPlainText(f"\n❌ [Load Failed]: {e}")

    def _toggle_play_pause(self) -> None:
        if self.paused_waiting_ai:
            self.paused_waiting_ai = False
            self.lbl_lockstep_state.setText("▶️ 手動強制解除 AI 等待，恢復 Tick 運行")
        else:
            self.sim_running = not self.sim_running
        self.btn_play_pause.setText("⏸️ 暫停模擬" if self.sim_running else "▶️ 繼續模擬")

    def _on_toggle_auto_stage(self, checked: bool) -> None:
        if hasattr(self.sim._core, "state") and isinstance(self.sim._core.state, dict):
            self.sim._core.state["auto_advance_stage"] = bool(checked)

    def _on_toggle_mining_economy(self, checked: bool) -> None:
        if hasattr(self.sim._core, "state") and isinstance(self.sim._core.state, dict):
            self.sim._core.state["enable_mining_economy"] = bool(checked)
            if not checked:
                self.sim._core.state["fault_material_shortage"] = False
        self.lbl_lockstep_state.setText(
            f"⛏️ 基建&採礦原材料閉環: {'ON (隨 EXP% 級數耗材)' if checked else 'OFF (已旁路免耗材擴建)'}"
        )

    def _refresh_stage_combobox(self, select_stage: int = 0) -> None:
        cur = select_stage or int(self.cmb_stage.currentData() or 1)
        self.cmb_stage.blockSignals(True)
        self.cmb_stage.clear()
        for st_id, meta in sorted(STAGE_METADATA.items(), key=lambda x: x[0]):
            self.cmb_stage.addItem(meta["name"], st_id)
        next_blank = max(STAGE_METADATA.keys()) + 1
        self.cmb_stage.addItem(
            f"Stage {next_blank}+: ❓ [留空 — 待滿級後由 31B 調用黑洞全算力創世寫入 stage_list.json]",
            -1,
        )
        idx = self.cmb_stage.findData(cur)
        if idx >= 0:
            self.cmb_stage.setCurrentIndex(idx)
        self.cmb_stage.blockSignals(False)

    def _on_stage_selected(self) -> None:
        st_id = int(self.cmb_stage.currentData() or 1)
        if st_id < 1:
            # User clicked the blank placeholder slot; revert selection to current active stage
            self._refresh_stage_combobox(select_stage=int(self.sim.get_state().get("stage", 1)))
            return
        state = self.sim.reset_stage(st_id)
        if hasattr(self.sim._core, "state") and isinstance(self.sim._core.state, dict):
            self.sim._core.state["auto_advance_stage"] = bool(self.chk_auto_stage.isChecked())
        self.ticks_since_last_sync = 0
        self.awaiting_initial_ai_action = True
        # Unless user explicitly locked onto Lorenz Attractor (`lorenz_3d`), sync 3D view with Stage!
        if str(self.cmb_camera.currentData() or "") != "lorenz_3d":
            self.viewport.sync_view_to_stage(st_id)
            rec_cam = STAGE_METADATA.get(st_id, {}).get("recommended_camera", "earth_25d")
            self.cmb_camera.blockSignals(True)
            c_idx = self.cmb_camera.findData(rec_cam)
            if c_idx >= 0:
                self.cmb_camera.setCurrentIndex(c_idx)
            self.cmb_camera.blockSignals(False)
        # Auto-switch to Detailed Mode when selecting Stage 4 or Stage 5 (breaking through Stage 3)
        if st_id >= 4 and self.chk_compact_mode.isChecked():
            self.chk_compact_mode.setChecked(False)
            self.txt_ai_log.appendPlainText(
                f"\n📝 [Stage {st_id} 深度模式切換]: 已突破 Stage 3，自動關閉精簡模式並切回「完整底層深度分析模式」！"
            )
        elif st_id <= 3 and not self.chk_compact_mode.isChecked():
            self.chk_compact_mode.setChecked(True)
        self._refresh_ui_from_state(state)
        if self.chk_auto_ai_sync.isChecked() and self.tcp_server.is_client_connected():
            self.scheduled_action_queue.clear()
            self._trigger_ai_lockstep_sync(
                reason=f"🔄 階段切換/重啟至 Stage {st_id} 初始現狀確認 — 請立即檢視電網與採礦原材料狀態"
            )

    def _on_camera_changed(self) -> None:
        mode = str(self.cmb_camera.currentData() or "auto")
        if mode == "auto":
            self.viewport.auto_follow_stage = True
            self.viewport.sync_view_to_stage(int(self.sim.get_state().get("stage", 1)))
        elif mode == "lorenz_3d":
            self.viewport.auto_follow_stage = False
            self.viewport.view_mode = "lorenz_3d"
        else:
            # User picked a stage scene view; allow stage changes to keep syncing unless locked to lorenz_3d
            self.viewport.auto_follow_stage = True
            self.viewport.view_mode = mode
        self.viewport.update()

    def _inject_fault(self, fault_code: str) -> None:
        state = self.sim.inject_fault(fault_code)
        self._refresh_ui_from_state(state)
        self.txt_ai_log.appendPlainText(f"\n⚠️ [Fault Injected]: {fault_code}")
        if fault_code != "clear" and self.chk_auto_ai_sync.isChecked() and self.tcp_server.is_client_connected():
            self._trigger_ai_lockstep_sync(reason=f"災難警報觸發 ({fault_code})")

    def _on_particle_preset_selected(self, idx: int) -> None:
        st_p = int(self.cmb_particle_preset.currentData() or 7)
        prog = STAGE_METADATA.get(st_p, {}).get("particle_program") or DysonCosmos3DViewport.default_particle_program_for_stage(st_p)
        self.viewport.set_custom_particle_program(prog)
        self.txt_particle_json.setPlainText(json.dumps(prog, ensure_ascii=False, indent=2))

    def _on_insert_particle_fn(self, idx: int) -> None:
        sender = self.sender()
        if not isinstance(sender, QComboBox) or idx <= 0:
            return
        fn_obj = sender.currentData()
        sender.setCurrentIndex(0)
        if not isinstance(fn_obj, dict):
            return
        try:
            cur_prog = json.loads(self.txt_particle_json.toPlainText())
            if not isinstance(cur_prog, dict):
                cur_prog = DysonCosmos3DViewport.default_particle_program_for_stage(7)
            cur_prog.setdefault("enabled", True)
            cur_prog.setdefault("function_list", []).append(fn_obj)
            self.txt_particle_json.setPlainText(json.dumps(cur_prog, ensure_ascii=False, indent=2))
            self.viewport.set_custom_particle_program(cur_prog)
        except Exception:
            pass

    def _on_apply_particle_json(self) -> None:
        try:
            prog = json.loads(self.txt_particle_json.toPlainText())
            if isinstance(prog, dict):
                self.viewport.set_custom_particle_program(prog)
                st_cur = int(self.sim.get_state().get("stage", 7))
                if st_cur in STAGE_METADATA:
                    STAGE_METADATA[st_cur]["particle_program"] = prog
                self.txt_ai_log.appendPlainText(
                    f"\n🧬 [Particle Pipeline Applied]: 已即時更新高維度粒子序列 ({len(prog.get('function_list', []))} 個基底 Function)！"
                )
        except Exception as e:
            self.txt_ai_log.appendPlainText(f"\n⚠️ [Particle JSON Error]: {e}")

    def _trigger_big_crunch_epoch_reset(self, reason: str = "") -> None:
        """Archives the current Universe Epoch (stage_list.json + save + summary) into `backups/`,
        then triggers a Big Crunch -> Big Bang reset back to Stage 1 for the next Cosmic Cycle!"""
        state = self.sim.get_state()
        cur_epoch = int(state.get("cosmic_cycle_epoch", 2))
        cur_st = int(state.get("stage", 1))
        cur_tick = int(state.get("tick", 0))
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

        backup_dir = Path(__file__).resolve().parent / "backups" / f"epoch{cur_epoch}_stage{cur_st}_{ts}"
        backup_dir.mkdir(parents=True, exist_ok=True)

        # 1. Backup full `stage_list.json` of this Epoch
        serializable_stages = {str(k): v for k, v in sorted(STAGE_METADATA.items(), key=lambda x: x[0])}
        (backup_dir / f"stage_list_epoch{cur_epoch}_stage{cur_st}.json").write_text(
            json.dumps(serializable_stages, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # 2. Backup final Save State & Lorenz Attractor trail
        save_payload = {
            "saved_at": datetime.datetime.now().isoformat(),
            "epoch": cur_epoch,
            "reason": reason,
            "state": state,
            "lorenz_state": [self.viewport._lx, self.viewport._ly, self.viewport._lz],
            "phase_trail": self.viewport.phase_trail[-800:],
        }
        (backup_dir / f"save_epoch{cur_epoch}_stage{cur_st}_tick{cur_tick}.json").write_text(
            json.dumps(save_payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # 3. Extract Cosmic Microwave Background Relic from the highest stage of this Epoch
        last_meta = STAGE_METADATA.get(cur_st, {})
        relic_str = f"Epoch #{cur_epoch} 終極階段 [{last_meta.get('name', f'Stage {cur_st}')}] (P_gen={state.get('p_gen_mw', 0):.3e} MW | Lore: {last_meta.get('lore', '')[:80]})"

        # 4. Write EPOCH_ARCHIVE_SUMMARY.md
        summary_md = (
            f"# 🌌 龐加萊輪迴紀元歸檔 (Epoch #{cur_epoch} — Big Crunch Archive)\n"
            f"- **觸發原因**: {reason}\n"
            f"- **歸檔時間**: `{ts}`\n"
            f"- **最終階段**: `{last_meta.get('name', f'Stage {cur_st}')}`\n"
            f"- **最終 Tick**: `#{cur_tick}` | **宇宙曆**: `{state.get('cosmic_years', 0.0):,.0f} 地球年`\n"
            f"- **最終發電量 (`P_gen`)**: `{state.get('p_gen_mw', 0.0):.6e} MW` | **EROEI**: `{state.get('eroei', 0.0):.4e}`\n"
            f"- **跨宇宙背景輻射遺物印記 (`prev_universe_relic`)**: `{relic_str}`\n"
        )
        (backup_dir / "EPOCH_ARCHIVE_SUMMARY.md").write_text(summary_md, encoding="utf-8")

        # 4b. Flush & Export Full 65-Dimension Time-Series CSV for this completed Epoch!
        try:
            epoch_csv_path = backup_dir / f"dyson_telemetry_{self.session_id}.csv"
            self.telemetry_db.export_session_to_csv(epoch_csv_path)
            sess_csv_path = self.sess_dir / f"dyson_telemetry_{self.session_id}.csv"
            self.telemetry_db.export_session_to_csv(sess_csv_path)
            self.telemetry_db.start_new_session(ts)
            self.session_id = ts
        except Exception:
            pass

        # 5. Reset `stage_list.json` to Stages 1~6 & Re-birth Universe at Epoch + 1, Stage 1!
        reset_stage_list_to_base_6()
        if hasattr(self.sim._core, "state") and isinstance(self.sim._core.state, dict):
            self.sim._core.state["cosmic_cycle_epoch"] = cur_epoch + 1
            self.sim._core.state["prev_universe_relic"] = relic_str
        self.sim.reset_stage(1)
        self.scheduled_action_queue.clear()
        self.ticks_since_last_sync = 0
        self.awaiting_initial_ai_action = True
        self.sync_interval_ticks = 100
        self.spn_sync_ticks.blockSignals(True)
        self.spn_sync_ticks.setValue(100)
        self.spn_sync_ticks.blockSignals(False)
        for k, sp in self.param_spins.items():
            sp.setMaximum(2.5 if k == "dimensional_exponent" else (1.5 if "throttle" in k else 1.0))
        self.paused_waiting_ai = False
        self.chk_compact_mode.setChecked(True)
        self._refresh_stage_combobox(select_stage=1)
        self.viewport.phase_trail.clear()
        self.viewport.set_custom_particle_program(DysonCosmos3DViewport.default_particle_program_for_stage(1))
        self.viewport.sync_view_to_stage(1)
        self.viewport.trigger_ascension_transition(
            from_stage=cur_st,
            to_stage=1,
            title=f"💥 宇宙大坍縮 ➔ 第 {cur_epoch + 1} 輪迴紀元大爆炸 (BIG CRUNCH ➔ BIG BANG)",
            lore=f"上一紀元已自動歸檔至 backups/{backup_dir.name}！攜帶前世宇宙微波背景印記重返地球赤道起點！",
        )
        self._refresh_ui_from_state(self.sim.get_state())
        self.txt_ai_log.appendPlainText(
            f"\n💥♻️ 【BIG CRUNCH ➔ BIG BANG 宇宙輪迴重啟完成！】\n"
            f"  • 歸檔目錄: backups/{backup_dir.name}/\n"
            f"  • 前世遺物印記: {relic_str}\n"
            f"  • 新宇宙紀元: 第 {cur_epoch + 1} 輪迴紀元 (Epoch #{cur_epoch + 1}) 已從 Stage 1 (2026 核分裂+火力基建) 重新點火！\n"
        )
        # Immediately trigger AI inference upon restart to inspect initial status!
        if self.chk_auto_ai_sync.isChecked() and self.tcp_server.is_client_connected():
            self._trigger_ai_lockstep_sync(
                reason=f"♻️ 第 {cur_epoch + 1} 輪迴紀元重啟初始確認 (Tick #1：2026 核分裂+火力基建現狀檢視，滿 100 Ticks 將解鎖地熱與洋流發電！)"
            )

    def _on_preview_ascension_clicked(self) -> None:
        st_cur = int(self.sim.get_state().get("stage", 1))
        meta = STAGE_METADATA.get(st_cur, {})
        self.viewport.trigger_ascension_transition(
            from_stage=max(1, st_cur - 1),
            to_stage=st_cur,
            title=meta.get("name", f"Stage {st_cur}"),
            lore=meta.get("lore", meta.get("goal_desc", "")),
        )

    def _on_manual_param_edited(self) -> None:
        if self._updating_sliders:
            return
        patch = {k: float(sp.value()) for k, sp in self.param_spins.items()}
        patch["build_focus"] = self.cmb_build_focus.currentText()
        state = self.sim.apply_action_dict(patch)
        self._refresh_ui_from_state(state)

    def _on_sim_tick(self) -> None:
        if not self.sim_running or self.paused_waiting_ai:
            self.viewport.update_sim_state(
                self.sim.get_state(),
                paused_for_ai=(self.paused_waiting_ai or not self.sim_running),
            )
            return

        # HARD GATE 1: Never advance any Tick while Auto-AI Sync is enabled and Bridge is NOT connected!
        if self.chk_auto_ai_sync.isChecked() and not self.tcp_server.is_client_connected():
            cur_s = self.sim.get_state()
            self.lbl_lockstep_state.setText(
                f"🔒 [HOLDING FOR BRIDGE @ Tick #{cur_s.get('tick', 1)}] 尚未偵測到 AI Bridge 連線，禁止推進 Tick！(請啟動 run_moe_bridge.sh)"
            )
            self.viewport.update_sim_state(cur_s, paused_for_ai=True)
            return

        # HARD GATE 2: Once Bridge connects, force initial AI calibration before advancing from Tick #1 / stage reset!
        if self.chk_auto_ai_sync.isChecked() and self.tcp_server.is_client_connected() and getattr(self, "awaiting_initial_ai_action", False):
            self.awaiting_initial_ai_action = False
            self._trigger_ai_lockstep_sync(
                reason="🚀 模擬器啟動 / 初始條件打亂狀態解鎖 (請立即修正失調節流閥與逆火負發電，否則禁止推進 Tick)"
            )
            return

        prev_stage = int(self.sim.get_state().get("stage", 1))
        state = self.sim.step_ticks(1)
        cur_tick = int(state.get("tick", 0))
        cur_stage = int(state.get("stage", 1))
        stage_leveled_up = cur_stage != prev_stage
        self.ticks_since_last_sync += 1

        if stage_leveled_up:
            # Once breaking through Stage 3 -> Stage 4/5, automatically switch back to Full Deep-Diagnostic Mode!
            if cur_stage >= 4 and self.chk_compact_mode.isChecked():
                self.chk_compact_mode.setChecked(False)
                self.txt_ai_log.appendPlainText(
                    f"\n📝 [突破 Stage 3 ➔ 切換詳細模式]: 進入 Stage {cur_stage} 高階文明，已自動切換為「完整底層深度分析模式」，要求 AI 全面監控底層化工與頂層反物質耦合！"
                )
            # Sync 3D camera dropdown & viewport on auto Stage Level-Up unless locked to `lorenz_3d`
            if str(self.cmb_camera.currentData() or "") != "lorenz_3d":
                self.viewport.sync_view_to_stage(cur_stage)
                rec_cam = STAGE_METADATA.get(cur_stage, {}).get("recommended_camera", "earth_25d")
                self.cmb_camera.blockSignals(True)
                c_idx = self.cmb_camera.findData(rec_cam)
                if c_idx >= 0:
                    self.cmb_camera.setCurrentIndex(c_idx)
                self.cmb_camera.blockSignals(False)
            if self.scheduled_action_queue:
                self.scheduled_action_queue.clear()
            meta_new = STAGE_METADATA.get(cur_stage, {})
            prog_new = meta_new.get("particle_program") or DysonCosmos3DViewport.default_particle_program_for_stage(cur_stage)
            self.viewport.set_custom_particle_program(prog_new)
            self.txt_particle_json.setPlainText(json.dumps(prog_new, ensure_ascii=False, indent=2))
            self.viewport.trigger_ascension_transition(
                from_stage=prev_stage,
                to_stage=cur_stage,
                title=meta_new.get("name", f"Stage {cur_stage}"),
                lore=meta_new.get("lore", meta_new.get("goal_desc", "")),
            )
            self.txt_ai_log.appendPlainText(
                f"\n🌟 [STAGE LEVEL UP @ Tick #{cur_tick}]: 能量條集滿 100%，文明正式從 Stage {prev_stage} 躍遷至 Stage {cur_stage}！已啟動超維躍遷轉場動畫並喚醒 AI！"
            )

        # Check & Execute AI-Scheduled Alarm Queue Items (Zero-Compute Multi-Step Predictive MPC Adjustments!)
        if self.scheduled_action_queue:
            due_items = [item for item in self.scheduled_action_queue if cur_tick >= item["trigger_tick"]]
            self.scheduled_action_queue = [item for item in self.scheduled_action_queue if cur_tick < item["trigger_tick"]]
            for item in due_items:
                q_params = item["params"]
                self.viewport.mark_ai_intervention()
                state = self.sim.apply_action_dict(q_params)
                # Predictive Foresight Bonus: If system is healthy when scheduled step fires, award +1.5% Stage EXP!
                is_healthy_hit = (
                    float(state.get("grid_satisfaction", 1.0)) >= 0.98
                    and not state.get("fault_h2_deadlock")
                    and not state.get("fault_brownout_spiral")
                    and not state.get("fault_ai_overdraft")
                    and not state.get("game_over")
                )
                bonus_str = ""
                if is_healthy_hit and hasattr(self.sim._core, "state") and isinstance(self.sim._core.state, dict):
                    st_now_q = int(self.sim._core.state.get("stage", 1))
                    tgt_mw_q = float(STAGE_METADATA.get(st_now_q, {}).get("target_mw", 55.0))
                    cur_mw_q = float(self.sim._core.state.get("p_gen_mw", 0.0))
                    exp_cap_q = 100.0 if cur_mw_q >= tgt_mw_q else 99.0
                    old_exp = float(self.sim._core.state.get("stage_exp_pct", 0.0))
                    new_exp = min(exp_cap_q, old_exp + 1.5)
                    self.sim._core.state["stage_exp_pct"] = new_exp
                    state["stage_exp_pct"] = new_exp
                    bonus_str = f" | 🔮 [算力預言精準命中獎勵: EXP +1.5% ➔ {new_exp:.1f}%!]"
                q_sum = ", ".join(f"{k}={v}" for k, v in q_params.items())
                self.txt_ai_log.appendPlainText(
                    f"⏰ [Alarm Queue Executed @ Tick #{cur_tick}]: 零算力自動執行預排參數 -> {q_sum}{bonus_str}"
                )

        # Record 65-dimension telemetry vector into Pure-RAM Buffer (0 disk I/O during regular ticks!)
        evt_tag = "stage_level_up" if stage_leveled_up else "tick"
        self.telemetry_db.record_tick(
            state=state,
            event_type=evt_tag,
            model_id=getattr(self, "active_ai_model_id", "Gemma-4-31B-IT-NVFP4"),
            engine_mode=getattr(self, "active_ai_engine_mode", "rust_localsleep-moe (16-LoRA)"),
            queue_pending_count=len(self.scheduled_action_queue),
            force_flush=stage_leveled_up,
        )

        self._refresh_ui_from_state(state)

        # Automatic Big Crunch -> Big Bang Cyclic Universe Reset once Stage 25 reaches 100% EXP!
        if cur_stage >= 25 and float(state.get("stage_exp_pct", 0.0)) >= 99.9:
            self._trigger_big_crunch_epoch_reset(
                f"🌌 Stage {cur_stage} 能量條集滿 100%！宇宙抵達熱力學與超膜終極奇點 ➔ 自動觸發『大坍縮 ➔ 大爆炸 (Big Crunch ➔ Big Bang)』歸檔與輪迴重啟！"
            )
            return

        if self.chk_auto_ai_sync.isChecked() and self.tcp_server.is_client_connected():
            has_urgent_fault = bool(
                state.get("fault_brownout_spiral")
                or state.get("fault_h2_deadlock")
                or state.get("fault_seu_bitflip")
                or state.get("fault_material_shortage")
                or float(state.get("parasitic_drain_mw", 0.0)) > 0.5
            )
            need_genesis = bool(state.get("awaiting_ai_stage_genesis", False))
            if need_genesis:
                if self.chk_compact_mode.isChecked():
                    self.chk_compact_mode.setChecked(False)
                self._trigger_ai_lockstep_sync(
                    reason=f"🌌 Stage {cur_stage} 能量滿級！調用黑洞全算力撰寫 Stage {cur_stage + 1} 創世故事與目標 (寫入 stage_list.json)"
                )
            elif stage_leveled_up:
                self._trigger_ai_lockstep_sync(
                    reason=f"🌟 階段晉升強制喚醒 (Stage {prev_stage} ➔ Stage {cur_stage} 新科技解鎖！請立即調配新階段參數)"
                )
            elif has_urgent_fault and self.ticks_since_last_sync >= 10:
                if self.scheduled_action_queue:
                    self.scheduled_action_queue.clear()
                    self.txt_ai_log.appendPlainText("🚨 [Emergency Interrupt]: 偵測到突發災難，已清空舊鬧鐘佇列並提前喚醒 AI！")
                self._trigger_ai_lockstep_sync(reason="緊急故障中斷喚醒")
            elif not self.scheduled_action_queue and self.ticks_since_last_sync >= self.sync_interval_ticks:
                self._trigger_ai_lockstep_sync(
                    reason=f"AI 鬧鐘佇列已全數執行完畢 & 週期到期喚醒 (間隔 {self.sync_interval_ticks} Ticks)"
                )

    def _trigger_ai_lockstep_sync(self, reason: str = "") -> None:
        state = self.sim.get_state()
        eval_res = self.sim.evaluate_sync_window()

        # Anti-Explosion Deadlock Circuit Breaker: If deadlock/crisis occurs 3 consecutive times, auto-disable Compact Mode!
        has_deadlock_or_crisis = bool(
            state.get("active_alerts")
            or state.get("fault_h2_deadlock")
            or float(state.get("refined_oil_tank_pct", 0.0)) >= 95.0
            or float(state.get("hydrogen_tank_pct", 0.0)) >= 95.0
            or float(state.get("grid_satisfaction", 1.0)) < 0.85
        )
        if has_deadlock_or_crisis:
            self.consecutive_deadlock_count = getattr(self, "consecutive_deadlock_count", 0) + 1
            if self.scheduled_action_queue:
                self.scheduled_action_queue.clear()
            if self.consecutive_deadlock_count >= 3 and self.chk_compact_mode.isChecked():
                self.chk_compact_mode.setChecked(False)
                esc_msg = (
                    f"\n🛡️🧠 【防炸斷路器觸發 (連續 {self.consecutive_deadlock_count} 次死鎖/爆倉震盪 ➔ 自動切換完整深度算力模式)】\n"
                    f"  • 偵測到極速精簡模式無法解開耦合死鎖（油槽={state.get('refined_oil_tank_pct', 0.0):.1f}%, 氫槽={state.get('hydrogen_tank_pct', 0.0):.1f}%, η={state.get('grid_satisfaction', 1.0)*100:.0f}%）！\n"
                    f"  • 系統已自動取消勾選「⚡ 極速精簡模式」，強制升級為「📝 完整底層深度分析模式 (System-2 Deep Compute)」展開多步因果推演解鎖！\n"
                )
                self.txt_ai_log.appendPlainText(esc_msg)
                self._append_session_md(f"\n> {esc_msg}\n")
        else:
            self.consecutive_deadlock_count = 0

        is_compact = bool(self.chk_compact_mode.isChecked())
        prompt = self.sim.build_tick_state_prompt(state, compact_mode=is_compact)

        if not self.tcp_server.is_client_connected():
            self.txt_ai_log.appendPlainText(
                f"\n[Tick #{state['tick']}] ⚠️ 尚未偵測到 TCP AI Client 連線 (Port {DEFAULT_TCP_PORT})，已生成狀態 Prompt 預覽：\n{prompt[:420]}...\n"
            )
            return

        # Lockstep Pause: Simulator pauses immediately until AI replies!
        self.paused_waiting_ai = True
        self.ticks_since_last_sync = 0
        self.lbl_lockstep_state.setText(
            f"⏸️ [PAUSED_WAITING_AI @ Tick #{state['tick']}] 原因: {reason} | 前窗評估: {eval_res['consolidation_mode']}"
        )
        self.txt_ai_log.appendPlainText(
            f"\n==================== 🛰️ [Tick #{state['tick']} Lockstep Sync | {reason}] ====================\n"
            f"• 前一週期資格跡評估: {eval_res['consolidation_mode']} (ΔP={fmt_num(eval_res['delta_gen_mw'], 1)} MW, η={eval_res['grid_satisfaction']*100:.0f}%)\n"
            f"• 模擬器已自動暫停，等待地端 AI 回傳 <dyson_action>...\nKuro AI >> "
        )
        self.tcp_server.send_packet({
            "type": "tick_state_sync",
            "tick": state["tick"],
            "stage": state["stage"],
            "reason": reason,
            "compact_mode": is_compact,
            "state": state,
            "eval_prev_window": eval_res,
            "prompt": prompt,
        })
        self.viewport.update_sim_state(state, paused_for_ai=True)

    def _poll_tcp_events(self) -> None:
        while not self.tcp_server.inbound_queue.empty():
            evt = self.tcp_server.inbound_queue.get_nowait()
            etype = evt.get("type", "")
            if etype == "client_connected":
                self.lbl_tcp_status.setText(f"🟢 AI 推論橋接器已連線 ({evt.get('addr')})")
                self.txt_ai_log.appendPlainText(f"\n🔌 [TCP Connected] AI 推論通道已建立 ({evt.get('addr')})！")
            elif etype == "bridge_hello":
                m_id = str(evt.get("model_id") or "Unknown-Model")
                e_mode = str(evt.get("engine_mode") or "Standard-Bridge")
                api_b = str(evt.get("api_base") or "")
                self.active_ai_model_id = m_id
                self.active_ai_engine_mode = e_mode
                self.active_ai_api_base = api_b
                self.lbl_tcp_status.setText(f"🟢 AI 已連線: {m_id} [{e_mode}]")
                hello_msg = f"\n🤖 [AI Model Handshake] 自動偵測連線模型: `{m_id}` | 架構模式: `{e_mode}` | Endpoint: `{api_b}`\n"
                self.txt_ai_log.appendPlainText(hello_msg)
                self._append_session_md(f"\n> {hello_msg.strip()}\n\n")
                # If simulator just started / restarted (tick <= 15) and isn't already waiting for AI, trigger immediate initial check!
                cur_t = int(self.sim.get_state().get("tick", 0))
                if (cur_t <= 15 or getattr(self, "awaiting_initial_ai_action", False)) and self.chk_auto_ai_sync.isChecked() and not self.paused_waiting_ai:
                    self.awaiting_initial_ai_action = False
                    self._trigger_ai_lockstep_sync(
                        reason="🚀 模擬器啟動 / 橋接器連線初始現狀確認 (檢視打亂之初始失調狀態並立即校正)"
                    )
            elif etype == "client_disconnected":
                self.lbl_tcp_status.setText("🟡 AI 推論橋接器已斷線，等待重連 (Tick 已鎖定暫停)...")
                self.paused_waiting_ai = False
                self.awaiting_initial_ai_action = True
            elif etype == "ai_token_stream":
                piece = evt.get("piece", "")
                if piece:
                    cursor = self.txt_ai_log.textCursor()
                    cursor.movePosition(cursor.MoveOperation.End)
                    cursor.insertText(piece)
                    self.txt_ai_log.setTextCursor(cursor)
                    self.txt_ai_log.ensureCursorVisible()
            elif etype == "ai_action_complete":
                raw_text = evt.get("raw_text", "")
                infer_elapsed_s = float(evt.get("elapsed_s", 1.0))
                if evt.get("model_id"):
                    self.active_ai_model_id = str(evt["model_id"])
                if evt.get("engine_mode"):
                    self.active_ai_engine_mode = str(evt["engine_mode"])
                if evt.get("api_base"):
                    self.active_ai_api_base = str(evt["api_base"])
                cur_model_id = getattr(self, "active_ai_model_id", "Gemma-4-31B-IT-NVFP4")
                cur_engine_mode = getattr(self, "active_ai_engine_mode", "rust_localsleep-moe (16-LoRA)")
                cur_model_full_tag = f"{cur_model_id} [{cur_engine_mode}]"
                self.lbl_tcp_status.setText(f"🟢 AI 已連線: {cur_model_full_tag}")

                cur_state = self.sim.get_state()
                tick_val = int(evt.get("tick", cur_state.get("tick", 0)))
                parsed_params, summary = DysonActionParser.parse_ai_response(raw_text)
                raw_q_preview = parsed_params.get("action_queue")
                q_count_for_refund = len(raw_q_preview) if isinstance(raw_q_preview, list) else 0

                cost_coeff = float(self.spn_ai_cost_coeff.value())
                cost_info = self.sim.consume_ai_inference_energy(
                    infer_elapsed_s,
                    cost_coeff,
                    compact_mode=self.chk_compact_mode.isChecked(),
                    queued_steps_count=q_count_for_refund,
                )
                cur_state = self.sim.get_state()
                parse_err = parsed_params.pop("_parse_error", None)
                if hasattr(self.sim._core, "state") and isinstance(self.sim._core.state, dict):
                    self.sim._core.state["last_parse_error"] = str(parse_err or "")
                err_feedback_log = (
                    f"\n❌ [Parser Syntax Error ➔ 將在下輪 Prompt 丟回給 {cur_model_id} 要求自我修正]: {parse_err}"
                    if parse_err else ""
                )

                # 0. Check if AI authored a brand-new Stage (`new_stage_genesis`) via Black-Hole Full Compute!
                genesis_obj = parsed_params.pop("new_stage_genesis", None)
                # Safety Net: If simulator was waiting for genesis (`awaiting_ai_stage_genesis`), NEVER let it get stuck in a 1-tick loop!
                if not isinstance(genesis_obj, dict) and bool(cur_state.get("awaiting_ai_stage_genesis", False)):
                    next_st_id = int(cur_state.get("stage", 6)) + 1
                    genesis_obj = {
                        "stage": next_st_id,
                        "name": f"Stage {next_st_id}: 🌌 超膜量子泡沫與高維真空相變 #{next_st_id}",
                        "lore": raw_text.strip().split("\n")[0][:120] or "文明跨越奇點，將物理常數編碼為高維超膜資訊流。",
                        "goal_desc": "維持高維非線性正循環，衝刺下一能標閾值！",
                    }
                genesis_banner = ""
                if isinstance(genesis_obj, dict):
                    next_st_id = int(cur_state.get("stage", 6)) + 1
                    new_entry = register_ai_genesis_stage(genesis_obj, next_st_id, authored_by=cur_model_full_tag)
                    actual_st_id = int(genesis_obj.get("stage") or next_st_id)
                    if hasattr(self.sim._core, "state") and isinstance(self.sim._core.state, dict):
                        s_ref = self.sim._core.state
                        s_ref["stage"] = actual_st_id
                        s_ref["stage_ticks"] = 0
                        s_ref["stage_exp_pct"] = 0.0
                        s_ref["awaiting_ai_stage_genesis"] = False
                        s_ref["years_per_tick"] = float(new_entry.get("years_per_tick", 100000.0))
                        s_ref["battery_capacity_mwh"] = max(float(s_ref.get("battery_capacity_mwh", 500000.0)) * 2.5, 1000000.0)
                    self._refresh_stage_combobox(select_stage=actual_st_id)
                    prog_gen = new_entry.get("particle_program") or DysonCosmos3DViewport.default_particle_program_for_stage(actual_st_id)
                    self.viewport.set_custom_particle_program(prog_gen)
                    self.txt_particle_json.setPlainText(json.dumps(prog_gen, ensure_ascii=False, indent=2))
                    self.viewport.trigger_ascension_transition(
                        from_stage=actual_st_id - 1,
                        to_stage=actual_st_id,
                        title=new_entry["name"],
                        lore=new_entry.get("lore", new_entry.get("goal_desc", "")),
                    )
                    genesis_banner = (
                        f"\n🌌📜 【{cur_model_full_tag} 黑洞全算力創世成功 — 已寫入 stage_list.json！】\n"
                        f"  • 創世模型 (Author): {cur_model_full_tag}\n"
                        f"  • 新階段名稱: {new_entry['name']}\n"
                        f"  • 創世世界觀 (Lore): {new_entry['lore']}\n"
                        f"  • 階段目標: {new_entry['goal_desc']} (Target: {fmt_num(new_entry['target_mw'], 0)} MW | 1 Tick = {fmt_num(new_entry['years_per_tick'], 0)} 地球年)\n"
                    )
                    self._append_session_md(f"\n> {genesis_banner}\n")

                # 1. Extract dynamic `next_wake_ticks` (10 ~ 10000 Ticks self-scheduled by AI)
                next_wake = parsed_params.pop("next_wake_ticks", None)
                if isinstance(next_wake, (int, float)):
                    new_interval = max(10, min(10000, int(round(float(next_wake)))))
                    self.sync_interval_ticks = new_interval

                # 2. Extract multi-step `action_queue` & AUTO-EXTEND `sync_interval_ticks` beyond the entire queue!
                raw_queue = parsed_params.pop("action_queue", None)
                queued_desc = []
                max_delay = 0
                if isinstance(raw_queue, list):
                    self.scheduled_action_queue.clear()
                    prev_delay = 0
                    for q_item in raw_queue:
                        if isinstance(q_item, dict):
                            raw_d = max(10, min(5000, int(q_item.get("delay_ticks", 80))))
                            # Ensure strictly increasing monotonic schedule even if AI wrote relative/duplicate delays
                            delay = raw_d if raw_d > prev_delay else (prev_delay + max(60, raw_d))
                            prev_delay = delay
                            max_delay = max(max_delay, delay)
                            step_params = {
                                k: v for k, v in q_item.items()
                                if k in DysonActionParser.VALID_KEYS and k not in ("next_wake_ticks", "action_queue")
                            }
                            if step_params:
                                trig_t = int(cur_state.get("tick", tick_val)) + delay
                                self.scheduled_action_queue.append({"trigger_tick": trig_t, "params": step_params})
                                queued_desc.append(f"@Tick#{trig_t}(+{delay}): {step_params}")
                    self.scheduled_action_queue.sort(key=lambda x: x["trigger_tick"])

                # Auto-extend wake tick interval so it NEVER wakes up before the scheduled queue finishes!
                if max_delay > 0 or queued_desc:
                    auto_min_wake = max(max_delay + 120, len(queued_desc) * 120)
                    if self.sync_interval_ticks < auto_min_wake:
                        self.sync_interval_ticks = min(10000, auto_min_wake)
                        next_wake = self.sync_interval_ticks

                self.spn_sync_ticks.blockSignals(True)
                self.spn_sync_ticks.setValue(self.sync_interval_ticks)
                self.spn_sync_ticks.blockSignals(False)

                if parsed_params or next_wake or queued_desc:
                    self.viewport.mark_ai_intervention()
                    new_state = self.sim.apply_action_dict(parsed_params) if parsed_params else cur_state
                    self._refresh_ui_from_state(new_state)
                    self._save_game_checkpoint(auto=True)
                    q_log = f"\n⏰ [AI 預排鬧鐘佇列 ({len(queued_desc)} 筆)]: " + " ; ".join(queued_desc) if queued_desc else ""
                    w_log = f" | ⏱️ 下次喚醒設為 +{self.sync_interval_ticks} Ticks" if next_wake else ""
                    over_str = f" ⚠️[透支 {cost_info['overdraft_mwh']:.1f} MWh!]" if cost_info["overdraft_mwh"] > 0 else ""
                    if int(new_state.get("stage", 1)) >= 7:
                        cost_log = (
                            f"\n♾️ [Stage {new_state.get('stage')} 多重宇宙超膜算力]: 推論耗時 Δt={cost_info['elapsed_s']:.2f}s "
                            f"— 由高維真空零點能無限供給 (蓄電扣減 0.0 MWh | 黑洞視界壽命: ∞ 無限大！)"
                        )
                    elif cost_info.get("bh_years_cost", 0.0) > 0:
                        cost_log = (
                            f"\n🕳️ [Stage 6 霍金量子迴路算力耗能]: 蓄電池扣電 0.0 MWh！推論耗時 Δt={cost_info['elapsed_s']:.2f}s "
                            f"直接消耗黑洞視界壽命 -{cost_info['bh_years_cost']:,.0f} 地球年 (黑洞剩餘壽命: {cost_info['bh_lifespan_years']:,.0f} 年 / {cost_info['bh_lifespan_pct']:.2f}%)"
                        )
                    else:
                        cost_log = (
                            f"\n🔋 [AI 算力耗能 Consumer]: 推論耗時 Δt={cost_info['elapsed_s']:.2f}s × 係數 {cost_info['coeff']:.1f} "
                            f"= 扣除蓄電 -{cost_info['consumed_mwh']:.1f} MWh (剩餘蓄電: {cost_info['remaining_battery_mwh']:.1f} MWh){over_str}"
                        )
                    self.txt_ai_log.appendPlainText(
                        f"{genesis_banner}{cost_log}{err_feedback_log}\n✅ [Parsed & Applied]: {', '.join(summary)}{w_log}{q_log}\n"
                        f"▶️ [Lockstep Resumed] 模擬器已套用新參數並自動恢復 Tick 推進！\n"
                    )
                else:
                    new_state = self.sim.get_state()
                    self.sync_interval_ticks = 15
                    self.spn_sync_ticks.blockSignals(True)
                    self.spn_sync_ticks.setValue(15)
                    self.spn_sync_ticks.blockSignals(False)
                    self.txt_ai_log.appendPlainText(
                        f"\n⚠️ [Parser Notice]: 未偵測到有效 <dyson_action> JSON！{err_feedback_log}\n"
                        f"👉 已將喚醒間隔縮短為 15 Ticks，並將錯誤訊息寫入下輪 Prompt 要求 31B 修正格式！\n"
                    )
                self._append_session_md(
                    f"## 🛰️ Tick #{tick_val} | Stage {new_state.get('stage')} | P_gen={fmt_num(new_state.get('p_gen_mw', 0), 1)} MW (η={new_state.get('grid_satisfaction', 1)*100:.0f}%) | 🤖 Model: `{cur_model_full_tag}`\n"
                    f"- **Model & Engine**: `{cur_model_id}` (`{cur_engine_mode}`)\n"
                    f"- **Alerts**: `{new_state.get('active_alerts', [])}`\n"
                    f"- **AI Diagnosis & Action ({cur_model_id})**:\n```text\n{raw_text.strip()}\n```\n"
                    f"- **Parsed Control Params**: `{json.dumps(parsed_params, ensure_ascii=False)}`\n\n---\n\n"
                )
                self._append_session_jsonl({
                    "timestamp": datetime.datetime.now().isoformat(),
                    "tick": tick_val,
                    "stage": new_state.get("stage"),
                    "model_id": cur_model_id,
                    "engine_mode": cur_engine_mode,
                    "p_gen_mw": new_state.get("p_gen_mw"),
                    "grid_satisfaction": new_state.get("grid_satisfaction"),
                    "hydrogen_tank_pct": new_state.get("hydrogen_tank_pct"),
                    "eroei": new_state.get("eroei"),
                    "raw_ai_reply": raw_text,
                    "parsed_params": parsed_params,
                    "scheduled_action_queue": list(self.scheduled_action_queue),
                    "state_snapshot": new_state,
                })
                # Record AI Sync Event into RAM buffer & flush batch to Redis/SQLite-WAL now (during AI pause, 0 tick jitter!)
                self.telemetry_db.record_tick(
                    state=new_state,
                    event_type="ai_sync_applied",
                    model_id=cur_model_id,
                    engine_mode=cur_engine_mode,
                    queue_pending_count=len(self.scheduled_action_queue),
                    force_flush=True,
                )
                self.paused_waiting_ai = False
                if cost_info.get("game_over"):
                    self.sim_running = False
                    self.scheduled_action_queue.clear()
                    self.btn_play_pause.setText("▶️ 繼續模擬 (已 GAME OVER)")
                    go_reason = cost_info.get("game_over_reason") or "💀 [GAME OVER]: 蓄電池跌破負數，AI 算力中樞斷電腦死！"
                    self.lbl_lockstep_state.setText(go_reason)
                    self.lbl_lockstep_state.setStyleSheet("color: #f43f5e; font-weight: bold; font-size: 13px;")
                    go_md = (
                        f"\n\n> 💀🚨 **{go_reason}**\n"
                        f"> - **淘汰模型 (Eliminated Model)**: `{cur_model_full_tag}`\n"
                        f"> - **最終停留階段**: `Stage {cur_state.get('stage', 1)}` (`Tick #{tick_val}` | `P_gen={cur_state.get('p_gen_mw', 0.0):.1f} MW`)\n"
                        f"> - **最終蓄電透支**: `{cost_info['remaining_battery_mwh']:.2f} MWh` (本次推論耗時 `{infer_elapsed_s:.2f}s` 扣電 `-{cost_info['consumed_mwh']:.1f} MWh`)\n\n---\n"
                    )
                    self.txt_ai_log.appendPlainText(go_md)
                    self._append_session_md(go_md)
                else:
                    self.lbl_lockstep_state.setText(f"▶️ 模擬器狀態: RUNNING (已套用 {len(parsed_params)} 項 AI 參數)")

    def _refresh_ui_from_state(self, s: Dict[str, Any]) -> None:
        self.viewport.update_sim_state(s, paused_for_ai=self.paused_waiting_ai)
        st_num = int(s.get("stage", 1))
        if self.cmb_stage.currentData() != st_num:
            self.cmb_stage.blockSignals(True)
            idx = self.cmb_stage.findData(st_num)
            if idx >= 0:
                self.cmb_stage.setCurrentIndex(idx)
            self.cmb_stage.blockSignals(False)

        rem_wake = max(0, self.sync_interval_ticks - self.ticks_since_last_sync)
        q_cnt = len(self.scheduled_action_queue)
        q_next_str = f" (下個鬧鐘 @Tick#{self.scheduled_action_queue[0]['trigger_tick']})" if q_cnt > 0 else ""
        st_cur_ui = int(s.get("stage", 1))
        if st_cur_ui >= 7:
            bh_line = f"• ♾️ 黑洞視界壽命: ∞ 無限大 (超膜零點能) | 🌌 宇宙曆: {fmt_num(s.get('cosmic_years', 0.0), 0)} 年 (1 Tick={fmt_num(s.get('years_per_tick', 100000.0), 0)}年)\n"
        elif st_cur_ui == 6:
            bh_line = f"• 🕳️ 黑洞視界壽命: {fmt_num(s.get('blackhole_lifespan_years', 100000000.0), 0)} 地球年 ({s.get('blackhole_lifespan_pct', 100.0):.2f}%) | 🌌 宇宙曆: {fmt_num(s.get('cosmic_years', 0.0), 0)} 年 (1 Tick={fmt_num(s.get('years_per_tick', 1.0), 0)}年)\n"
        else:
            bh_line = f"• 🌌 宇宙曆紀元: 第 {fmt_num(s.get('cosmic_years', 0.0), 0)} 地球年 (當前時間流速: 1 Tick = 1 地球年)\n"
        self.lbl_telemetry.setText(
            f"• 🌟 階段躍遷能量條 (EXP): {s.get('stage_exp_pct', 0.0):.1f}% / 100.0% ({s.get('stage_exp_rate_per_tick', 0.0):+.2f}%/tick)\n"
            f"• ⏰ AI 鬧鐘倒數: {rem_wake} / {self.sync_interval_ticks} Ticks  |  待執行排程佇列 (Queue): {q_cnt} 筆{q_next_str}\n"
            f"{bh_line}"
            f"• 🧠 AI 算力耗電端: 上次 Δt={s.get('last_ai_infer_sec', 0.0):.2f}s 扣電 -{fmt_num(s.get('last_ai_consumed_mwh', 0.0), 1)} MWh  |  累計總耗電: {fmt_num(s.get('total_ai_consumed_mwh', 0.0), 1)} MWh\n"
            f"• Tick: #{s['tick']}  |  發電 P_gen: {fmt_num(s['p_gen_mw'], 1)} MW  |  負載 P_req: {fmt_num(s['p_req_mw'], 1)} MW\n"
            f"• 供電滿足率 η: {s['grid_satisfaction']*100:.1f}%  |  🔋 蓄電器: {fmt_num(s['battery_charge_mwh'], 1)}/{fmt_num(s['battery_capacity_mwh'], 1)} MWh\n"
            f"• ⛏️ 採礦機: {fmt_num(s.get('mining_rigs', 6.0), 1)} 台 | 🧱 原材料庫存: {fmt_num(s.get('raw_material_stock', 180.0), 1)} 噸 (EXP 級數耗材倍率: {s.get('mat_exp_cost_mult', 1.0):.2f}x)\n"
            f"• 燃煤: {fmt_num(s['coal_stock'], 1)} | 氫氣槽(H2): {s['hydrogen_tank_pct']:.1f}% | 精煉油槽: {s['refined_oil_tank_pct']:.1f}% | 重氫: {fmt_num(s['deuterium_stock'], 1)}\n"
            f"• 軌道太陽帆: {fmt_num(s['active_solar_sails'], 0)} 面 | 戴森球節點: {fmt_num(s['dyson_shell_nodes'], 1)} (覆蓋 {fmt_num(s['dyson_shell_coverage_pct'], 1)}%) | EROEI: {fmt_num(s['eroei'], 2)}"
        )

        p = s.get("params", {})
        self._updating_sliders = True
        for k, sp in self.param_spins.items():
            if k in p:
                val_f = float(p[k])
                if st_cur_ui >= 7 and val_f > sp.maximum():
                    sp.setMaximum(max(1000.0, val_f * 2.0))
                sp.setValue(val_f)
        if "build_focus" in p:
            self.cmb_build_focus.setCurrentText(str(p["build_focus"]))
        self._updating_sliders = False

    def _on_export_telemetry_csv_clicked(self) -> None:
        import webbrowser
        out_csv = self.sess_dir / f"dyson_telemetry_{self.session_id}.csv"
        info = self.telemetry_db.export_session_to_csv(out_csv, max_excel_rows=1500, max_html_rows=4500)
        hub_info = batch_export_all_legacy_sessions(self.sess_dir, self.telemetry_db_path, max_excel_rows=1500)
        self.txt_ai_log.appendPlainText(
            f"\n📊 [Grafana-Lite Telemetry Exported & Legacy Converted ({self.telemetry_db.backend_label})]:\n"
            f"  • 🟢 當前輪 Excel 高密防當機版 ({info['excel_rows']} 筆): {info['excel_csv_path']}\n"
            f"  • 📈 當前輪 Grafana-Lite 互動式曲線分析儀 ({info['html_rows']} 點): {info['html_chart_path']}\n"
            f"  • 🗂️ 已同步升級所有舊紀錄 (共 {hub_info['total_sessions']} 組 Session): {hub_info['hub_html_path']}"
        )
        try:
            webbrowser.open(Path(hub_info["hub_html_path"]).as_uri())
        except Exception:
            pass

    def closeEvent(self, event: Any) -> None:
        try:
            self.telemetry_db.close()
        except Exception:
            pass
        super().closeEvent(event)


def main() -> None:
    app = QApplication(sys.argv)
    win = DysonSphereSimWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
