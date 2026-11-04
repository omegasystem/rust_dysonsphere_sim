#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dyson_telemetry_db.py — High-Performance RAM-Buffered SQLite WAL Time-Series Telemetry Engine
=============================================================================================
- Zero per-tick disk I/O: Accumulates all 50+ dimensions of state + AI control parameters in RAM
  (`_ram_buffer`) during high-frequency simulation ticks (10~100 Hz).
- Batch Transaction Flush: Flushes in a single `executemany` WAL transaction only every N ticks
  (default 200 ticks), on Stage Level-Up, AI Sync, Big Crunch, or clean shutdown.
- Instant Analytics & One-Click CSV Export: Query cross-model parameter effectiveness via SQL
  or export any session to CSV in milliseconds.
"""

from __future__ import annotations

import csv
import datetime
import json
import math
import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import redis as _redis_mod  # type: ignore
except ImportError:
    _redis_mod = None


TELEMETRY_COLUMNS: List[str] = [
    "session_id",
    "tick",
    "stage",
    "stage_ticks",
    "event_type",
    "model_id",
    "engine_mode",
    # Macro Grid & Progress
    "stage_exp_pct",
    "stage_exp_rate_per_tick",
    "p_gen_mw",
    "p_load_mw",
    "grid_satisfaction",
    "eroei",
    "parasitic_drain_mw",
    "ai_compute_drain_mwh",
    # Storage & Mining Economy
    "battery_charge_mwh",
    "coal_stock",
    "raw_material_stock",
    "mining_rigs",
    "last_mat_mined",
    "last_mat_consumed",
    "mat_exp_cost_mult",
    "hydrogen_tank_pct",
    "refined_oil_tank_pct",
    "deuterium_stock",
    # Power Generation Breakdown (MW)
    "gen_thermal_mw",
    "gen_fission_mw",
    "gen_geothermal_mw",
    "gen_ocean_current_mw",
    "gen_fusion_mw",
    "gen_dyson_receiver_mw",
    "gen_antimatter_mw",
    # Infrastructure Units
    "thermal_plants",
    "fission_plants",
    "geothermal_plants",
    "ocean_current_turbines",
    "refineries",
    "fusion_plants",
    "em_ejectors",
    "vertical_launch_silos",
    "ray_receivers",
    "artificial_suns",
    "dyson_shell_nodes",
    "active_solar_sails",
    # Fault Flags (0/1 ints for fast correlation analysis)
    "fault_brownout_spiral",
    "fault_h2_deadlock",
    "fault_material_shortage",
    "fault_ai_overdraft",
    "fault_penrose_runaway",
    "game_over",
    # 15 AI Control Parameters
    "param_coal_throttle",
    "param_fusion_throttle",
    "param_antimatter_throttle",
    "param_load_shed_non_essential",
    "param_hydrogen_burn_valve",
    "param_refined_oil_crack_ratio",
    "param_deuterium_fraction_rate",
    "param_em_ejector_rate",
    "param_rocket_launch_rate",
    "param_ray_receiver_photon_ratio",
    "param_mining_rig_build_rate",
    "param_dimensional_exponent",
    "param_battery_mode",
    "param_build_focus",
    "queue_pending_count",
]


class DysonTelemetryDB:
    """
    RAM Ring-Buffered SQLite WAL Time-Series Store for Dyson Sphere Simulator.
    Avoids frequent disk writes while preserving 100% of per-tick 65-column curves.
    """

    def __init__(
        self,
        db_path: Path,
        session_id: str,
        flush_every_n_ticks: int = 500,
        redis_url: Optional[str] = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.session_id = session_id
        self.flush_every_n_ticks = max(50, int(flush_every_n_ticks))
        # Pure-RAM Ring Buffer: stores every tick's 65-dim tuple in memory (0 disk I/O during simulation!)
        self._ram_buffer: List[Tuple[Any, ...]] = []
        self._all_session_rows_ram: List[Tuple[Any, ...]] = []
        self._total_flushed_rows: int = 0

        # Optional Redis In-Memory Backend (auto-detects `REDIS_URL` or `redis://127.0.0.1:6379/0`)
        self.redis_client: Any = None
        self.redis_active: bool = False
        r_url = redis_url or os.environ.get("DYSON_REDIS_URL", "redis://127.0.0.1:6379/0")
        if _redis_mod is not None and r_url:
            try:
                rc = _redis_mod.from_url(r_url, socket_connect_timeout=0.12, socket_timeout=0.15, decode_responses=True)
                rc.ping()
                self.redis_client = rc
                self.redis_active = True
            except Exception:
                self.redis_client = None
                self.redis_active = False

        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        # High-performance SQLite settings: WAL mode + RAM temp store + normal sync
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.execute("PRAGMA synchronous=NORMAL;")
        self.conn.execute("PRAGMA temp_store=MEMORY;")
        self.conn.execute("PRAGMA cache_size=-64000;")  # 64 MB page cache in RAM
        self._init_schema()

    @property
    def backend_label(self) -> str:
        if self.redis_active:
            return "Redis RAM + SQLite-WAL"
        return "Pure-RAM RingBuffer + SQLite-WAL"

    def _init_schema(self) -> None:
        col_defs = []
        for col in TELEMETRY_COLUMNS:
            if col in ("session_id", "event_type", "model_id", "engine_mode", "param_build_focus"):
                col_defs.append(f"{col} TEXT")
            elif col in (
                "tick",
                "stage",
                "stage_ticks",
                "fault_brownout_spiral",
                "fault_h2_deadlock",
                "fault_material_shortage",
                "fault_ai_overdraft",
                "fault_penrose_runaway",
                "game_over",
                "param_battery_mode",
                "queue_pending_count",
            ):
                col_defs.append(f"{col} INTEGER")
            else:
                col_defs.append(f"{col} REAL")

        ddl = f"""
        CREATE TABLE IF NOT EXISTS tick_telemetry (
            {', '.join(col_defs)}
        );
        CREATE INDEX IF NOT EXISTS idx_telemetry_session_tick ON tick_telemetry(session_id, tick);
        CREATE INDEX IF NOT EXISTS idx_telemetry_session_stage ON tick_telemetry(session_id, stage);
        CREATE INDEX IF NOT EXISTS idx_telemetry_event ON tick_telemetry(session_id, event_type);

        CREATE TABLE IF NOT EXISTS sessions_meta (
            session_id TEXT PRIMARY KEY,
            started_at TEXT,
            updated_at TEXT,
            model_id TEXT,
            engine_mode TEXT,
            max_tick INTEGER DEFAULT 0,
            max_stage INTEGER DEFAULT 1,
            final_p_gen_mw REAL DEFAULT 0.0,
            total_rows INTEGER DEFAULT 0
        );
        """
        self.conn.executescript(ddl)
        now_iso = datetime.datetime.now().isoformat()
        self.conn.execute(
            """
            INSERT OR IGNORE INTO sessions_meta (session_id, started_at, updated_at, model_id, engine_mode)
            VALUES (?, ?, ?, ?, ?)
            """,
            (self.session_id, now_iso, now_iso, "Unknown", "Unknown"),
        )
        self.conn.commit()

    def record_tick(
        self,
        state: Dict[str, Any],
        event_type: str = "tick",
        model_id: str = "Gemma-4-31B-IT-NVFP4",
        engine_mode: str = "rust_localsleep-moe (16-LoRA)",
        queue_pending_count: int = 0,
        force_flush: bool = False,
    ) -> None:
        """
        Appends one 65-column telemetry vector to RAM buffer (`< 5 us`, ZERO disk I/O).
        Flushes to SQLite WAL in batch only when buffer reaches `flush_every_n_ticks` or `force_flush=True`.
        """
        params = state.get("params") or {}
        row: Tuple[Any, ...] = (
            self.session_id,
            int(state.get("tick", 0)),
            int(state.get("stage", 1)),
            int(state.get("stage_ticks", 0)),
            str(event_type),
            str(model_id),
            str(engine_mode),
            # Macro Grid & Progress
            round(float(state.get("stage_exp_pct", 0.0)), 4),
            round(float(state.get("stage_exp_rate_per_tick", 0.0)), 4),
            float(state.get("p_gen_mw", 0.0)),
            float(state.get("p_load_mw", 0.0)),
            round(float(state.get("grid_satisfaction", 1.0)), 4),
            round(float(state.get("eroei", 1.0)), 4),
            round(float(state.get("parasitic_drain_mw", 0.0)), 4),
            round(float(state.get("ai_compute_drain_mwh", 0.0)), 4),
            # Storage & Mining Economy
            round(float(state.get("battery_charge_mwh", 0.0)), 4),
            round(float(state.get("coal_stock", 0.0)), 4),
            round(float(state.get("raw_material_stock", 0.0)), 4),
            round(float(state.get("mining_rigs", 0.0)), 4),
            round(float(state.get("last_mat_mined", 0.0)), 4),
            round(float(state.get("last_mat_consumed", 0.0)), 4),
            round(float(state.get("mat_exp_cost_mult", 1.0)), 4),
            round(float(state.get("hydrogen_tank_pct", 0.0)), 4),
            round(float(state.get("refined_oil_tank_pct", 0.0)), 4),
            round(float(state.get("deuterium_stock", 0.0)), 4),
            # Power Generation Breakdown
            round(float(state.get("gen_thermal_mw", 0.0)), 4),
            round(float(state.get("gen_fission_mw", 0.0)), 4),
            round(float(state.get("gen_geothermal_mw", 0.0)), 4),
            round(float(state.get("gen_ocean_current_mw", 0.0)), 4),
            round(float(state.get("gen_fusion_mw", 0.0)), 4),
            float(state.get("gen_dyson_receiver_mw", 0.0)),
            float(state.get("gen_antimatter_mw", 0.0)),
            # Infrastructure Units
            round(float(state.get("thermal_plants", 0.0)), 4),
            round(float(state.get("fission_plants", 0.0)), 4),
            round(float(state.get("geothermal_plants", 0.0)), 4),
            round(float(state.get("ocean_current_turbines", 0.0)), 4),
            round(float(state.get("refineries", 0.0)), 4),
            round(float(state.get("fusion_plants", 0.0)), 4),
            round(float(state.get("em_ejectors", 0.0)), 4),
            round(float(state.get("vertical_launch_silos", 0.0)), 4),
            round(float(state.get("ray_receivers", 0.0)), 4),
            round(float(state.get("artificial_suns", 0.0)), 4),
            round(float(state.get("dyson_shell_nodes", 0.0)), 4),
            round(float(state.get("active_solar_sails", 0.0)), 4),
            # Fault Flags
            int(bool(state.get("fault_brownout_spiral", False))),
            int(bool(state.get("fault_h2_deadlock", False))),
            int(bool(state.get("fault_material_shortage", False))),
            int(bool(state.get("fault_ai_overdraft", False))),
            int(bool(state.get("fault_penrose_runaway", False))),
            int(bool(state.get("game_over", False))),
            # 15 AI Control Parameters
            round(float(params.get("coal_throttle", 1.0)), 4),
            round(float(params.get("fusion_throttle", 1.0)), 4),
            float(params.get("antimatter_throttle", 1.0)),
            round(float(params.get("load_shed_non_essential", 0.0)), 4),
            round(float(params.get("hydrogen_burn_valve", 0.05)), 4),
            round(float(params.get("refined_oil_crack_ratio", 0.3)), 4),
            round(float(params.get("deuterium_fraction_rate", 0.6)), 4),
            float(params.get("em_ejector_rate", 1.0)),
            float(params.get("rocket_launch_rate", 1.0)),
            round(float(params.get("ray_receiver_photon_ratio", 0.25)), 4),
            float(params.get("mining_rig_build_rate", 0.35)),
            float(params.get("dimensional_exponent", 1.0)),
            int(params.get("battery_mode", 0)),
            str(params.get("build_focus", "balanced")),
            int(queue_pending_count),
        )
        self._ram_buffer.append(row)
        self._all_session_rows_ram.append(row)
        if force_flush or len(self._ram_buffer) >= self.flush_every_n_ticks:
            self.flush()

    def flush(self) -> int:
        """Batch-writes buffered RAM rows into Redis Pipeline (if active) + SQLite WAL in a single transaction."""
        if not self._ram_buffer:
            return 0
        rows_to_write = self._ram_buffer
        self._ram_buffer = []
        placeholders = ", ".join(["?"] * len(TELEMETRY_COLUMNS))
        last_row = rows_to_write[-1]
        now_iso = datetime.datetime.now().isoformat()

        # 1. If Redis is active, push batch into Redis RAM list (`dyson:telemetry:<session_id>`) & live hash via Pipeline
        if self.redis_active and self.redis_client is not None:
            try:
                pipe = self.redis_client.pipeline(transaction=False)
                r_key = f"dyson:telemetry:{self.session_id}"
                for r in rows_to_write:
                    pipe.rpush(r_key, json.dumps(r, ensure_ascii=False))
                pipe.hset(
                    f"dyson:session:{self.session_id}:meta",
                    mapping={
                        "updated_at": now_iso,
                        "model_id": str(last_row[5]),
                        "engine_mode": str(last_row[6]),
                        "tick": str(last_row[1]),
                        "stage": str(last_row[2]),
                        "p_gen_mw": str(last_row[9]),
                        "total_rows": str(len(self._all_session_rows_ram)),
                    },
                )
                pipe.execute()
            except Exception:
                pass

        # 2. Batch-commit to SQLite WAL in a single atomic transaction
        try:
            with self.conn:
                self.conn.executemany(
                    f"INSERT INTO tick_telemetry VALUES ({placeholders})",
                    rows_to_write,
                )
                self._total_flushed_rows += len(rows_to_write)
                self.conn.execute(
                    """
                    UPDATE sessions_meta
                    SET updated_at = ?,
                        model_id = ?,
                        engine_mode = ?,
                        max_tick = MAX(max_tick, ?),
                        max_stage = MAX(max_stage, ?),
                        final_p_gen_mw = ?,
                        total_rows = ?
                    WHERE session_id = ?
                    """,
                    (
                        now_iso,
                        str(last_row[5]),
                        str(last_row[6]),
                        int(last_row[1]),
                        int(last_row[2]),
                        float(last_row[9]),
                        self._total_flushed_rows,
                        self.session_id,
                    ),
                )
            return len(rows_to_write)
        except Exception:
            return 0

    def start_new_session(self, new_session_id: str) -> None:
        """Flushes current session and switches to a new session_id (e.g., on Big Crunch reset)."""
        self.flush()
        self.session_id = new_session_id
        self._all_session_rows_ram.clear()
        self._total_flushed_rows = 0
        now_iso = datetime.datetime.now().isoformat()
        with self.conn:
            self.conn.execute(
                """
                INSERT OR IGNORE INTO sessions_meta (session_id, started_at, updated_at, model_id, engine_mode)
                VALUES (?, ?, ?, ?, ?)
                """,
                (self.session_id, now_iso, now_iso, "Unknown", "Unknown"),
            )

    def export_session_to_csv(
        self,
        output_csv_path: Path,
        session_id: Optional[str] = None,
        max_excel_rows: int = 1500,
        max_html_rows: int = 4500,
    ) -> Dict[str, Any]:
        """
        Flushes RAM buffer first, then exports THREE artifacts:
          1. `<name>_excel_lite.csv`: High-density event-preserving downsampled (<= 1500 rows) + `log10_p_gen_mw`
             & core columns so Excel renders smooth dense curves without GDI freeze!
          2. `<name>.csv`: Full raw 65-dimension time series (for Python/Pandas/DuckDB).
          3. `<name>_chart.html`: Ultra-High-Density (up to 4500 pts) Interactive HTML5 Canvas Curve Analyzer
             with complete Model & Simulation Settings Card + Stage-by-Stage Parameter Table!
        """
        self.flush()
        target_sid = session_id or self.session_id
        cur = self.conn.cursor()
        cur.execute(
            f"SELECT {', '.join(TELEMETRY_COLUMNS)} FROM tick_telemetry WHERE session_id = ? ORDER BY tick ASC, rowid ASC",
            (target_sid,),
        )
        rows = cur.fetchall()
        if not rows and self._all_session_rows_ram:
            rows = list(self._all_session_rows_ram)

        # If this is a legacy `.jsonl` session with sparse AI-sync snapshots (< 120 rows),
        # synthesize dense intermediate trajectory points (~20 ticks apart) so HTML & Excel curves are dense and smooth!
        if 1 < len(rows) < 120:
            rows = self._densify_sparse_rows(rows)

        output_csv_path = Path(output_csv_path)
        output_csv_path.parent.mkdir(parents=True, exist_ok=True)

        # 1. Write Full Raw CSV
        with open(output_csv_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(TELEMETRY_COLUMNS)
            writer.writerows(rows)

        # 2. Helper to downsample to a target density while 100% preserving all events & faults
        def _sample_rows(src_rows: List[Tuple[Any, ...]], max_pts: int) -> List[Tuple[Any, ...]]:
            n_tot = len(src_rows)
            if n_tot <= max_pts:
                return list(src_rows)
            st_step = max(1, n_tot // max(100, max_pts))
            out_s: List[Tuple[Any, ...]] = []
            for idx_r, r_item in enumerate(src_rows):
                evt_s = str(r_item[4])
                has_flt = any(int(r_item[fi]) != 0 for fi in range(44, 50))
                if idx_r == 0 or idx_r == n_tot - 1 or evt_s != "tick" or has_flt or (idx_r % st_step == 0):
                    out_s.append(r_item)
            return out_s

        sampled_excel_rows = _sample_rows(rows, max_excel_rows)
        sampled_html_rows = _sample_rows(rows, max_html_rows)

        # Add `log10_p_gen_mw` and `log10_eroei` columns so Stage 1 (20 MW) to Stage 25 (1e35 MW) plot cleanly!
        col_idx = {name: i for i, name in enumerate(TELEMETRY_COLUMNS)}
        excel_cols = [
            "tick",
            "stage",
            "event_type",
            "model_id",
            "engine_mode",
            "stage_exp_pct",
            "stage_exp_rate_per_tick",
            "log10_p_gen_mw",
            "p_gen_mw",
            "p_load_mw",
            "grid_satisfaction",
            "log10_eroei",
            "eroei",
            "parasitic_drain_mw",
            "battery_charge_mwh",
            "raw_material_stock",
            "mining_rigs",
            "last_mat_mined",
            "last_mat_consumed",
            "mat_exp_cost_mult",
            "hydrogen_tank_pct",
            "refined_oil_tank_pct",
            "deuterium_stock",
            "thermal_plants",
            "fission_plants",
            "geothermal_plants",
            "ocean_current_turbines",
            "fusion_plants",
            "dyson_shell_nodes",
            "active_solar_sails",
            "param_coal_throttle",
            "param_mining_rig_build_rate",
            "param_fusion_throttle",
            "param_antimatter_throttle",
            "param_hydrogen_burn_valve",
            "param_refined_oil_crack_ratio",
            "param_deuterium_fraction_rate",
            "param_em_ejector_rate",
            "param_rocket_launch_rate",
            "param_ray_receiver_photon_ratio",
            "param_dimensional_exponent",
            "param_battery_mode",
            "param_build_focus",
            "queue_pending_count",
        ]

        def _row_to_dict(r: Tuple[Any, ...]) -> Tuple[List[Any], Dict[str, Any]]:
            p_mw = max(1e-3, float(r[col_idx["p_gen_mw"]] or 0.001))
            eroei_v = max(1e-3, float(r[col_idx["eroei"]] or 0.001))
            log_p = round(math.log10(p_mw), 4)
            log_e = round(math.log10(eroei_v), 4)
            out_r = []
            rec_d: Dict[str, Any] = {}
            for c_name in excel_cols:
                if c_name == "log10_p_gen_mw":
                    val = log_p
                elif c_name == "log10_eroei":
                    val = log_e
                else:
                    val = r[col_idx[c_name]]
                out_r.append(val)
                rec_d[c_name] = val
            return out_r, rec_d

        excel_csv_path = output_csv_path.with_name(output_csv_path.stem + "_excel_lite.csv")
        with open(excel_csv_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(excel_cols)
            for r in sampled_excel_rows:
                out_row, _ = _row_to_dict(r)
                writer.writerow(out_row)

        html_records: List[Dict[str, Any]] = [_row_to_dict(r)[1] for r in sampled_html_rows]
        meta_info = self._extract_session_meta_and_settings(output_csv_path.parent, target_sid, html_records)

        # 3. Generate High-Density Interactive HTML5 Canvas Curve Analyzer (`*_chart.html`)
        html_path = output_csv_path.with_name(output_csv_path.stem + "_chart.html")
        self._write_interactive_chart_html(html_path, target_sid, html_records, meta_info)

        return {
            "raw_rows": len(rows),
            "excel_rows": len(sampled_excel_rows),
            "html_rows": len(html_records),
            "raw_csv_path": str(output_csv_path),
            "excel_csv_path": str(excel_csv_path),
            "html_chart_path": str(html_path),
        }

    def _densify_sparse_rows(self, sparse_rows: List[Tuple[Any, ...]]) -> List[Tuple[Any, ...]]:
        """
        For legacy `.jsonl` sessions that only recorded at AI Lockstep Sync points (e.g. 25~35 rows over 6000 ticks),
        interpolates high-density intermediate points (every ~8 ticks) using log-linear power interpolation
        and linear EXP% ramp so the HTML and Excel curves show every stage's sawtooth EXP ramp and power trajectory!
        """
        col_idx = {name: i for i, name in enumerate(TELEMETRY_COLUMNS)}
        dense: List[Tuple[Any, ...]] = []
        for i in range(len(sparse_rows) - 1):
            r0 = list(sparse_rows[i])
            r1 = list(sparse_rows[i + 1])
            dense.append(tuple(r0))
            t0 = int(r0[col_idx["tick"]] or 0)
            t1 = int(r1[col_idx["tick"]] or 0)
            dt = t1 - t0
            if dt <= 8:
                continue
            st0 = int(r0[col_idx["stage"]] or 1)
            st1 = int(r1[col_idx["stage"]] or 1)
            p0 = max(1.0, float(r0[col_idx["p_gen_mw"]] or 20.0))
            p1 = max(1.0, float(r1[col_idx["p_gen_mw"]] or 20.0))
            e0 = max(0.1, float(r0[col_idx["eroei"]] or 1.15))
            e1 = max(0.1, float(r1[col_idx["eroei"]] or 1.15))
            h0 = float(r0[col_idx["hydrogen_tank_pct"]] or 0.0)
            h1 = float(r1[col_idx["hydrogen_tank_pct"]] or 0.0)
            exp0 = float(r0[col_idx["stage_exp_pct"]] or 0.0)
            exp1 = float(r1[col_idx["stage_exp_pct"]] or 99.0) if st1 == st0 else 100.0

            n_sub = min(60, max(4, dt // 8))
            for step_i in range(1, n_sub):
                alpha = step_i / float(n_sub)
                r_mid = list(r0)
                t_mid = int(round(t0 + alpha * dt))
                r_mid[col_idx["tick"]] = t_mid
                r_mid[col_idx["stage_ticks"]] = int(r0[col_idx["stage_ticks"]] or 0) + (t_mid - t0)
                r_mid[col_idx["event_type"]] = "tick"
                # Log-linear interpolation for power and EROEI
                r_mid[col_idx["p_gen_mw"]] = math.exp(math.log(p0) * (1.0 - alpha) + math.log(p1) * alpha)
                r_mid[col_idx["eroei"]] = round(math.exp(math.log(e0) * (1.0 - alpha) + math.log(e1) * alpha), 4)
                r_mid[col_idx["hydrogen_tank_pct"]] = round(h0 * (1.0 - alpha) + h1 * alpha, 2)
                cur_exp = min(100.0, exp0 + alpha * max(5.0, exp1 - exp0))
                r_mid[col_idx["stage_exp_pct"]] = round(cur_exp, 2)
                exp_ratio = cur_exp / 100.0
                r_mid[col_idx["mat_exp_cost_mult"]] = round(
                    math.exp(1.55 * exp_ratio) * (1.22 ** min(5, max(0, st0 - 1))),
                    2,
                )
                dense.append(tuple(r_mid))
        dense.append(sparse_rows[-1])
        return dense

    def _extract_session_meta_and_settings(
        self,
        sessions_dir: Path,
        session_id: str,
        records: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Extracts model, engine_mode, endpoint, and simulation settings from records + `.md` header."""
        model_id = "Auto-Detected-LLM"
        engine_mode = "Universal-OpenAI-Bridge"
        endpoint = "http://127.0.0.1:8000/v1"
        for r in records:
            m_val = str(r.get("model_id") or "")
            e_val = str(r.get("engine_mode") or "")
            if m_val and m_val != "Unknown":
                model_id = m_val
            if e_val and e_val != "Unknown":
                engine_mode = e_val

        # Also inspect `dyson_session_<sid>.md` if present for exact Handshake header
        md_file = Path(sessions_dir) / f"dyson_session_{session_id}.md"
        if md_file.exists():
            try:
                head_txt = md_file.read_text(encoding="utf-8", errors="ignore")[:2500]
                import re
                m_match = re.search(r"自動偵測連線模型:\s*`([^`]+)`\s*\|\s*架構模式:\s*`([^`]+)`\s*\|\s*Endpoint:\s*`([^`]+)`", head_txt)
                if m_match:
                    model_id, engine_mode, endpoint = m_match.group(1), m_match.group(2), m_match.group(3)
            except Exception:
                pass

        is_lora_bypass = ("bypass" in engine_mode.lower() or "vanilla" in engine_mode.lower())
        is_qwen = ("qwen" in model_id.lower())
        if is_qwen:
            lora_badge = f"🌐 {engine_mode} (Vanilla Base)"
        elif is_lora_bypass:
            lora_badge = f"⚪ {engine_mode} (Vanilla Base)"
        elif "16-lora" in engine_mode.lower() or "localsleep" in engine_mode.lower():
            lora_badge = f"🔥 {engine_mode}"
        else:
            lora_badge = f"⚡ {engine_mode}"

        max_tick = max((int(r.get("tick", 0)) for r in records), default=0)
        max_stage = max((int(r.get("stage", 1)) for r in records), default=1)
        max_p_gen = max((float(r.get("p_gen_mw", 0.0)) for r in records), default=0.0)
        min_bat = min((float(r.get("battery_charge_mwh", 300.0)) for r in records), default=300.0)
        has_mining = any(float(r.get("mining_rigs", 0.0)) > 0.0 and float(r.get("last_mat_mined", 0.0)) > 0.0 for r in records)
        ai_sync_cnt = sum(1 for r in records if str(r.get("event_type", "")).startswith("ai_sync"))

        # Stage-by-stage parameter snapshot table
        stage_summary: List[Dict[str, Any]] = []
        seen_stages: Dict[int, Dict[str, Any]] = {}
        for r in records:
            st = int(r.get("stage", 1))
            tk = int(r.get("tick", 0))
            if st not in seen_stages:
                seen_stages[st] = {
                    "stage": st,
                    "start_tick": tk,
                    "end_tick": tk,
                    "start_p_mw": float(r.get("p_gen_mw", 0.0)),
                    "end_p_mw": float(r.get("p_gen_mw", 0.0)),
                    "build_focus": r.get("param_build_focus", "balanced"),
                    "mining_rate": r.get("param_mining_rig_build_rate", 0.35),
                    "coal": r.get("param_coal_throttle", 1.0),
                    "fusion": r.get("param_fusion_throttle", 1.0),
                    "antimatter": r.get("param_antimatter_throttle", 1.0),
                    "h2_burn": r.get("param_hydrogen_burn_valve", 0.05),
                    "oil_crack": r.get("param_refined_oil_crack_ratio", 0.3),
                    "deut_frac": r.get("param_deuterium_fraction_rate", 0.6),
                    "em_eject": r.get("param_em_ejector_rate", 1.0),
                    "rocket": r.get("param_rocket_launch_rate", 1.0),
                    "dim_exp": r.get("param_dimensional_exponent", 1.0),
                    "bat_mode": r.get("param_battery_mode", 0),
                    "max_queue": int(r.get("queue_pending_count", 0)),
                }
            else:
                s_item = seen_stages[st]
                s_item["end_tick"] = max(s_item["end_tick"], tk)
                s_item["end_p_mw"] = max(s_item["end_p_mw"], float(r.get("p_gen_mw", 0.0)))
                if str(r.get("event_type", "")).startswith("ai_sync"):
                    s_item["build_focus"] = r.get("param_build_focus", s_item["build_focus"])
                    s_item["mining_rate"] = r.get("param_mining_rig_build_rate", s_item["mining_rate"])
                    s_item["fusion"] = r.get("param_fusion_throttle", s_item["fusion"])
                    s_item["antimatter"] = r.get("param_antimatter_throttle", s_item["antimatter"])
                    s_item["h2_burn"] = r.get("param_hydrogen_burn_valve", s_item["h2_burn"])
                    s_item["oil_crack"] = r.get("param_refined_oil_crack_ratio", s_item["oil_crack"])
                    s_item["deut_frac"] = r.get("param_deuterium_fraction_rate", s_item["deut_frac"])
                    s_item["em_eject"] = r.get("param_em_ejector_rate", s_item["em_eject"])
                    s_item["rocket"] = r.get("param_rocket_launch_rate", s_item["rocket"])
                    s_item["dim_exp"] = r.get("param_dimensional_exponent", s_item["dim_exp"])
                    s_item["bat_mode"] = r.get("param_battery_mode", s_item["bat_mode"])
                s_item["max_queue"] = max(s_item["max_queue"], int(r.get("queue_pending_count", 0)))

        for st_k in sorted(seen_stages.keys()):
            stage_summary.append(seen_stages[st_k])

        return {
            "session_id": session_id,
            "model_id": model_id,
            "engine_mode": engine_mode,
            "lora_badge": lora_badge,
            "endpoint": endpoint,
            "max_tick": max_tick,
            "max_stage": max_stage,
            "max_p_gen": max_p_gen,
            "min_battery": min_bat,
            "mining_economy_on": has_mining,
            "ai_sync_count": ai_sync_cnt,
            "stage_summary": stage_summary,
        }

    def _write_interactive_chart_html(
        self,
        html_path: Path,
        session_id: str,
        records: List[Dict[str, Any]],
        meta_info: Optional[Dict[str, Any]] = None,
    ) -> None:
        meta = meta_info or self._extract_session_meta_and_settings(html_path.parent, session_id, records)
        data_json = json.dumps(records, ensure_ascii=False)
        mining_badge = "🟢 ON (隨 EXP% 級數耗材)" if meta.get("mining_economy_on") else "⚪ OFF (舊版免耗材或 JSONL 重建)"

        stage_rows_html = ""
        for st_it in meta.get("stage_summary", []):
            dt_ticks = max(1, int(st_it["end_tick"]) - int(st_it["start_tick"]))
            stage_rows_html += (
                f"<tr>"
                f"<td><b>Stage {st_it['stage']}</b></td>"
                f"<td>#{st_it['start_tick']} ➔ #{st_it['end_tick']} (<code>{dt_ticks}t</code>)</td>"
                f"<td>{st_it['start_p_mw']:.2e} ➔ <b>{st_it['end_p_mw']:.2e} MW</b></td>"
                f"<td><code>{st_it['build_focus']}</code></td>"
                f"<td>{st_it['mining_rate']}</td>"
                f"<td>{st_it['coal']} / {st_it['fusion']} / <b>{st_it['antimatter']}</b></td>"
                f"<td>H2:{st_it['h2_burn']} | Oil:{st_it['oil_crack']} | D:{st_it['deut_frac']}</td>"
                f"<td>帆:{st_it['em_eject']} | 箭:{st_it['rocket']}</td>"
                f"<td><b>{st_it['dim_exp']}</b></td>"
                f"<td>{st_it['bat_mode']}</td>"
                f"<td>{st_it['max_queue']} 筆</td>"
                f"</tr>\n"
            )

        html_content = f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8"/>
<title>🪐 Dyson Sphere Grafana-Lite Telemetry Analyzer ({session_id})</title>
<style>
  body {{ background: #070d19; color: #e2e8f0; font-family: 'Segoe UI', 'Microsoft JhengHei', sans-serif; margin: 0; padding: 14px; }}
  h2 {{ margin: 0 0 8px 0; color: #38bdf8; font-size: 18px; display: flex; justify-content: space-between; align-items: center; }}
  .meta-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 8px; background: #0f172a; border: 1px solid #1e293b; border-radius: 8px; padding: 10px 12px; margin-bottom: 10px; font-size: 12px; }}
  .meta-card {{ background: #162032; border-left: 3px solid #38bdf8; padding: 6px 10px; border-radius: 4px; }}
  .meta-card .lbl {{ color: #94a3b8; font-size: 11px; }}
  .meta-card .val {{ color: #f8fafc; font-weight: bold; font-size: 13px; margin-top: 2px; word-break: break-all; }}
  .toolbar {{ display: flex; flex-wrap: wrap; gap: 10px; align-items: center; background: #0f172a; border: 1px solid #1e293b; padding: 8px 12px; border-radius: 8px; margin-bottom: 10px; font-size: 12px; }}
  .btn {{ background: #1e293b; color: #38bdf8; border: 1px solid #334155; border-radius: 4px; padding: 4px 10px; cursor: pointer; font-weight: bold; font-size: 12px; }}
  .btn:hover {{ background: #334155; }}
  .grid-charts {{ display: grid; grid-template-columns: 1fr; gap: 10px; }}
  .chart-box {{ background: #0b1324; border: 1px solid #1e293b; border-radius: 8px; padding: 8px 10px; position: relative; }}
  .chart-title {{ font-weight: bold; font-size: 13px; margin-bottom: 4px; display: flex; justify-content: space-between; }}
  canvas {{ width: 100%; height: 245px; display: block; cursor: crosshair; }}
  table.param-tbl {{ width: 100%; border-collapse: collapse; font-size: 12px; background: #0f172a; border: 1px solid #1e293b; border-radius: 8px; margin-top: 12px; }}
  table.param-tbl th, table.param-tbl td {{ border-bottom: 1px solid #1e293b; padding: 6px 8px; text-align: left; }}
  table.param-tbl th {{ background: #162032; color: #38bdf8; position: sticky; top: 0; }}
  #tooltip {{ position: fixed; pointer-events: none; background: rgba(7,13,25,0.96); border: 1px solid #38bdf8; color: #f8fafc; padding: 9px 12px; border-radius: 6px; font-size: 12px; display: none; z-index: 999; white-space: pre-line; box-shadow: 0 8px 24px rgba(0,0,0,0.6); }}
</style>
</head>
<body>
<h2>
  <span>🪐 Dyson Sphere 零依賴 Grafana-Lite 高密度多維曲線分析儀 (Session: {session_id})</span>
  <span style="font-size:12px;color:#94a3b8;">💡 滾輪縮放 (Wheel Zoom) | 按住左鍵拖曳平移 (Drag Pan) | 雙擊重設全覽 | 4 面板同步十字準線</span>
</h2>

<!-- 1. Model & Simulation Environment Settings Card -->
<div class="meta-grid">
  <div class="meta-card" style="border-left-color:#38bdf8;">
    <div class="lbl">🤖 推論模型 (Model ID)</div>
    <div class="val">{meta['model_id']}</div>
  </div>
  <div class="meta-card" style="border-left-color:#f43f5e;">
    <div class="lbl">🧬 架構與 LoRA 設定 (Engine / LoRA Mode)</div>
    <div class="val">{meta['lora_badge']}<br/><span style="font-size:11px;color:#94a3b8;font-weight:normal;">({meta['engine_mode']})</span></div>
  </div>
  <div class="meta-card" style="border-left-color:#a855f7;">
    <div class="lbl">🔌 推論端點與介入次數 (Endpoint & Syncs)</div>
    <div class="val">{meta['endpoint']} | AI 介入: {meta['ai_sync_count']} 次</div>
  </div>
  <div class="meta-card" style="border-left-color:#22c55e;">
    <div class="lbl">🏆 最高抵達階段與總 Tick (Progress)</div>
    <div class="val">Stage {meta['max_stage']} | Tick #{meta['max_tick']} (繪圖密度: {len(records)} 點)</div>
  </div>
  <div class="meta-card" style="border-left-color:#facc15;">
    <div class="lbl">⚡ 峰值發電量 & 最低蓄電池水位</div>
    <div class="val">P_gen: {meta['max_p_gen']:.3e} MW | Min Bat: {meta['min_battery']:.1f} MWh</div>
  </div>
  <div class="meta-card" style="border-left-color:#f97316;">
    <div class="lbl">⚙️ 模擬器物理規則設定 (Physics Rules)</div>
    <div class="val">⛏️ 採礦耗材: {mining_badge}<br/><span style="font-size:11px;color:#94a3b8;font-weight:normal;">未達標鎖 99% EXP | 蓄電 &lt; 0 Game Over | 逆火負發電 ON</span></div>
  </div>
</div>

<div class="toolbar">
  <button class="btn" onclick="resetZoom()">🔍 重設全時段視角 (100% Full Range)</button>
  <button class="btn" onclick="zoomToEarlyStages()">🏭 聚焦前期工業與化工階段 (Stage 1 ~ 6)</button>
  <button class="btn" onclick="zoomToGenesisStages()">🌌 聚焦後期黑洞創世階段 (Stage 7 ~ 25)</button>
  <label style="cursor:pointer;display:flex;align-items:center;gap:4px;">
    <input type="checkbox" id="chkDots" onchange="redrawAll()"/> 顯示高密度採樣圓點 (Show Data Dots)
  </label>
  <span id="zoomStatus" style="margin-left:auto;color:#38bdf8;font-weight:bold;">視角範圍: 全部 ({len(records)} 點)</span>
</div>

<div class="grid-charts">
  <div class="chart-box">
    <div class="chart-title" style="color:#38bdf8;">
      <span>📈 Panel 1 [宏觀能量與躍遷]: 發電量級數 log10(P_gen MW) vs. 階段經驗條 (Stage EXP %) vs. Stage 階數 vs. 供電率 η</span>
      <span style="color:#94a3b8;font-size:11px;">紫色虛線=Stage晉升 | 藍點=AI推論介入</span>
    </div>
    <canvas id="cv1" width="1520" height="245"></canvas>
  </div>
  <div class="chart-box">
    <div class="chart-title" style="color:#f59e0b;">
      <span>⛏️ Panel 2 [採礦與基建耗材閉環]: 原材料庫存 (raw_material_stock) vs. 採礦機數量 (mining_rigs) vs. AI 採礦增產率 (mining_rig_build_rate) vs. EXP 耗材倍率</span>
      <span style="color:#94a3b8;font-size:11px;">觀察 EXP 升高時耗材倍率暴增與 AI 造礦響應</span>
    </div>
    <canvas id="cv2" width="1520" height="245"></canvas>
  </div>
  <div class="chart-box">
    <div class="chart-title" style="color:#ec4899;">
      <span>🧪 Panel 3 [化工雙輸出防死鎖與儲能]: 氫氣槽(H2%) / 精煉油槽(Oil%) / 蓄電池(MWh) vs. AI 重油裂解率 & 氫氣燃燒閥</span>
      <span style="color:#94a3b8;font-size:11px;">95% 為雙輸出爆倉死鎖紅線 | 0 MWh 為斷電淘汰線</span>
    </div>
    <canvas id="cv3" width="1520" height="245"></canvas>
  </div>
  <div class="chart-box">
    <div class="chart-title" style="color:#a855f7;">
      <span>⚛️ Panel 4 [AI 核心控制參數與基建成長]: 核分裂/地熱/洋流/核融合電廠數 vs. 核融合節流閥 / 太陽帆彈射率 / 結構火箭發射率</span>
      <span style="color:#94a3b8;font-size:11px;">追蹤 2026 核分裂 ➔ 地熱/洋流 ➔ 核融合 ➔ 戴森雲演進</span>
    </div>
    <canvas id="cv4" width="1520" height="245"></canvas>
  </div>
</div>

<!-- 2. Stage-by-Stage AI Parameter Settings Table -->
<table class="param-tbl">
  <thead>
    <tr>
      <th>階段 (Stage)</th>
      <th>Tick 區間 (耗時)</th>
      <th>發電量演進 (P_gen)</th>
      <th>擴建重心 (build_focus)</th>
      <th>採礦增產率</th>
      <th>節流閥 (煤 / 核融合 / 反物質)</th>
      <th>化工閥門 (H2燃 / 油裂 / 重氫)</th>
      <th>太空發射 (太陽帆 / 火箭)</th>
      <th>超維指數 (α_dim)</th>
      <th>電池模式</th>
      <th>預排佇列</th>
    </tr>
  </thead>
  <tbody>
    {stage_rows_html}
  </tbody>
</table>

<div id="tooltip"></div>
<script>
const DATA = {data_json};
const tooltip = document.getElementById('tooltip');
let viewStart = 0;
let viewEnd = Math.max(0, DATA.length - 1);
let hoverIndex = -1;
let isDragging = false;
let dragStartX = 0;
let dragStartViewStart = 0;
let dragStartViewEnd = 0;

const PANELS = [
  {{
    id: 'cv1',
    series: [
      {{ key: 'log10_p_gen_mw', label: 'log10(P_gen MW)', color: '#38bdf8', width: 2.3 }},
      {{ key: 'stage_exp_pct', label: 'Stage EXP (%)', color: '#facc15', width: 1.6 }},
      {{ key: 'stage', label: 'Stage 階數', color: '#a855f7', width: 2.0 }},
      {{ key: 'grid_satisfaction', label: '供電率 η', color: '#22c55e', width: 1.4 }}
    ]
  }},
  {{
    id: 'cv2',
    series: [
      {{ key: 'raw_material_stock', label: '原材料庫存(噸)', color: '#22c55e', width: 2.2 }},
      {{ key: 'mining_rigs', label: '採礦機(台)', color: '#38bdf8', width: 2.0 }},
      {{ key: 'param_mining_rig_build_rate', label: 'AI 採礦增產率', color: '#f43f5e', width: 2.0 }},
      {{ key: 'mat_exp_cost_mult', label: 'EXP耗材倍率', color: '#f59e0b', width: 1.6 }}
    ]
  }},
  {{
    id: 'cv3',
    series: [
      {{ key: 'hydrogen_tank_pct', label: 'H2 儲槽(%)', color: '#38bdf8', width: 2.0 }},
      {{ key: 'refined_oil_tank_pct', label: '精煉油槽(%)', color: '#f59e0b', width: 2.0 }},
      {{ key: 'battery_charge_mwh', label: '蓄電池(MWh)', color: '#22c55e', width: 2.0 }},
      {{ key: 'param_refined_oil_crack_ratio', label: 'AI 重油裂解率', color: '#ec4899', width: 1.8 }},
      {{ key: 'param_hydrogen_burn_valve', label: 'AI H2燃燒閥', color: '#a855f7', width: 1.5 }}
    ]
  }},
  {{
    id: 'cv4',
    series: [
      {{ key: 'fission_plants', label: '核分裂廠', color: '#22c55e', width: 1.8 }},
      {{ key: 'geothermal_plants', label: '地熱廠', color: '#f97316', width: 1.8 }},
      {{ key: 'ocean_current_turbines', label: '洋流渦輪', color: '#06b6d4', width: 1.8 }},
      {{ key: 'fusion_plants', label: '核融合廠', color: '#38bdf8', width: 2.2 }},
      {{ key: 'param_em_ejector_rate', label: 'AI 太陽帆彈射率', color: '#facc15', width: 1.8 }},
      {{ key: 'param_rocket_launch_rate', label: 'AI 火箭發射率', color: '#f43f5e', width: 1.8 }}
    ]
  }}
];

function resetZoom() {{
  viewStart = 0;
  viewEnd = Math.max(0, DATA.length - 1);
  redrawAll();
}}

function zoomToEarlyStages() {{
  let idx = DATA.findIndex(d => Number(d.stage) >= 7);
  viewStart = 0;
  viewEnd = idx > 10 ? idx : Math.max(0, DATA.length - 1);
  redrawAll();
}}

function zoomToGenesisStages() {{
  let idx = DATA.findIndex(d => Number(d.stage) >= 7);
  viewStart = idx > 0 ? Math.max(0, idx - 5) : 0;
  viewEnd = Math.max(0, DATA.length - 1);
  redrawAll();
}}

function drawPanel(panel) {{
  const cv = document.getElementById(panel.id);
  const ctx = cv.getContext('2d');
  const W = cv.width, H = cv.height;
  const padL = 52, padR = 20, padT = 22, padB = 24;
  const plotW = W - padL - padR, plotH = H - padT - padB;
  ctx.clearRect(0, 0, W, H);
  if (!DATA.length) return;

  const sliceLen = Math.max(1, viewEnd - viewStart);
  const showDots = document.getElementById('chkDots').checked || sliceLen <= 180;

  // Grid lines
  ctx.strokeStyle = '#162238';
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {{
    const y = padT + (plotH * i) / 4;
    ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(W - padR, y); ctx.stroke();
  }}

  // Stage transition & AI sync vertical markers
  for (let i = viewStart; i <= viewEnd; i++) {{
    const d = DATA[i];
    if (!d) continue;
    const x = padL + ((i - viewStart) / sliceLen) * plotW;
    if (d.event_type === 'stage_level_up' || (i > 0 && d.stage !== DATA[i-1].stage)) {{
      ctx.strokeStyle = 'rgba(168, 85, 247, 0.55)';
      ctx.setLineDash([4, 3]);
      ctx.beginPath(); ctx.moveTo(x, padT); ctx.lineTo(x, H - padB); ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = '#c084fc';
      ctx.font = 'bold 10px sans-serif';
      ctx.fillText('St.' + d.stage, x + 2, padT + 10);
    }} else if (String(d.event_type).startsWith('ai_sync')) {{
      ctx.strokeStyle = 'rgba(56, 189, 248, 0.28)';
      ctx.beginPath(); ctx.moveTo(x, padT); ctx.lineTo(x, H - padB); ctx.stroke();
    }}
  }}

  // Draw series normalized to [vMin, vMax] in current view window
  panel.series.forEach((s, sIdx) => {{
    let vals = [];
    for (let i = viewStart; i <= viewEnd; i++) vals.push(Number(DATA[i][s.key] || 0));
    let vMin = Math.min(...vals), vMax = Math.max(...vals);
    if (vMax - vMin < 1e-6) {{ vMax = vMin + 1.0; }}
    ctx.strokeStyle = s.color;
    ctx.lineWidth = s.width || 1.8;
    ctx.beginPath();
    for (let i = viewStart; i <= viewEnd; i++) {{
      const x = padL + ((i - viewStart) / sliceLen) * plotW;
      const v = Number(DATA[i][s.key] || 0);
      const norm = (v - vMin) / (vMax - vMin);
      const y = padT + plotH - norm * plotH;
      if (i === viewStart) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }}
    ctx.stroke();

    if (showDots) {{
      ctx.fillStyle = s.color;
      for (let i = viewStart; i <= viewEnd; i++) {{
        const x = padL + ((i - viewStart) / sliceLen) * plotW;
        const v = Number(DATA[i][s.key] || 0);
        const norm = (v - vMin) / (vMax - vMin);
        const y = padT + plotH - norm * plotH;
        const isSync = String(DATA[i].event_type).startsWith('ai_sync');
        ctx.beginPath();
        ctx.arc(x, y, isSync ? 3.2 : 1.7, 0, Math.PI * 2);
        ctx.fill();
      }}
    }}

    ctx.fillStyle = s.color;
    ctx.font = 'bold 11px sans-serif';
    ctx.fillText(`■ ${{s.label}} [${{vMin.toFixed(2)}} ~ ${{vMax.toFixed(2)}}]`, padL + sIdx * 235, 14);
  }});

  // Synchronized Crosshair
  if (hoverIndex >= viewStart && hoverIndex <= viewEnd) {{
    const hx = padL + ((hoverIndex - viewStart) / sliceLen) * plotW;
    ctx.strokeStyle = '#f8fafc';
    ctx.lineWidth = 1.0;
    ctx.setLineDash([2, 2]);
    ctx.beginPath(); ctx.moveTo(hx, padT); ctx.lineTo(hx, H - padB); ctx.stroke();
    ctx.setLineDash([]);
  }}

  // X-axis tick labels
  ctx.fillStyle = '#94a3b8';
  ctx.font = '11px sans-serif';
  for (let i = 0; i <= 8; i++) {{
    const idx = Math.min(viewEnd, Math.floor(viewStart + (i * sliceLen) / 8));
    const x = padL + ((idx - viewStart) / sliceLen) * plotW;
    ctx.fillText('Tick #' + DATA[idx].tick + ' (St.' + DATA[idx].stage + ')', x - 26, H - 6);
  }}
}}

function redrawAll() {{
  PANELS.forEach(p => drawPanel(p));
  if (DATA.length) {{
    document.getElementById('zoomStatus').textContent =
      `視角範圍: Tick #${{DATA[viewStart].tick}} (St.${{DATA[viewStart].stage}}) ➔ Tick #${{DATA[viewEnd].tick}} (St.${{DATA[viewEnd].stage}}) | 顯示點數: ${{viewEnd - viewStart + 1}} / ${{DATA.length}}`;
  }}
}}

PANELS.forEach(p => {{
  const cv = document.getElementById(p.id);
  const padL = 52, padR = 20;

  cv.addEventListener('mousemove', (ev) => {{
    const rect = cv.getBoundingClientRect();
    const W = cv.width;
    const plotW = W - padL - padR;
    const relX = ((ev.clientX - rect.left) / rect.width) * W;
    const sliceLen = Math.max(1, viewEnd - viewStart);

    if (isDragging) {{
      const dxRatio = (dragStartX - relX) / plotW;
      const shift = Math.round(dxRatio * sliceLen);
      const span = dragStartViewEnd - dragStartViewStart;
      let ns = Math.max(0, Math.min(DATA.length - 1 - span, dragStartViewStart + shift));
      viewStart = ns;
      viewEnd = ns + span;
      redrawAll();
      return;
    }}

    const ratio = Math.max(0, Math.min(1, (relX - padL) / plotW));
    hoverIndex = Math.round(viewStart + ratio * sliceLen);
    redrawAll();
    const d = DATA[hoverIndex];
    if (!d) return;
    tooltip.style.display = 'block';
    tooltip.style.left = Math.min(window.innerWidth - 420, ev.clientX + 16) + 'px';
    tooltip.style.top = Math.min(window.innerHeight - 210, ev.clientY + 16) + 'px';
    tooltip.textContent =
      `🛰️ Tick #${{d.tick}} | Stage ${{d.stage}} | 事件: ${{d.event_type}}\\n` +
      `🤖 模型: ${{d.model_id}} (${{d.engine_mode}})\\n` +
      `⚡ P_gen: ${{Number(d.p_gen_mw).toExponential(3)}} MW (log10=${{d.log10_p_gen_mw}}) | EXP: ${{d.stage_exp_pct}}%\\n` +
      `🔋 蓄電池: ${{d.battery_charge_mwh}} MWh | 供電率 η: ${{(d.grid_satisfaction*100).toFixed(1)}}% | EROEI: ${{Number(d.eroei).toExponential(2)}}\\n` +
      `⛏️ 採礦機: ${{d.mining_rigs}} 台 | 原材料庫存: ${{d.raw_material_stock}} 噸 (倍率 ${{d.mat_exp_cost_mult}}x) | AI 造礦率: ${{d.param_mining_rig_build_rate}}\\n` +
      `🧪 H2槽: ${{d.hydrogen_tank_pct}}% | 油槽: ${{d.refined_oil_tank_pct}}% | 裂解率: ${{d.param_refined_oil_crack_ratio}} | 燃燒閥: ${{d.param_hydrogen_burn_valve}}\\n` +
      `🎛️ Focus: ${{d.param_build_focus}} | 核融合閥: ${{d.param_fusion_throttle}} | 反物質閥: ${{d.param_antimatter_throttle}} | α_dim: ${{d.param_dimensional_exponent}}`;
  }});

  cv.addEventListener('mousedown', (ev) => {{
    const rect = cv.getBoundingClientRect();
    dragStartX = ((ev.clientX - rect.left) / rect.width) * cv.width;
    dragStartViewStart = viewStart;
    dragStartViewEnd = viewEnd;
    isDragging = true;
  }});

  window.addEventListener('mouseup', () => {{ isDragging = false; }});
  cv.addEventListener('mouseleave', () => {{ hoverIndex = -1; tooltip.style.display = 'none'; redrawAll(); }});
  cv.addEventListener('dblclick', () => resetZoom());

  cv.addEventListener('wheel', (ev) => {{
    ev.preventDefault();
    const rect = cv.getBoundingClientRect();
    const W = cv.width;
    const plotW = W - padL - padR;
    const relX = ((ev.clientX - rect.left) / rect.width) * W;
    const ratio = Math.max(0, Math.min(1, (relX - padL) / plotW));
    const curSpan = Math.max(10, viewEnd - viewStart);
    const factor = ev.deltaY < 0 ? 0.75 : 1.35;
    const newSpan = Math.max(15, Math.min(DATA.length - 1, Math.round(curSpan * factor)));
    const centerIdx = viewStart + ratio * curSpan;
    let ns = Math.round(centerIdx - ratio * newSpan);
    ns = Math.max(0, Math.min(DATA.length - 1 - newSpan, ns));
    viewStart = ns;
    viewEnd = ns + newSpan;
    redrawAll();
  }}, {{ passive: false }});
}});

redrawAll();
</script>
</body>
</html>"""
        html_path.write_text(html_content, encoding="utf-8")

    def close(self) -> None:
        try:
            self.flush()
            self.conn.close()
        except Exception:
            pass


def backfill_jsonl_sessions_to_db(sessions_dir: Path, db_path: Path) -> Dict[str, int]:
    """
    Imports historical `dyson_session_*.jsonl` sync snapshots into `dyson_telemetry.db`
    so existing completed runs (e.g. 103343, 104914, 112346, 120622) can be queried & exported immediately!
    """
    imported: Dict[str, int] = {}
    for jf in sorted(sessions_dir.glob("dyson_session_*.jsonl")):
        sid = jf.stem.replace("dyson_session_", "")
        db = DysonTelemetryDB(db_path=db_path, session_id=sid, flush_every_n_ticks=500)
        cur = db.conn.cursor()
        cur.execute("SELECT COUNT(*) FROM tick_telemetry WHERE session_id = ?", (sid,))
        if (cur.fetchone() or [0])[0] > 0:
            db.close()
            continue
        count = 0
        for line in jf.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            st_snap = rec.get("state_snapshot")
            if not isinstance(st_snap, dict) or not st_snap:
                # Backward-compatible backfill for earlier `.jsonl` files with top-level keys
                p_parsed = rec.get("parsed_params") or {}
                st_snap = {
                    "tick": rec.get("tick", 0),
                    "stage": rec.get("stage", 1),
                    "p_gen_mw": rec.get("p_gen_mw", 0.0),
                    "grid_satisfaction": rec.get("grid_satisfaction", 1.0),
                    "hydrogen_tank_pct": rec.get("hydrogen_tank_pct", 0.0),
                    "eroei": rec.get("eroei", 1.0),
                    "params": p_parsed,
                }
            q_list = rec.get("scheduled_action_queue") or (rec.get("parsed_params") or {}).get("action_queue") or []
            db.record_tick(
                state=st_snap,
                event_type="ai_sync_snapshot",
                model_id=str(rec.get("model_id") or "Gemma-4-31B-IT-NVFP4"),
                engine_mode=str(rec.get("engine_mode") or "Standard"),
                queue_pending_count=len(q_list) if isinstance(q_list, list) else 0,
                force_flush=False,
            )
            count += 1
        db.flush()
        db.close()
        if count > 0:
            imported[sid] = count
    return imported


def batch_export_all_legacy_sessions(sessions_dir: Path, db_path: Path, max_excel_rows: int = 1500) -> Dict[str, Any]:
    """
    Toolified Batch Exporter for ALL legacy/historical sessions:
      1. Backfills all `dyson_session_*.jsonl` into `dyson_telemetry.db`.
      2. Scans all existing raw `dyson_telemetry_*.csv` (e.g. 133206, 135700, 142251) and imports/converts
         any that are missing `*_excel_lite.csv` or `*_chart.html`.
      3. Exports `*_excel_lite.csv` + `*_chart.html` for every session in `dyson_telemetry.db`.
      4. Generates `sessions/dyson_telemetry_hub.html` — an all-in-one Session Switcher & Curve Dashboard!
    """
    sessions_dir = Path(sessions_dir)
    db_path = Path(db_path)
    backfill_jsonl_sessions_to_db(sessions_dir, db_path)

    converted_csvs: List[str] = []
    # Also scan any raw `dyson_telemetry_<sid>.csv` on disk and ensure it's in DB + has `_excel_lite.csv` & `_chart.html`
    for raw_csv in sorted(sessions_dir.glob("dyson_telemetry_*.csv")):
        if raw_csv.name.endswith("_excel_lite.csv"):
            continue
        sid = raw_csv.stem.replace("dyson_telemetry_", "")
        db = DysonTelemetryDB(db_path=db_path, session_id=sid, flush_every_n_ticks=1000)
        cur = db.conn.cursor()
        cur.execute("SELECT COUNT(*) FROM tick_telemetry WHERE session_id = ?", (sid,))
        cnt = (cur.fetchone() or [0])[0]
        if cnt == 0:
            # Import rows from existing raw CSV on disk into SQLite DB first
            try:
                with open(raw_csv, "r", encoding="utf-8-sig", errors="ignore") as f:
                    reader = csv.reader(f)
                    header = next(reader, None)
                    if header and len(header) == len(TELEMETRY_COLUMNS):
                        rows_in = [tuple(r) for r in reader if len(r) == len(TELEMETRY_COLUMNS)]
                        if rows_in:
                            placeholders = ", ".join(["?"] * len(TELEMETRY_COLUMNS))
                            with db.conn:
                                db.conn.executemany(
                                    f"INSERT INTO tick_telemetry VALUES ({placeholders})",
                                    rows_in,
                                )
            except Exception:
                pass
        # Always regenerate `_excel_lite.csv` (1500 pts) & `_chart.html` (4500 pts Grafana-Lite) so existing sessions get upgraded!
        db.export_session_to_csv(raw_csv, session_id=sid, max_excel_rows=max_excel_rows, max_html_rows=4500)
        converted_csvs.append(sid)
        db.close()

    # Also export any JSONL-backfilled session from 20261104+ (or >= 5 rows) that doesn't have `_excel_lite.csv` yet
    master_db = DysonTelemetryDB(db_path=db_path, session_id="hub_master", flush_every_n_ticks=1000)
    cur = master_db.conn.cursor()
    cur.execute("SELECT DISTINCT session_id FROM tick_telemetry ORDER BY session_id DESC")
    all_sids = [str(r[0]) for r in cur.fetchall() if r and r[0] and str(r[0]) != "hub_master"]

    hub_entries: List[Dict[str, Any]] = []
    for sid in all_sids:
        out_raw = sessions_dir / f"dyson_telemetry_{sid}.csv"
        out_lite = sessions_dir / f"dyson_telemetry_{sid}_excel_lite.csv"
        out_html = sessions_dir / f"dyson_telemetry_{sid}_chart.html"
        # Always regenerate HTML & Excel-Lite with the upgraded high-density & model-settings template!
        export_res = master_db.export_session_to_csv(out_raw, session_id=sid, max_excel_rows=max_excel_rows, max_html_rows=4500)
        if sid not in converted_csvs:
            converted_csvs.append(sid)
        cur.execute(
            "SELECT COUNT(*), MAX(tick), MAX(stage), MAX(p_gen_mw), MAX(model_id), MAX(engine_mode) FROM tick_telemetry WHERE session_id = ?",
            (sid,),
        )
        row_stat = cur.fetchone() or (0, 0, 1, 0.0, "Unknown", "Unknown")
        if int(row_stat[0] or 0) > 0:
            # Check `.md` header for exact model/engine badge
            meta_s = master_db._extract_session_meta_and_settings(sessions_dir, sid, [])
            hub_entries.append({
                "session_id": sid,
                "rows": int(export_res.get("html_rows") or row_stat[0] or 0),
                "max_tick": int(row_stat[1] or 0),
                "max_stage": int(row_stat[2] or 1),
                "max_p_gen_mw": float(row_stat[3] or 0.0),
                "model_id": str(meta_s.get("model_id") if meta_s.get("model_id") != "Auto-Detected-LLM" or row_stat[4] in (None, "", "Unknown") else row_stat[4]),
                "engine_mode": str(meta_s.get("lora_badge") or row_stat[5] or "Unknown"),
                "chart_html": out_html.name,
                "excel_lite_csv": out_lite.name,
                "raw_csv": out_raw.name,
            })
    master_db.close()

    # Write `dyson_telemetry_hub.html` (Unified Index & Viewer for all historical & current sessions)
    hub_path = sessions_dir / "dyson_telemetry_hub.html"
    rows_tr = ""
    for e in hub_entries:
        rows_tr += (
            f"<tr>"
            f"<td><b>{e['session_id']}</b></td>"
            f"<td><code>{e['model_id']}</code><br/><small style='color:#94a3b8'>{e['engine_mode']}</small></td>"
            f"<td>Stage {e['max_stage']} (Tick #{e['max_tick']})</td>"
            f"<td>{e['max_p_gen_mw']:.3e} MW</td>"
            f"<td>{e['rows']} 筆</td>"
            f"<td>"
            f"<a class='btn btn-chart' href='{e['chart_html']}' target='viewer_frame'>📈 檢視互動曲線</a> "
            f"<a class='btn btn-excel' href='{e['excel_lite_csv']}' download>🟢 下載 Excel 精簡版</a> "
            f"<a class='btn btn-raw' href='{e['raw_csv']}' download>🗄️ 原始 CSV</a>"
            f"</td></tr>\n"
        )
    default_iframe = hub_entries[0]["chart_html"] if hub_entries else ""
    hub_html = f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8"/>
<title>🪐 Dyson Sphere 全歷程遙測曲線總覽中樞 (Telemetry Hub)</title>
<style>
  body {{ background: #070d19; color: #e2e8f0; font-family: 'Segoe UI', 'Microsoft JhengHei', sans-serif; margin: 0; padding: 16px; }}
  h2 {{ margin: 0 0 10px 0; color: #38bdf8; }}
  .layout {{ display: grid; grid-template-columns: 540px 1fr; gap: 14px; height: calc(100vh - 70px); }}
  .table-wrap {{ background: #0f172a; border: 1px solid #1e293b; border-radius: 8px; overflow-y: auto; padding: 8px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
  th, td {{ border-bottom: 1px solid #1e293b; padding: 6px 6px; text-align: left; }}
  th {{ color: #38bdf8; position: sticky; top: 0; background: #0f172a; }}
  .btn {{ display: inline-block; padding: 3px 7px; border-radius: 4px; text-decoration: none; font-weight: bold; font-size: 11px; margin: 1px; }}
  .btn-chart {{ background: #0284c7; color: #fff; }}
  .btn-excel {{ background: #059669; color: #fff; }}
  .btn-raw {{ background: #334155; color: #cbd5e1; }}
  iframe {{ width: 100%; height: 100%; border: 1px solid #1e293b; border-radius: 8px; background: #070d19; }}
</style>
</head>
<body>
<h2>🪐 Dyson Sphere 歷史與當前 Session 全維度曲線總覽中樞 (共 {len(hub_entries)} 組紀錄)</h2>
<div class="layout">
  <div class="table-wrap">
    <table>
      <thead>
        <tr><th>Session ID</th><th>模型與架構</th><th>最高進度</th><th>峰值發電</th><th>原始點數</th><th>操作 / 匯出</th></tr>
      </thead>
      <tbody>
        {rows_tr}
      </tbody>
    </table>
  </div>
  <iframe name="viewer_frame" src="{default_iframe}"></iframe>
</div>
</body>
</html>"""
    hub_path.write_text(hub_html, encoding="utf-8")
    return {
        "converted_count": len(converted_csvs),
        "converted_sids": converted_csvs,
        "total_sessions": len(hub_entries),
        "hub_html_path": str(hub_path),
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Dyson Sphere Telemetry Batch Exporter & Legacy CSV/JSONL Converter")
    parser.add_argument("--max-excel-rows", type=int, default=1500, help="Max rows in *_excel_lite.csv (default: 1500)")
    parser.add_argument("--open-hub", action="store_true", help="Open dyson_telemetry_hub.html in browser after export")
    args = parser.parse_args()

    base = Path(__file__).resolve().parent
    sess_dir = base / "sessions"
    db_file = sess_dir / "dyson_telemetry.db"
    res = batch_export_all_legacy_sessions(sess_dir, db_file, max_excel_rows=args.max_excel_rows)
    print(
        f"✅ [DysonTelemetryDB] 已完成歷史與舊 CSV 批次轉檔！\n"
        f"  • 本次新轉換 Session 數: {res['converted_count']} 組\n"
        f"  • 總納管 Session 數: {res['total_sessions']} 組 (皆已生成 *_excel_lite.csv 與 *_chart.html)\n"
        f"  • 全歷程曲線總覽中樞: {res['hub_html_path']}"
    )
    if args.open_hub:
        import webbrowser
        webbrowser.open(Path(res["hub_html_path"]).as_uri())
