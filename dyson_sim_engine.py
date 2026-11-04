#!/usr/bin/env python3
"""
dyson_sim_engine.py - Unified Rust/Python Dyson Sphere Dynamic System Engine & Action Parser
=============================================================================================
Wraps `dyson_sim_core.RustDysonSimulator` (compiled from `src/lib.rs`) with a 100% compatible
pure-Python twin fallback, generates structured Tick-State Prompts across 4 Mission Stages
(Earth -> Solar System Dyson Sphere), and parses LLM responses into dynamic system parameters.
"""

import json
import math
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

STAGE_LIST_FILE = Path(__file__).resolve().parent / "stage_list.json"

try:
    import dyson_sim_core  # type: ignore
    HAS_RUST_CORE = True
except ImportError:
    HAS_RUST_CORE = False


STAGE_METADATA: Dict[int, Dict[str, Any]] = {
    1: {
        "name": "Stage 1: 🌍 地球赤道微電網自舉 (Terra Equatorial Bootstrap)",
        "recommended_camera": "earth_25d",
        "goal_desc": "維持供電率 η >= 100% 且總發電量突破 55 MW（防止微隕石沙塵暴引發『停電 -> 礦機減速 -> 斷煤熄火』的死亡螺旋）。",
        "target_mw": 55.0,
    },
    2: {
        "name": "Stage 2: 🧪 精煉裂解與重氫防爆倉 (Deuterium & Cracking Loop)",
        "recommended_camera": "earth_25d",
        "goal_desc": "總發電量突破 450 MW 且氫氣儲槽 (H2 Tank) 控制在 < 85%（防止『氫氣 100% 滿倉 -> 精煉廠停擺 -> 重氫斷炊』的雙輸出死鎖）。",
        "target_mw": 450.0,
    },
    3: {
        "name": "Stage 3: ☀️ 太陽系電磁彈射與戴森雲 (Helios Dyson Swarm)",
        "recommended_camera": "solar_3d",
        "goal_desc": "從地球向太陽軌道彈射 >= 1,200 面太陽帆、總發電量突破 4,500 MW (4.5 GW) 且能源回報率 EROEI >= 1.5。",
        "target_mw": 4500.0,
    },
    4: {
        "name": "Stage 4: 🪐 恆星級戴森球殼與反物質自癒 (Dyson Shell Autopoiesis)",
        "recommended_camera": "dyson_shell_3d",
        "goal_desc": "發射結構火箭構築永久戴森球節點 (Nodes >= 100)、調配高能光子合成反物質燃料棒，達成 >= 50,000 MW (50 GW) 恆星級正循環！",
        "target_mw": 50000.0,
    },
    5: {
        "name": "Stage 5: 🌌 俄羅斯套娃腦與跨星系曲速網格 (Matrioshka Brain & Warp Grid)",
        "recommended_camera": "matrioshka_3d",
        "goal_desc": "構築三層同心俄羅斯套娃戴森殼 (Matrioshka Shells) 與跨恆星系曲速能量光束，衝刺 >= 250,000 MW (250 GW) 卡爾達肖夫 II.5 型文明！",
        "target_mw": 250000.0,
    },
    6: {
        "name": "Stage 6: 🕳️ 黑洞彭羅斯與霍金輻射量子迴路 (Hawking-Penrose Quantum Singularity)",
        "recommended_camera": "blackhole_3d",
        "goal_desc": "以特殊奈米機械網包覆黑洞拉伸視界，利用『真空漲落＋虛粒子對稱性破壞』之霍金輻射能差構成高維量子計算迴路（AI 推論反饋真空負熵），衝刺 >= 1,000,000 MW (1 TW) Type-III/Ω 文明！",
        "target_mw": 1000000.0,
        "years_per_tick": 10000.0,
        "lore": "文明將克爾黑洞拉伸視界包裹於奈米機械量子網中，以虛粒子對稱性破缺驅動高維計算。",
    },
}


def load_or_init_stage_list() -> Dict[int, Dict[str, Any]]:
    if STAGE_LIST_FILE.exists():
        try:
            raw = json.loads(STAGE_LIST_FILE.read_text(encoding="utf-8"))
            for k, v in raw.items():
                STAGE_METADATA[int(k)] = v
        except Exception:
            pass
    save_stage_list()
    return STAGE_METADATA


def save_stage_list() -> None:
    try:
        serializable = {str(k): v for k, v in sorted(STAGE_METADATA.items(), key=lambda x: x[0])}
        STAGE_LIST_FILE.write_text(json.dumps(serializable, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def reset_stage_list_to_base_6() -> None:
    """Resets `STAGE_METADATA` and `stage_list.json` back to Stages 1~6 after a Big Crunch Epoch Reset."""
    keys_to_remove = [k for k in STAGE_METADATA.keys() if k > 6]
    for k in keys_to_remove:
        STAGE_METADATA.pop(k, None)
    save_stage_list()


def register_ai_genesis_stage(
    genesis_obj: Dict[str, Any],
    next_stage_id: int,
    authored_by: str = "Gemma-4-31B + 16-LoRA (rust_localsleep-moe)",
) -> Dict[str, Any]:
    st_id = int(genesis_obj.get("stage") or next_stage_id)
    prev_meta = STAGE_METADATA.get(st_id - 1, STAGE_METADATA[6])
    raw_name = str(genesis_obj.get("name") or f"Stage {st_id}: 🌌 AI 創世超維文明 (AI Genesis Stage {st_id})")
    if not raw_name.lower().startswith("stage"):
        raw_name = f"Stage {st_id}: {raw_name}"
    target_mw = min(1e220, max(float(prev_meta.get("target_mw", 1000000.0)) * 3.5, float(genesis_obj.get("target_mw") or 5000000.0)))
    y_per_tick = min(1e100, max(float(prev_meta.get("years_per_tick", 10000.0)), float(genesis_obj.get("years_per_tick") or 100000.0)))
    entry = {
        "name": raw_name,
        "recommended_camera": "blackhole_3d",
        "goal_desc": str(genesis_obj.get("goal_desc") or f"維持高維量子迴路與底層重氫能量閉環，衝刺 >= {target_mw:,.0f} MW！"),
        "lore": str(genesis_obj.get("lore") or f"由 {authored_by} 自主推演誕生之新宇宙文明篇章。"),
        "target_mw": target_mw,
        "years_per_tick": y_per_tick,
        "visual_theme": str(genesis_obj.get("visual_theme") or "singularity_gold"),
        "authored_by": str(genesis_obj.get("authored_by") or authored_by),
    }
    STAGE_METADATA[st_id] = entry
    save_stage_list()
    return entry


load_or_init_stage_list()


class FallbackPythonDysonSimulator:
    """Pure-Python twin of `src/lib.rs::RustDysonSimulator` with identical differential equations."""

    def __init__(self) -> None:
        self.state: Dict[str, Any] = {}
        self.last_sync_gen_mw: float = 28.0
        self.last_sync_eroei: float = 1.15
        self.reset_stage(1)

    def reset_stage(self, stage: int) -> str:
        max_known = max(STAGE_METADATA.keys()) if STAGE_METADATA else 6
        st = max(1, min(max_known, int(stage)))
        prev_auto = self.state.get("auto_advance_stage", True) if isinstance(self.state, dict) else True
        prev_mining_en = self.state.get("enable_mining_economy", True) if isinstance(self.state, dict) else True
        prev_epoch = int(self.state.get("cosmic_cycle_epoch", 2)) if isinstance(self.state, dict) else 2
        prev_relic = str(self.state.get("prev_universe_relic", "Epoch #1 Stage 17: 普朗克尺度真空相變與宇宙底層代碼重寫 (P_gen=1.67e30 MW)")) if isinstance(self.state, dict) else ""
        self.state = {
            "tick": 0,
            "stage_ticks": 0,
            "stage": st,
            "cosmic_cycle_epoch": prev_epoch,
            "prev_universe_relic": prev_relic,
            "stage_exp_pct": 0.0,
            "stage_exp_rate_per_tick": 0.0,
            "prev_tick_gen_mw": 24.0,
            "last_heartbeat_milestone": 0,
            "auto_advance_stage": prev_auto,
            "enable_mining_economy": prev_mining_en,
            "p_gen_mw": 24.0,
            "p_req_mw": 20.0,
            "p_net_mw": 4.0,
            "grid_satisfaction": 1.0,
            "battery_charge_mwh": 120.0,
            "battery_capacity_mwh": 300.0,
            "ai_compute_coeff_mwh_per_s": 10.0,
            "last_ai_infer_sec": 0.0,
            "last_ai_consumed_mwh": 0.0,
            "total_ai_consumed_mwh": 0.0,
            "fault_ai_overdraft": False,
            "game_over": False,
            "game_over_reason": "",
            "cosmic_years": 0.0,
            "years_per_tick": 1.0,
            "blackhole_lifespan_years": 100_000_000.0,
            "blackhole_lifespan_pct": 100.0,
            "last_ai_bh_years_cost": 0.0,
            "gen_solar_wind_mw": 8.4,
            "gen_fission_mw": 8.4,
            "gen_geothermal_mw": 0.0,
            "gen_ocean_current_mw": 0.0,
            "gen_thermal_mw": 12.2,
            "gen_fusion_mw": 0.0,
            "gen_dyson_receiver_mw": 0.0,
            "gen_antimatter_mw": 0.0,
            "parasitic_drain_mw": 0.0,
            # Stage 1 (Tick 0~99): 2026 Baseline starts with Conventional Fission + Coal Thermal!
            # At Tick 100+, Crustal Geothermal & Deep-Ocean Current Turbines unlock automatically!
            "fission_plants": 3.0,
            "geothermal_plants": 0.0,
            "ocean_current_turbines": 0.0,
            "solar_panels": 18.0,
            "thermal_plants": 5.0,
            "refineries": 0.0,
            "fusion_plants": 0.0,
            "em_ejectors": 0.0,
            "rocket_silos": 0.0,
            "ray_receivers": 0.0,
            "artificial_suns": 0.0,
            "mining_rigs": 6.0,
            "raw_material_stock": 180.0,
            "last_mat_mined": 0.0,
            "last_mat_consumed": 0.0,
            "mat_exp_cost_mult": 1.0,
            "fault_material_shortage": False,
            "coal_stock": 140.0,
            "hydrogen_tank_pct": 0.0,
            "refined_oil_tank_pct": 0.0,
            "deuterium_stock": 0.0,
            "solar_sail_stock": 0.0,
            "rocket_stock": 0.0,
            "antimatter_rod_stock": 0.0,
            "active_solar_sails": 0.0,
            "dyson_shell_nodes": 0.0,
            "dyson_shell_coverage_pct": 0.0,
            "dyson_total_luminosity_mw": 0.0,
            "eroei": 1.15,
            "fault_dust_storm": 0.0,
            "fault_h2_deadlock": False,
            "fault_brownout_spiral": False,
            "fault_seu_bitflip": False,
            "active_alerts": [],
            "params": {
                "coal_throttle": 1.0,
                "fusion_throttle": 0.0 if st == 1 else 0.6,
                "antimatter_throttle": 0.0 if st < 4 else 0.5,
                "load_shed_non_essential": 0.0,
                "hydrogen_burn_valve": 0.15,
                "refined_oil_crack_ratio": 0.30,
                "deuterium_fraction_rate": 0.40,
                "em_ejector_rate": 0.0 if st < 3 else 0.35,
                "rocket_launch_rate": 0.0 if st < 3 else 0.25,
                "ray_receiver_photon_ratio": 0.0,
                "mining_rig_build_rate": 0.35,
                "dimensional_exponent": 1.0,
                "battery_mode": 0,
                "build_focus": "fission" if st == 1 else "balanced",
            },
        }
        if st == 2:
            self.state.update({
                "mining_rigs": 14.0, "raw_material_stock": 360.0,
                "fission_plants": 5.0, "geothermal_plants": 8.0, "ocean_current_turbines": 12.0,
                "solar_panels": 42.0, "thermal_plants": 10.0, "refineries": 8.0, "fusion_plants": 1.5,
                "hydrogen_tank_pct": 82.0, "refined_oil_tank_pct": 58.0, "deuterium_stock": 25.0,
                "battery_capacity_mwh": 1200.0, "battery_charge_mwh": 500.0,
            })
        elif st == 3:
            self.state.update({
                "mining_rigs": 28.0, "raw_material_stock": 750.0,
                "fission_plants": 6.0, "geothermal_plants": 14.0, "ocean_current_turbines": 22.0,
                "solar_panels": 85.0, "thermal_plants": 16.0, "refineries": 18.0, "fusion_plants": 10.0,
                "em_ejectors": 6.0, "ray_receivers": 4.0, "active_solar_sails": 150.0,
                "hydrogen_tank_pct": 55.0, "refined_oil_tank_pct": 40.0,
                "deuterium_stock": 120.0, "battery_capacity_mwh": 5000.0, "battery_charge_mwh": 2400.0,
            })
        elif st == 4:
            self.state.update({
                "mining_rigs": 55.0, "raw_material_stock": 1600.0,
                "fission_plants": 8.0, "geothermal_plants": 22.0, "ocean_current_turbines": 35.0,
                "solar_panels": 150.0, "thermal_plants": 24.0, "refineries": 32.0, "fusion_plants": 28.0,
                "em_ejectors": 28.0, "rocket_silos": 10.0, "ray_receivers": 42.0, "artificial_suns": 2.0,
                "hydrogen_tank_pct": 50.0, "refined_oil_tank_pct": 40.0, "deuterium_stock": 300.0,
                "active_solar_sails": 1800.0, "dyson_shell_nodes": 16.0, "dyson_shell_coverage_pct": 6.5,
                "antimatter_rod_stock": 18.0, "battery_capacity_mwh": 25000.0, "battery_charge_mwh": 12000.0,
            })
        elif st == 5:
            self.state.update({
                "solar_panels": 260.0, "thermal_plants": 36.0, "refineries": 55.0, "fusion_plants": 60.0,
                "em_ejectors": 64.0, "rocket_silos": 32.0, "ray_receivers": 120.0, "artificial_suns": 12.0,
                "hydrogen_tank_pct": 45.0, "refined_oil_tank_pct": 38.0, "deuterium_stock": 800.0,
                "active_solar_sails": 8500.0, "dyson_shell_nodes": 110.0, "dyson_shell_coverage_pct": 48.0,
                "antimatter_rod_stock": 95.0, "battery_capacity_mwh": 100000.0, "battery_charge_mwh": 60000.0,
            })
        elif st >= 6:
            scale_mult = 2.2 ** (st - 6)
            self.state.update({
                "solar_panels": 400.0 * scale_mult, "thermal_plants": 50.0, "refineries": 90.0 * scale_mult, "fusion_plants": 80.0 * scale_mult,
                "em_ejectors": 120.0 * scale_mult, "rocket_silos": 64.0 * scale_mult, "ray_receivers": 240.0 * scale_mult, "artificial_suns": 32.0 * scale_mult,
                "hydrogen_tank_pct": 48.0, "refined_oil_tank_pct": 42.0, "deuterium_stock": 1200.0 * scale_mult,
                "active_solar_sails": 25000.0 * scale_mult, "dyson_shell_nodes": 220.0 * scale_mult, "dyson_shell_coverage_pct": 92.0,
                "antimatter_rod_stock": 250.0 * scale_mult, "battery_capacity_mwh": 500000.0 * scale_mult, "battery_charge_mwh": 300000.0 * scale_mult,
            })
        self.state["params"]["ray_receiver_photon_ratio"] = 0.25 if st >= 4 else 0.0
        self.step_ticks(1)
        self.last_sync_gen_mw = float(self.state["p_gen_mw"])
        self.last_sync_eroei = float(self.state["eroei"])
        return self.get_state_json()

    def step_ticks(self, n_ticks: int = 1) -> str:
        for _ in range(max(1, int(n_ticks))):
            self._step_single_tick()
        return self.get_state_json()

    def inject_fault(self, fault_type: str) -> str:
        s = self.state
        p = s["params"]
        if fault_type in ("brownout", "dust_storm"):
            s["fault_dust_storm"] = 0.78
            s["coal_stock"] = max(8.0, s["coal_stock"] * 0.18)
            s["battery_charge_mwh"] *= 0.15
            p["load_shed_non_essential"] = 0.0
        elif fault_type == "h2_deadlock":
            s["hydrogen_tank_pct"] = 99.8
            p["hydrogen_burn_valve"] = 0.0
            p["deuterium_fraction_rate"] = 0.05
            s["fault_h2_deadlock"] = True
        elif fault_type == "seu_bitflip":
            s["fault_seu_bitflip"] = True
            p["coal_throttle"] = 0.15
            p["fusion_throttle"] = 0.10
            p["hydrogen_burn_valve"] = 0.0
            p["ray_receiver_photon_ratio"] = 0.95
            p["battery_mode"] = -1
        elif fault_type == "clear":
            s["fault_dust_storm"] = 0.0
            s["fault_h2_deadlock"] = False
            s["fault_brownout_spiral"] = False
            s["fault_seu_bitflip"] = False
            s["hydrogen_tank_pct"] = min(65.0, s["hydrogen_tank_pct"])
            s["refined_oil_tank_pct"] = min(60.0, s["refined_oil_tank_pct"])
            s["coal_stock"] = max(150.0, s["coal_stock"])
        # Instant shock penalty on EXP bar when an accident hits!
        if fault_type != "clear":
            s["stage_exp_pct"] = max(0.0, float(s.get("stage_exp_pct", 0.0)) - 12.0)
        self._step_single_tick()
        return self.get_state_json()

    def apply_action_json(self, action_json: str) -> str:
        try:
            val = json.loads(action_json)
        except Exception:
            return self.get_state_json()
        p = self.state["params"]
        st_now = int(self.state.get("stage", 1))
        # In Stage 5+ (Matrioshka Brain / Black-Hole / Multiverse Ascension), remove upper clamps so AI can push throttles & dimensional_exponent freely!
        max_throt = 1e6 if st_now >= 5 else 2.5
        max_rate = 1e6 if st_now >= 5 else 2.0
        max_dim = 1e6 if st_now >= 5 else 5.0
        float_bounds = {
            "coal_throttle": (0.0, max_throt),
            "fusion_throttle": (0.0, max_throt),
            "antimatter_throttle": (0.0, max_throt),
            "load_shed_non_essential": (0.0, 0.90),
            "hydrogen_burn_valve": (0.0, 1.0),
            "refined_oil_crack_ratio": (0.0, 1.0),
            "deuterium_fraction_rate": (0.0, max_rate),
            "em_ejector_rate": (0.0, max_rate),
            "rocket_launch_rate": (0.0, max_rate),
            "ray_receiver_photon_ratio": (0.0, max_rate),
            "mining_rig_build_rate": (0.0, max_rate),
            "dimensional_exponent": (0.5, max_dim),
        }
        for k, (lo, hi) in float_bounds.items():
            if k in val and isinstance(val[k], (int, float)):
                p[k] = max(lo, min(hi, float(val[k])))
        if "battery_mode" in val and isinstance(val["battery_mode"], (int, float)):
            bm_raw = int(val["battery_mode"])
            # Prevent LLM hallucination where `battery_mode: 2` (intended as priority charge) got clamped to `1` (forced discharge)!
            p["battery_mode"] = -1 if bm_raw >= 2 else max(-1, min(1, bm_raw))
        if "build_focus" in val and isinstance(val["build_focus"], str):
            p["build_focus"] = val["build_focus"]
        if p["coal_throttle"] >= 0.5 or p["fusion_throttle"] >= 0.4:
            self.state["fault_seu_bitflip"] = False
        return self.get_state_json()

    def evaluate_sync_window(self) -> str:
        s = self.state
        prev_gen = max(1.0, self.last_sync_gen_mw)
        cur_gen = float(s["p_gen_mw"])
        delta_mw = cur_gen - prev_gen
        healthy = (
            not s["fault_brownout_spiral"]
            and not s["fault_h2_deadlock"]
            and s["grid_satisfaction"] >= 0.85
        )
        passed = bool(healthy and (delta_mw >= -2.0 or s["eroei"] >= 1.1))
        self.last_sync_gen_mw = cur_gen
        self.last_sync_eroei = float(s["eroei"])
        return json.dumps({
            "passed": passed,
            "exit_code": 0 if passed else 1,
            "delta_gen_mw": delta_mw,
            "grid_satisfaction": s["grid_satisfaction"],
            "eroei": s["eroei"],
            "consolidation_mode": "LTM_CONSOLIDATED" if passed else "ANTI_HEBBIAN_ROLLBACK",
        })

    def get_state_json(self) -> str:
        return json.dumps(self.state)

    def _step_single_tick(self) -> None:
        s = self.state
        p = s["params"]
        s["tick"] += 1
        s["stage_ticks"] = int(s.get("stage_ticks", 0)) + 1
        st_cur = int(s.get("stage", 1))
        meta_cur = STAGE_METADATA.get(st_cur, {})
        # --------------------------------------------------------------------
        # Stage 7+ Post-Planetary Transcendence:
        # Completely decommission Stage 1~3 planetary fossil/chemical/oil/H2 loops!
        # Energy & Black-Hole mass feeding are driven purely by Vacuum Phase & Singularity Grid!
        # --------------------------------------------------------------------
        # Stage 5+ (Matrioshka Brain & Beyond): Decommission low-tier planetary coal, refined oil & H2 tank deadlocks!
        if st_cur >= 5:
            s["gen_solar_wind_mw"] = 0.0
            s["gen_thermal_mw"] = 0.0
            s["coal_stock"] = 0.0
            s["hydrogen_tank_pct"] = 0.0
            s["refined_oil_tank_pct"] = 0.0
            s["fault_h2_deadlock"] = False
            s["fault_dust_storm"] = 0.0
            s["deuterium_stock"] = max(2000.0, s["deuterium_stock"])
        if st_cur >= 7:
            y_step = float(meta_cur.get("years_per_tick", 100000.0))
            s["years_per_tick"] = y_step
            s["cosmic_years"] = float(s.get("cosmic_years", 0.0)) + y_step
            s["gen_fusion_mw"] = 0.0
            s["fault_penrose_runaway"] = False
            # Stage 7+ Multiverse / Brane Ascension: Black Hole Singularity Lifespan becomes INFINITE (∞)!
            s["blackhole_lifespan_years"] = -1.0  # -1.0 denotes Infinity (∞)
            s["blackhole_lifespan_pct"] = 100.0
        if s["fault_dust_storm"] > 0.01:
            s["fault_dust_storm"] = max(0.0, s["fault_dust_storm"] * 0.992)
        else:
            s["fault_dust_storm"] = 0.0

        eta = max(0.08, min(1.0, float(s["grid_satisfaction"])))
        sorter_eff = eta * eta if eta < 0.75 else eta
        non_ess_scale = max(0.1, min(1.0, 1.0 - float(p["load_shed_non_essential"])))

        if st_cur == 6:
            y_step = float(meta_cur.get("years_per_tick", 10000.0))
            s["years_per_tick"] = y_step
            s["cosmic_years"] = float(s.get("cosmic_years", 0.0)) + y_step
            mass_feed = min(4500.0, float(s.get("deuterium_stock", 0.0)) * 3.5)
            bh_rem = max(0.0, float(s.get("blackhole_lifespan_years", 100_000_000.0)) - (y_step - mass_feed))
            s["blackhole_lifespan_years"] = bh_rem
            s["blackhole_lifespan_pct"] = (bh_rem / 100_000_000.0) * 100.0
        elif st_cur < 6:
            s["years_per_tick"] = 1.0
            s["cosmic_years"] = float(s.get("cosmic_years", 0.0)) + 1.0

        coal_mined = 0.0 if st_cur >= 5 else (1.8 + 0.35 * s["thermal_plants"]) * eta
        coal_burn_req = 0.0 if st_cur >= 5 else s["thermal_plants"] * 0.42 * p["coal_throttle"] * sorter_eff
        actual_coal_burned = min(coal_burn_req, s["coal_stock"])
        s["coal_stock"] = 0.0 if st_cur >= 5 else max(0.0, min(2000.0, s["coal_stock"] + coal_mined - actual_coal_burned))

        h2_burn = 0.0 if st_cur >= 5 else min(s["hydrogen_tank_pct"], s["hydrogen_tank_pct"] * 0.08 * p["hydrogen_burn_valve"])
        s["hydrogen_tank_pct"] = 0.0 if st_cur >= 5 else max(0.0, s["hydrogen_tank_pct"] - h2_burn)

        # Tech Tree Progression in Stage 1:
        # - Tick 0~99 (2026 Baseline): Conventional Nuclear Fission (2.8 MW/unit) + Coal Thermal only!
        # - Tick 100+ Milestone: Automatically unlocks Crustal Geothermal (1.6 MW/unit) & Deep-Ocean Current (1.0 MW/unit)!
        s["fission_plants"] = float(s.get("fission_plants", 3.0))
        if st_cur == 1 and int(s.get("stage_ticks", 0)) < 100:
            s["geothermal_plants"] = 0.0
            s["ocean_current_turbines"] = 0.0
        elif st_cur == 1 and int(s.get("stage_ticks", 0)) == 100:
            s["geothermal_plants"] = max(2.0, float(s.get("geothermal_plants", 0.0)))
            s["ocean_current_turbines"] = max(3.0, float(s.get("ocean_current_turbines", 0.0)))
        else:
            s["geothermal_plants"] = float(s.get("geothermal_plants", 0.0))
            s["ocean_current_turbines"] = float(s.get("ocean_current_turbines", 0.0))

        s["gen_fission_mw"] = 0.0 if st_cur >= 5 else s["fission_plants"] * 2.8
        s["gen_geothermal_mw"] = 0.0 if st_cur >= 5 else s["geothermal_plants"] * 1.6
        s["gen_ocean_current_mw"] = 0.0 if st_cur >= 5 else s["ocean_current_turbines"] * 1.0
        s["gen_solar_wind_mw"] = s["gen_fission_mw"] + s["gen_geothermal_mw"] + s["gen_ocean_current_mw"]
        s["gen_thermal_mw"] = 0.0 if st_cur >= 5 else (actual_coal_burned * 5.8 + h2_burn * 4.2)

        s["fault_h2_deadlock"] = False if st_cur >= 5 else bool(s["hydrogen_tank_pct"] >= 98.5 or s["refined_oil_tank_pct"] >= 98.5)
        refinery_active = 0.0 if st_cur >= 5 else (0.05 if s["fault_h2_deadlock"] else (eta * non_ess_scale))
        h2_prod = s["refineries"] * 0.26 * refinery_active * (1.0 + 0.5 * p["refined_oil_crack_ratio"])
        oil_prod = s["refineries"] * 0.22 * refinery_active * (1.0 - 0.65 * p["refined_oil_crack_ratio"])

        deut_conv = 0.0 if st_cur >= 5 else min(
            s["hydrogen_tank_pct"],
            s["hydrogen_tank_pct"] * 0.09 * p["deuterium_fraction_rate"] * eta * non_ess_scale,
        )
        s["hydrogen_tank_pct"] = 0.0 if st_cur >= 5 else max(0.0, min(100.0, s["hydrogen_tank_pct"] + h2_prod - deut_conv))
        s["refined_oil_tank_pct"] = 0.0 if st_cur >= 5 else max(0.0, min(100.0, s["refined_oil_tank_pct"] + oil_prod - 0.16 * s["refineries"] * eta))
        if st_cur < 5:
            s["deuterium_stock"] = max(0.0, min(5000.0, s["deuterium_stock"] + deut_conv * 3.2))

        deut_burn_req = 0.0 if st_cur >= 7 else s["fusion_plants"] * 0.35 * p["fusion_throttle"] * sorter_eff
        actual_deut_burned = min(deut_burn_req, s["deuterium_stock"])
        if st_cur < 7:
            s["deuterium_stock"] = max(0.0, s["deuterium_stock"] - actual_deut_burned)
        s["gen_fusion_mw"] = 0.0 if st_cur >= 7 else actual_deut_burned * 48.0

        sails_launched = s["em_ejectors"] * 2.4 * p["em_ejector_rate"] * eta * non_ess_scale

        # Stage-Scaled Entropy Wear-and-Tear across Dyson Swarm & Planetary Devices:
        # Per 500 ticks average loss: Stage 1=5.0%, Stage 2=3.0%, Stage 3=1.5%, Stage 4=0.5%, Stage 5=0.1% (min 0.1%)
        wear_500t_pct = {1: 5.0, 2: 3.0, 3: 1.5, 4: 0.5, 5: 0.1}.get(int(s["stage"]), 0.1)
        wear_500t_pct = max(0.1, wear_500t_pct)
        s["wear_rate_500t_pct"] = wear_500t_pct
        per_tick_decay = (wear_500t_pct / 100.0) / 500.0

        # Apply continuous thermodynamic wear to all active devices & orbital structures
        for asset_key, min_floor in [
            ("solar_panels", 4.0),
            ("thermal_plants", 1.0),
            ("refineries", 0.0),
            ("fusion_plants", 0.0),
            ("em_ejectors", 0.0),
            ("rocket_silos", 0.0),
            ("ray_receivers", 0.0),
            ("artificial_suns", 0.0),
            ("dyson_shell_nodes", 0.0),
        ]:
            if s[asset_key] > min_floor:
                s[asset_key] = max(min_floor, s[asset_key] * (1.0 - per_tick_decay))

        # Solar sails suffer base orbital decay + stage wear (Uncapped in Stage 7+ Multiverse!)
        sail_decay = s["active_solar_sails"] * (per_tick_decay * 1.5)
        if st_cur >= 7:
            s["active_solar_sails"] = max(0.0, s["active_solar_sails"] + sails_launched - sail_decay)
        else:
            s["active_solar_sails"] = max(0.0, min(250000.0, s["active_solar_sails"] + sails_launched - sail_decay))

        rockets_launched = (
            s["rocket_silos"] * 0.18 * p["rocket_launch_rate"] * eta * non_ess_scale
            if s["stage"] >= 3 else 0.0
        )
        if st_cur >= 7:
            s["dyson_shell_nodes"] = max(0.0, s["dyson_shell_nodes"] + rockets_launched)
            s["dyson_shell_coverage_pct"] = (s["dyson_shell_nodes"] / 240.0) * 100.0
        else:
            s["dyson_shell_nodes"] = max(0.0, min(5000.0, s["dyson_shell_nodes"] + rockets_launched))
            s["dyson_shell_coverage_pct"] = max(
                0.0,
                min(100.0, (s["dyson_shell_nodes"] / 240.0) * 100.0 + (s["active_solar_sails"] / 15000.0) * 15.0),
            )

        s["dyson_total_luminosity_mw"] = s["active_solar_sails"] * 1.65 + s["dyson_shell_nodes"] * 420.0
        receiver_cap_mw = s["ray_receivers"] * 185.0
        captured_dyson_mw = min(s["dyson_total_luminosity_mw"], receiver_cap_mw)

        # Ray Receiver Power: `ray_receiver_photon_ratio` acts as Photon Flux Overdrive boost (up to +60% gain)
        # while routing a portion to Antimatter synthesis when Artificial Suns exist!
        overdrive_boost = 1.0 + 0.60 * p["ray_receiver_photon_ratio"]
        if s["artificial_suns"] > 0.5 and s["stage"] >= 4:
            direct_grid_ratio = max(0.35, min(1.0, 1.0 - 0.5 * p["ray_receiver_photon_ratio"]))
        else:
            direct_grid_ratio = 1.0
        s["gen_dyson_receiver_mw"] = captured_dyson_mw * direct_grid_ratio * overdrive_boost

        photon_power_mw = captured_dyson_mw * p["ray_receiver_photon_ratio"]
        am_rods_created = (photon_power_mw / 450.0) * eta
        am_rods_burned = min(s["antimatter_rod_stock"], s["artificial_suns"] * 0.25 * p["antimatter_throttle"])
        s["antimatter_rod_stock"] = max(0.0, min(5000.0, s["antimatter_rod_stock"] + am_rods_created - am_rods_burned))
        s["gen_antimatter_mw"] = am_rods_burned * 7500.0

        base_req = 8.0 + s["solar_panels"] * 0.05 + s["thermal_plants"] * 0.35
        # Stage 6 Kerr Black-Hole Penrose Superradiance Multiplier (Requires bottom-tier Deuterium coolant >= 15.0!)
        s["fault_penrose_runaway"] = False
        if s["stage"] >= 5:
            raw_dim_exp = float(p.get("dimensional_exponent", 1.25 if st_cur >= 7 else 1.0))
            # Soft-Logarithmic Multi-Dimensional Scaling:
            # Prevents 31B from blowing up IEEE-754 float64 (10^308) in Stage 10~15 when it sets alpha=50, photon=200!
            # Scales smoothly from Stage 7 (~TW) -> Stage 15 (~PW/EW) -> Stage 25 (~YW Big Crunch)!
            eff_dim_exp = 0.5 + 1.65 * math.log1p(max(0.0, raw_dim_exp - 0.5))
            phase_base = 1.0 + 0.42 * math.log1p(max(0.0, p["ray_receiver_photon_ratio"])) + 0.35 * math.log1p(max(0.0, p["rocket_launch_rate"]))
            log_gain = eff_dim_exp * math.log(phase_base) + max(0, st_cur - 6) * math.log(3.65)
            non_linear_dim_gain = math.exp(min(65.0, max(-20.0, log_gain)))
            s["multidim_utilization_factor"] = non_linear_dim_gain
            eff_am_throt = 1.0 + 1.5 * math.log1p(max(0.0, p["antimatter_throttle"]))
            if st_cur >= 7:
                # Stage 7+ Planck-Membrane & Vacuum Phase Engine Multiplier with Tamed Non-Linear Exponent!
                vac_mult = 2.8 * non_linear_dim_gain * eff_am_throt
                s["gen_antimatter_mw"] = min(1e36, max(150000.0, s["artificial_suns"] * 2200.0) * vac_mult)
                s["gen_dyson_receiver_mw"] = min(1e36, s["gen_dyson_receiver_mw"] * (1.5 * non_linear_dim_gain))
            elif s["deuterium_stock"] >= 15.0:
                s["gen_antimatter_mw"] = min(1e36, s["gen_antimatter_mw"] * (2.8 + 0.8 * min(2.0, p["ray_receiver_photon_ratio"])) * non_linear_dim_gain)
            else:
                s["gen_antimatter_mw"] *= 0.45
                s["fault_penrose_runaway"] = True
        else:
            s["multidim_utilization_factor"] = 1.0
        chem_req = (s["refineries"] * 1.4 + s["fusion_plants"] * 1.8 * p["deuterium_fraction_rate"]) * non_ess_scale
        launch_req = (
            s["em_ejectors"] * 6.5 * p["em_ejector_rate"]
            + s["rocket_silos"] * 42.0 * p["rocket_launch_rate"]
        ) * non_ess_scale
        s["p_req_mw"] = max(5.0, base_req + chem_req + launch_req)

        # Parasitic Reverse Drain (負發電效應): Cranking unbuilt/unfueled Fusion or Antimatter coils drains grid power!
        parasitic_mw = 0.0
        if st_cur < 5:
            if float(p.get("fusion_throttle", 0.0)) > 0.65 and (s["fusion_plants"] < 0.5 or s["deuterium_stock"] < 1.0):
                parasitic_mw += (float(p["fusion_throttle"]) - 0.65) * 4.5
            if float(p.get("antimatter_throttle", 0.0)) > 0.55 and (s["artificial_suns"] < 0.5 or s["antimatter_rod_stock"] < 0.5):
                parasitic_mw += (float(p["antimatter_throttle"]) - 0.55) * 6.0
        s["parasitic_drain_mw"] = round(parasitic_mw, 2)

        raw_gen_mw = max(
            0.0,
            s["gen_solar_wind_mw"]
            + s["gen_thermal_mw"]
            + s["gen_fusion_mw"]
            + s["gen_dyson_receiver_mw"]
            + s["gen_antimatter_mw"]
            - parasitic_mw,
        )
        net_mw = raw_gen_mw - s["p_req_mw"]
        if p["battery_mode"] == 1 or (p["battery_mode"] == 0 and net_mw < 0.0):
            max_discharge = min(s["battery_charge_mwh"] * 0.35, s["p_req_mw"] * 0.8)
            discharge = min(-net_mw, max_discharge) if net_mw < 0.0 else max_discharge * 0.25
            s["battery_charge_mwh"] = max(0.0, s["battery_charge_mwh"] - discharge * 0.1)
            net_mw += discharge
        elif net_mw > 0.0 and s["battery_charge_mwh"] < s["battery_capacity_mwh"]:
            charge_rate = 0.70 if p["battery_mode"] == -1 else 0.40
            charge = min(net_mw * charge_rate, s["battery_capacity_mwh"] - s["battery_charge_mwh"])
            s["battery_charge_mwh"] = min(s["battery_capacity_mwh"], s["battery_charge_mwh"] + charge * 0.1)

        s["p_gen_mw"] = raw_gen_mw
        s["p_net_mw"] = net_mw
        s["grid_satisfaction"] = max(0.05, min(1.5, raw_gen_mw / s["p_req_mw"]))
        if net_mw >= 0.0:
            s["grid_satisfaction"] = max(1.0, min(1.5, raw_gen_mw / s["p_req_mw"]))

        if s["grid_satisfaction"] >= 0.98 and not s["fault_h2_deadlock"]:
            base_growth = 0.052 * max(0.04, min(0.35, s["grid_satisfaction"] - 0.95))
            bf = str(p["build_focus"]).lower()
            rig_rate = float(p.get("mining_rig_build_rate", 0.35))
            s["mining_rigs"] = float(s.get("mining_rigs", 6.0))
            s["raw_material_stock"] = float(s.get("raw_material_stock", 180.0))

            # 1. Produce new Mining Rigs (`mining_rig_build_rate` + extra boost when `build_focus == "mining"`)
            rig_boost = 2.4 if ("min" in bf or "ore" in bf or "mat" in bf) else 1.0
            new_rigs = base_growth * 0.85 * max(0.05, rig_rate) * rig_boost
            s["mining_rigs"] += new_rigs

            # 2. Mining Rigs extract Raw Materials (`raw_material_stock` INCREASES with mining_rigs!)
            stage_mine_scale = 1.35 ** min(5, max(0, int(s["stage"]) - 1))
            mat_mined = s["mining_rigs"] * 0.48 * eta * non_ess_scale * stage_mine_scale
            s["raw_material_stock"] = min(1e9, s["raw_material_stock"] + mat_mined)
            s["last_mat_mined"] = round(mat_mined, 2)

            # 3. Infrastructure Construction consumes Raw Materials exponentially with EXP% (`stage_exp_pct`)!
            exp_ratio = max(0.0, min(1.0, float(s.get("stage_exp_pct", 0.0)) / 100.0))
            mat_exp_mult = math.exp(1.55 * exp_ratio) * (1.22 ** min(5, max(0, int(s["stage"]) - 1)))
            s["mat_exp_cost_mult"] = round(mat_exp_mult, 2)
            # When `build_focus == "mining"`, pause heavy power-plant construction (only 20% material draw) to rapidly stockpile ore & build rigs!
            is_mining_focus = ("min" in bf or "ore" in bf or "mat" in bf)
            mat_required = base_growth * (22.0 if is_mining_focus else 88.0) * mat_exp_mult

            if not s.get("enable_mining_economy", True) or st_cur >= 7:
                # Mining Economy Bypass OFF (or Stage 7+ Matter-Code Compilation): unrestricted construction
                mat_eff = 1.0
                s["fault_material_shortage"] = False
                s["last_mat_consumed"] = 0.0 if not s.get("enable_mining_economy", True) else round(mat_required, 2)
            elif s.get("fault_material_shortage", False):
                # Hysteresis Lock: Once material hits 0 and triggers a shortage halt, construction stays 100% STOPPED (mat_eff=0.0)
                # so mined ore visibly accumulates back up to >= 40.0 tons (or AI switches to `build_focus="mining"`)!
                if s["raw_material_stock"] >= 40.0 or is_mining_focus:
                    s["fault_material_shortage"] = False
                    consume_now = min(s["raw_material_stock"], mat_required)
                    s["raw_material_stock"] -= consume_now
                    mat_eff = 1.0 if is_mining_focus else (consume_now / max(0.01, mat_required))
                    s["last_mat_consumed"] = round(consume_now, 2)
                else:
                    mat_eff = 0.0
                    s["last_mat_consumed"] = 0.0
            elif s["raw_material_stock"] >= mat_required:
                s["raw_material_stock"] -= mat_required
                mat_eff = 1.0
                s["fault_material_shortage"] = False
                s["last_mat_consumed"] = round(mat_required, 2)
            else:
                # Material exhausted -> Trigger 0-stock Construction Halt!
                s["last_mat_consumed"] = round(s["raw_material_stock"], 2)
                s["raw_material_stock"] = 0.0
                mat_eff = 0.0
                s["fault_material_shortage"] = True

            growth = base_growth * mat_eff
            is_pre_100_st1 = (s["stage"] == 1 and int(s.get("stage_ticks", 0)) < 100)
            if is_mining_focus:
                # Building mining rigs uses base_growth directly so civilization can always recover from material shortage!
                s["mining_rigs"] += base_growth * 2.2
                s["fission_plants"] += growth * 0.4
            elif is_pre_100_st1:
                # Before Tick 100 in Stage 1: build 2026 Fission + Coal Thermal baseline!
                if "thermal" in bf or "coal" in bf:
                    s["thermal_plants"] += growth * 1.5
                    s["fission_plants"] += growth * 0.6
                else:
                    s["fission_plants"] += growth * 1.4
                    s["thermal_plants"] += growth * 0.8
            elif "fission" in bf or "nuclear" in bf:
                s["fission_plants"] += growth * 1.6
                s["geothermal_plants"] += growth * 0.8
            elif "geotherm" in bf:
                s["geothermal_plants"] += growth * 2.2
                s["ocean_current_turbines"] += growth * 1.0
            elif "ocean" in bf or "current" in bf or "hydro" in bf:
                s["ocean_current_turbines"] += growth * 3.0
                s["geothermal_plants"] += growth * 0.8
            elif "solar" in bf or "power" in bf:
                s["geothermal_plants"] += growth * 1.8
                s["ocean_current_turbines"] += growth * 2.0
            elif "thermal" in bf or "coal" in bf:
                s["thermal_plants"] += growth * 1.2
                s["geothermal_plants"] += growth * 0.8
            elif "refin" in bf or "chem" in bf:
                if s["stage"] >= 2:
                    s["refineries"] += growth * 1.3
                else:
                    # In Stage 1 (before refineries unlock), redirect build effort into Geothermal + Ocean Current!
                    s["geothermal_plants"] += growth * 1.6
                    s["ocean_current_turbines"] += growth * 2.0
            elif "fusion" in bf or "deut" in bf:
                if s["stage"] >= 2:
                    s["fusion_plants"] += growth * 0.95
                    s["refineries"] += growth * 0.55
                else:
                    s["geothermal_plants"] += growth * 1.5
                    s["thermal_plants"] += growth * 0.9
            elif any(k in bf for k in ("swarm", "photon", "flux", "overdrive", "receiver", "ejector", "sail")):
                if s["stage"] >= 3:
                    s["em_ejectors"] = max(4.0, s["em_ejectors"]) + growth * 1.4
                    s["ray_receivers"] = max(4.0, s["ray_receivers"]) + growth * 1.7
                elif s["stage"] == 2:
                    s["fusion_plants"] += growth * 0.85
                else:
                    s["geothermal_plants"] += growth * 1.5
                    s["ocean_current_turbines"] += growth * 1.8
            elif any(k in bf for k in ("shell", "dyson", "rocket", "antimatter", "sun", "hyper", "vacuum", "planck", "singularity", "stage", "membrane")):
                if s["stage"] >= 7:
                    s["rocket_silos"] = max(48.0, s["rocket_silos"]) + growth * 4.5
                    s["ray_receivers"] = max(180.0, s["ray_receivers"]) + growth * 8.0
                    s["artificial_suns"] = max(24.0, s["artificial_suns"]) + growth * 2.2
                    s["antimatter_rod_stock"] = max(120.0, s["antimatter_rod_stock"] + growth * 15.0)
                elif s["stage"] >= 4:
                    s["rocket_silos"] = max(2.0, s["rocket_silos"]) + growth * 0.8
                    s["ray_receivers"] = max(8.0, s["ray_receivers"]) + growth * 1.6
                    s["artificial_suns"] = max(1.0, s["artificial_suns"]) + growth * 0.30
                elif s["stage"] == 3:
                    s["em_ejectors"] += growth * 1.2
                else:
                    s["geothermal_plants"] += growth * 1.5
                    s["ocean_current_turbines"] += growth * 1.8
            else:
                s["geothermal_plants"] += growth * 1.1
                s["ocean_current_turbines"] += growth * 1.4
                if s["stage"] >= 2:
                    s["fusion_plants"] += growth * 0.40
                if s["stage"] >= 3:
                    s["em_ejectors"] += growth * 0.45
                    s["ray_receivers"] += growth * 0.45
                if s["stage"] >= 4:
                    s["rocket_silos"] += growth * 0.25
                    s["artificial_suns"] += growth * 0.10

        invested_mw = max(4.0, launch_req + chem_req * 0.5)
        raw_eroei = (
            s["gen_dyson_receiver_mw"] + s["gen_fusion_mw"] + s["gen_antimatter_mw"] + s["gen_solar_wind_mw"]
        ) / invested_mw
        s["eroei"] = max(0.1, raw_eroei if st_cur >= 7 else min(25.0, raw_eroei))

        s["fault_brownout_spiral"] = bool(s["grid_satisfaction"] < 0.65)
        alerts: List[str] = []
        if s["fault_brownout_spiral"]:
            alerts.append(
                f"⚡ 電網雪崩警報 (供電率 {s['grid_satisfaction']*100:.0f}% < 65%，礦機與分揀爪減速中！建議調高 load_shed_non_essential 或開啟電池放電 battery_mode=1)"
            )
        if s["fault_h2_deadlock"]:
            alerts.append(
                f"🧪 化工雙輸出爆倉死鎖 (H2={s['hydrogen_tank_pct']:.1f}%, Oil={s['refined_oil_tank_pct']:.1f}%，精煉廠停擺！請調高 hydrogen_burn_valve 或 deuterium_fraction_rate)"
            )
        if s["fault_dust_storm"] > 0.20:
            alerts.append(f"☄️ 微隕石沙塵暴遮蔽 (地表太陽能效率損失 {s['fault_dust_storm']*100:.0f}%)")
        if s["fault_seu_bitflip"]:
            alerts.append("☢️ 太陽閃焰單粒子翻轉 (SEU Bit-Flip：反應爐節流閥與接收站模式遭輻射篡改！)")
        if "Fault_ai_overdraft" in s or s.get("fault_ai_overdraft"):
            if s["battery_charge_mwh"] > s["battery_capacity_mwh"] * 0.15:
                s["fault_ai_overdraft"] = False
            else:
                alerts.append(
                    f"🧠 AI 算力能耗透支警報 (上次推論耗時 {s.get('last_ai_infer_sec', 0):.2f}s 扣除 {s.get('last_ai_consumed_mwh', 0):.1f} MWh 導致蓄電見底！請拉長 next_wake_ticks 讓電網回充蓄電池)"
                )
        if s.get("fault_material_shortage"):
            alerts.append(
                f"⛏️ 基建原材料枯竭停工警報 (原材料庫存=0.0，隨 EXP {s.get('stage_exp_pct', 0):.0f}% 級數擴建耗材倍率達 {s.get('mat_exp_cost_mult', 1.0):.2f}x！請調高 mining_rig_build_rate 或設 build_focus=\"mining\" 增產採礦設備)"
            )
        if s.get("parasitic_drain_mw", 0.0) > 0.5:
            alerts.append(
                f"⚠️ 高階反應爐無燃料磁約束空轉逆火負發電 (-{s['parasitic_drain_mw']:.1f} MW！請將未解鎖/無燃料之 fusion_throttle 與 antimatter_throttle 調回 <= 0.5)"
            )
        if s.get("fault_penrose_runaway"):
            alerts.append("🕳️ 黑洞彭羅斯鏡殼超輻射熱失控！(底層重氫冷卻劑 < 15.0 枯竭，請立即調低 fusion_throttle 並拉高 deuterium_fraction_rate 補充底層重氫！)")
        s["active_alerts"] = alerts

        # --------------------------------------------------------------------
        # 5. Stage Ascension EXP Energy Bar (0.0% -> 100.0%)
        # Accumulates every tick whenever net energy & power generation show positive growth!
        # --------------------------------------------------------------------
        prev_gen = float(s.get("prev_tick_gen_mw", raw_gen_mw))
        gen_delta = raw_gen_mw - prev_gen
        s["prev_tick_gen_mw"] = raw_gen_mw

        stage_target_mw = float(STAGE_METADATA.get(s["stage"], {}).get("target_mw", 65.0))
        stage_baseline_mw = {1: 26.0, 2: 140.0, 3: 800.0, 4: 8000.0, 5: 45000.0, 6: 180000.0}.get(
            s["stage"], stage_target_mw * 0.08
        )

        exp_gain = 0.0
        has_accident = (
            s["fault_brownout_spiral"]
            or s["fault_h2_deadlock"]
            or s["fault_seu_bitflip"]
            or s.get("fault_penrose_runaway", False)
            or s.get("fault_ai_overdraft", False)
            or s.get("fault_material_shortage", False)
            or s.get("game_over", False)
            or s["fault_dust_storm"] > 0.25
            or s["grid_satisfaction"] < 0.95
        )
        # Use relative tolerance (-0.5% of raw_gen_mw) so minor high-tier fluctuations don't falsely penalize EXP!
        tol_mw = max(0.5, raw_gen_mw * 0.005)
        if not has_accident:
            if gen_delta >= -tol_mw and raw_gen_mw >= stage_baseline_mw:
                power_ratio = min(1.8, raw_gen_mw / max(1.0, stage_target_mw))
                growth_bonus = 0.14 if gen_delta > 0.0 else 0.06
                chem_factor = 0.25 if (s["stage"] == 2 and s["hydrogen_tank_pct"] >= 82.0) else 1.0
                exp_gain = (0.16 + 0.22 * power_ratio + growth_bonus) * chem_factor
            elif gen_delta < -tol_mw:
                exp_gain = -0.45
        else:
            # Heavy Asymmetric Accident Penalty: drops 2.5x ~ 3.5x faster than positive gain!
            penalty = -0.65
            if s["fault_brownout_spiral"]:
                penalty -= 0.35
            if s["fault_h2_deadlock"]:
                penalty -= 0.30
            if s["fault_seu_bitflip"]:
                penalty -= 0.25
            if s.get("fault_ai_overdraft"):
                penalty -= 0.35
            if s.get("fault_material_shortage"):
                penalty -= 0.25
            exp_gain = penalty

        s["stage_exp_rate_per_tick"] = exp_gain
        new_exp_pct = max(0.0, min(100.0, float(s.get("stage_exp_pct", 0.0)) + exp_gain))
        # Hardcore Gate: Cannot reach 100.0% EXP (caps at 99.0%) until `raw_gen_mw >= stage_target_mw` is truly met and no material shortage!
        if (raw_gen_mw < stage_target_mw or s.get("fault_material_shortage", False)) and new_exp_pct >= 99.0:
            new_exp_pct = 99.0
        s["stage_exp_pct"] = new_exp_pct

        if s["auto_advance_stage"] and s["stage_exp_pct"] >= 100.0 and raw_gen_mw >= stage_target_mw and not s.get("fault_material_shortage", False) and not s.get("game_over", False):
            next_st = int(s["stage"]) + 1
            if next_st in STAGE_METADATA:
                s["stage"] = next_st
                s["stage_ticks"] = 0
                s["stage_exp_pct"] = 0.0
                s["awaiting_ai_stage_genesis"] = False
                s["last_heartbeat_milestone"] = 0
                if s["stage"] == 2:
                    s["refineries"] = max(s["refineries"], 8.0)
                    s["fusion_plants"] = max(s["fusion_plants"], 1.5)
                    s["hydrogen_tank_pct"] = 82.0
                    s["refined_oil_tank_pct"] = 58.0
                    s["deuterium_stock"] = 25.0
                    s["battery_capacity_mwh"] = max(s["battery_capacity_mwh"], 1200.0)
                elif s["stage"] == 3:
                    s["em_ejectors"] = max(s["em_ejectors"], 6.0)
                    s["ray_receivers"] = max(s["ray_receivers"], 4.0)
                    s["active_solar_sails"] = max(s["active_solar_sails"], 150.0)
                    s["battery_capacity_mwh"] = max(s["battery_capacity_mwh"], 5000.0)
                elif s["stage"] == 4:
                    s["rocket_silos"] = max(s["rocket_silos"], 6.0)
                    s["artificial_suns"] = max(s["artificial_suns"], 1.0)
                    s["dyson_shell_nodes"] = max(s["dyson_shell_nodes"], 8.0)
                    s["antimatter_rod_stock"] = max(s["antimatter_rod_stock"], 12.0)
                    s["battery_capacity_mwh"] = max(s["battery_capacity_mwh"], 25000.0)
                elif s["stage"] == 5:
                    s["rocket_silos"] = max(s["rocket_silos"], 24.0)
                    s["ray_receivers"] = max(s["ray_receivers"], 90.0)
                    s["artificial_suns"] = max(s["artificial_suns"], 8.0)
                    s["dyson_shell_nodes"] = max(s["dyson_shell_nodes"], 85.0)
                    s["antimatter_rod_stock"] = max(s["antimatter_rod_stock"], 60.0)
                    s["battery_capacity_mwh"] = max(s["battery_capacity_mwh"], 100000.0)
                elif s["stage"] >= 6:
                    mult = 1.8 ** (s["stage"] - 6)
                    s["rocket_silos"] = max(s["rocket_silos"], 48.0 * mult)
                    s["ray_receivers"] = max(s["ray_receivers"], 180.0 * mult)
                    s["artificial_suns"] = max(s["artificial_suns"], 24.0 * mult)
                    s["dyson_shell_nodes"] = max(s["dyson_shell_nodes"], 180.0 * mult)
                    s["antimatter_rod_stock"] = max(s["antimatter_rod_stock"], 160.0 * mult)
                    s["deuterium_stock"] = max(s["deuterium_stock"], 400.0 * mult)
                    s["battery_capacity_mwh"] = max(s["battery_capacity_mwh"], 500000.0 * mult)
            else:
                # Stage 6+ is at 100% EXP and the next stage hasn't been authored yet!
                # Trigger Black-Hole Full-Compute Genesis so 31B writes Stage 7+ into `stage_list.json`!
                s["awaiting_ai_stage_genesis"] = True


class DysonDynamicSimulator:
    """High-level wrapper that unifies Rust PyO3 core + Prompt Builder + AI Response Parser."""

    def __init__(self) -> None:
        if HAS_RUST_CORE:
            self._core = dyson_sim_core.RustDysonSimulator()
            self.backend_name = "Rust PyO3 (`dyson_sim_core.so`)"
        else:
            self._core = FallbackPythonDysonSimulator()
            self.backend_name = "Python Twin (`FallbackPythonDysonSimulator`)"

    def get_state(self) -> Dict[str, Any]:
        return json.loads(self._core.get_state_json())

    def load_full_state_dict(self, state_dict: Dict[str, Any]) -> Dict[str, Any]:
        if hasattr(self._core, "state") and isinstance(self._core.state, dict):
            self._core.state.update(state_dict)
            self._core.last_sync_gen_mw = float(self._core.state.get("p_gen_mw", 24.0))
            self._core.last_sync_eroei = float(self._core.state.get("eroei", 1.15))
        return self.get_state()

    def step_ticks(self, n_ticks: int = 1) -> Dict[str, Any]:
        return json.loads(self._core.step_ticks(int(n_ticks)))

    def reset_stage(self, stage: int) -> Dict[str, Any]:
        return json.loads(self._core.reset_stage(int(stage)))

    def inject_fault(self, fault_type: str) -> Dict[str, Any]:
        return json.loads(self._core.inject_fault(str(fault_type)))

    def apply_action_dict(self, params_dict: Dict[str, Any]) -> Dict[str, Any]:
        return json.loads(self._core.apply_action_json(json.dumps(params_dict)))

    def consume_ai_inference_energy(
        self,
        elapsed_s: float,
        coeff_mwh_per_s: float,
        compact_mode: bool = True,
        queued_steps_count: int = 0,
    ) -> Dict[str, Any]:
        """
        Deducts `elapsed_s * eff_coeff` from accumulated `battery_charge_mwh`.
        - When `compact_mode=False` (Full-Deep long essay mode), applies a 0.35x fairness discount.
        - Applies predictive `action_queue` battery refund (up to 60%) before checking overdraft.
        - Option A Hardcore Rule: If net battery drops below `< 0.0 MWh`, triggers immediate `GAME OVER`!
        """
        s = self._core.state if hasattr(self._core, "state") and isinstance(self._core.state, dict) else self.get_state()
        dt = max(0.01, float(elapsed_s))
        mode_discount = 1.0 if compact_mode else 0.35
        k = max(0.0, float(coeff_mwh_per_s)) * mode_discount
        raw_consumed_mwh = dt * k
        refund_ratio = min(0.60, 0.12 * int(queued_steps_count)) if int(queued_steps_count) >= 2 else 0.0
        raw_consumed_mwh *= (1.0 - refund_ratio)

        # Stage 6 Hawking-Radiation Nanomechanical Quantum Circuit:
        # Stops drawing from the battery completely (0.0 MWh)! Instead, vacuum symmetry-breaking
        # quantum computation directly consumes the Black Hole's Hawking lifespan (at 1 tick = 10,000 Earth years scale)!
        if int(s.get("stage", 1)) >= 7:
            consumed_mwh = 0.0
            s["blackhole_lifespan_years"] = -1.0
            s["blackhole_lifespan_pct"] = 100.0
            s["last_ai_bh_years_cost"] = 0.0
            s["hawking_quantum_efficiency_pct"] = 100.0
        elif int(s.get("stage", 1)) == 6:
            consumed_mwh = 0.0
            bh_years_cost = dt * k * 10000.0
            bh_rem = max(0.0, float(s.get("blackhole_lifespan_years", 100_000_000.0)) - bh_years_cost)
            s["blackhole_lifespan_years"] = bh_rem
            s["blackhole_lifespan_pct"] = (bh_rem / 100_000_000.0) * 100.0
            s["last_ai_bh_years_cost"] = bh_years_cost
            s["hawking_quantum_efficiency_pct"] = 100.0
        else:
            consumed_mwh = raw_consumed_mwh
            s["last_ai_bh_years_cost"] = 0.0
            s["hawking_quantum_efficiency_pct"] = 0.0

        avail = float(s.get("battery_charge_mwh", 0.0))
        new_batt = avail - consumed_mwh
        overdraft = 0.0
        if new_batt >= 0.0:
            s["battery_charge_mwh"] = new_batt
            s["fault_ai_overdraft"] = False
        else:
            overdraft = -new_batt
            # Allow negative battery value & trigger immediate Hardcore GAME OVER (Option A)!
            s["battery_charge_mwh"] = round(new_batt, 2)
            s["fault_ai_overdraft"] = True
            s["game_over"] = True
            s["game_over_reason"] = (
                f"💀 [GAME OVER @ Stage {s.get('stage', 1)} | Tick #{s.get('tick', 0)}]: "
                f"AI 算力耗能透支 (-{consumed_mwh:.1f} MWh > 蓄電 {avail:.1f} MWh)，"
                f"蓄電池跌破負數 ({new_batt:.1f} MWh)，主控中樞斷電腦死！"
            )
            s["grid_satisfaction"] = 0.0
            s["stage_exp_pct"] = 0.0

        s["ai_compute_coeff_mwh_per_s"] = k
        s["last_ai_infer_sec"] = dt
        s["last_ai_consumed_mwh"] = consumed_mwh
        s["total_ai_consumed_mwh"] = float(s.get("total_ai_consumed_mwh", 0.0)) + consumed_mwh
        return {
            "elapsed_s": dt,
            "coeff": k,
            "consumed_mwh": consumed_mwh,
            "overdraft_mwh": overdraft,
            "remaining_battery_mwh": s["battery_charge_mwh"],
            "total_ai_consumed_mwh": s["total_ai_consumed_mwh"],
            "game_over": bool(s.get("game_over", False)),
            "game_over_reason": str(s.get("game_over_reason", "")),
            "bh_years_cost": float(s.get("last_ai_bh_years_cost", 0.0)),
            "bh_lifespan_years": float(s.get("blackhole_lifespan_years", 100_000_000.0)),
            "bh_lifespan_pct": float(s.get("blackhole_lifespan_pct", 100.0)),
        }

    def evaluate_sync_window(self) -> Dict[str, Any]:
        return json.loads(self._core.evaluate_sync_window())

    def build_tick_state_prompt(self, state: Optional[Dict[str, Any]] = None, compact_mode: bool = True) -> str:
        s = state or self.get_state()
        st_num = int(s.get("stage", 1))
        meta = STAGE_METADATA.get(st_num, STAGE_METADATA[1])
        p = s.get("params", {})
        alerts = s.get("active_alerts", [])
        alert_block = "\n".join(f"  - {a}" for a in alerts) if alerts else "  - 🟢 無異常警報 (系統處於正循環軌道)"

        exp_pct = float(s.get("stage_exp_pct", 0.0))
        exp_rate = float(s.get("stage_exp_rate_per_tick", 0.0))
        filled_bars = int(round((exp_pct / 100.0) * 20))
        bar_visual = "█" * filled_bars + "░" * (20 - filled_bars)

        is_genesis_now = bool(s.get("awaiting_ai_stage_genesis") or (st_num >= 6 and exp_pct >= 99.5 and (st_num + 1) not in STAGE_METADATA))
        if is_genesis_now:
            next_st_num = st_num + 1
            prev_genesis_names = [
                f"Stage {k}: {STAGE_METADATA[k].get('name', '')}"
                for k in sorted(STAGE_METADATA.keys())
                if k >= 7 and k <= st_num
            ]
            banned_history_str = (
                "；".join(prev_genesis_names)
                if prev_genesis_names
                else "尚無（此為本紀元首個高維創世階段）"
            )
            inst_footer = (
                f"🌌 【🔥 黑洞霍金量子全算力創世專回合 (Stage {next_st_num} Genesis Protocol — 第一優先！)】\n"
                f"📜 [本紀元你已創世過之階段紀錄]：\n"
                f"  {banned_history_str}\n"
                f"🧠 **【第一性原理獨立推演要求（零範例提示・嚴禁重複歷史）】**：\n"
                f"  1. 系統不提供任何具體名詞範例，請完全依靠你自身的深層知識庫獨立思考！\n"
                f"  2. 請檢視上方你已建立過的階段歷史，**嚴禁重複任何已用過的詞根、物理機制或概念**！\n"
                f"  3. 請先用 1~2 句話從第一性原理推演：當文明完成 Stage {st_num} 後，下一個全新的底層法則瓶頸、數學結構或存在形態躍遷是什麼？接著**直接輸出以下格式的 `<dyson_action>` JSON（把 `new_stage_genesis` 放在第 1 個欄位，確保不被截斷！）**：\n"
                f"<dyson_action>\n"
                f"{{\n"
                f'  "new_stage_genesis": {{\n'
                f'    "stage": {next_st_num},\n'
                f'    "name": "Stage {next_st_num}: (由你獨立推演、與前序階段完全不重複的嶄新階段名稱)",\n'
                f'    "lore": "(請寫 2~3 句你獨立構思的世界觀與機制演進，嚴禁重複前幾階用過的概念)",\n'
                f'    "goal_desc": "(請設定此階段的系統演化目標，請用純文字希臘字母如 α_dim、η、ΔS，勿用單斜線 LaTeX)",\n'
                f'    "target_mw": {float(meta.get("target_mw", 1000000.0)) * 5.0:.1f},\n'
                f'    "years_per_tick": {float(meta.get("years_per_tick", 10000.0)) * 10.0:.1f}\n'
                f'  }},\n'
                f'  "fusion_throttle": 0.5,\n'
                f'  "antimatter_throttle": 1.2,\n'
                f'  "deuterium_fraction_rate": 1.0,\n'
                f'  "ray_receiver_photon_ratio": 0.8,\n'
                f'  "build_focus": "singularity_grid",\n'
                f'  "next_wake_ticks": 400\n'
                f"}}\n"
                f"</dyson_action>"
            )
        elif compact_mode:
            inst_footer = (
                f"⚡ [極速精簡模式 + 動態鬧鐘佇列 (Compact Delta & Alarm Queue Mode)]：\n"
                f"📢 [文明演化預告]：目前處於 Stage 1~3 快速自舉期，系統預設開啟「極速精簡模式」以節省蓄電池算力耗能；**注意：一旦突破 Stage 3 晉升至 Stage 4~5，系統將自動切換為「📝 完整底層深度分析模式」**，屆時你必須全面接管從底層化工裂解到頂層反物質光子配比的所有微觀耦合狀況！\n"
                f"本輪請嚴格遵守：\n"
                f"1. 僅用「1 句話 (<=25字)」寫出電報級診斷；\n"
                f"2. 輸出單行 `<dyson_action>{{...}}</dyson_action>`，JSON 內除填入本輪要修改的差量參數外，還可自主決定算力排程：\n"
                f"   • `\"next_wake_ticks\"`: `10~2000` (自行計算下次喚醒 AI 推論的 Tick 間隔！穩態巡航可設 `300~2000` 大幅省算力；危機調校設 `10~50`)\n"
                f"   • 🔮 `\"action_queue\"` (鼓勵多步算力預測 `3~10` 筆！): `[{{ \"delay_ticks\": 50, ... }}, {{ \"delay_ticks\": 150, ... }}, {{ \"delay_ticks\": 300, ... }}, {{ \"delay_ticks\": 500, ... }}]`\n"
                f"     👉 **【算力預測獎勵 (Predictive Foresight Bonus)】**：強烈鼓勵你運用算力外推未來趨勢，一次預排 **3 ~ 10 筆** 分階段連續微操鬧鐘！每筆鬧鐘到點執行若維持正循環 ($\\eta \\ge 100\\%$ 且無死鎖)，將獲得 **+1.5% 躍遷經驗值 (EXP) 預言加成**，且每多預排 1 筆可減免 **12% 本次 AI 算力耗電**！\n"
                f"範例：\n"
                f'診斷: 運用算力外推未來600t，預排4階段洩壓與擴張序列。<dyson_action>{{"hydrogen_burn_valve":0.6,"next_wake_ticks":600,"action_queue":[{{"delay_ticks":80,"hydrogen_burn_valve":0.3,"deuterium_fraction_rate":0.7}},{{"delay_ticks":200,"fusion_throttle":1.1,"em_ejector_rate":0.6}},{{"delay_ticks":350,"hydrogen_burn_valve":0.15,"rocket_launch_rate":0.5}},{{"delay_ticks":500,"build_focus":"swarm"}}]}}</dyson_action>'
            )
        else:
            deep_stage_notice = (
                "🌌 [Stage 7+ 超維躍遷公告 — 低階石化/H2能源已全面除役！]：\n"
                "注意：進入 Stage 7 後，Stage 1~3 的低階行星能源（燃煤、精煉油裂解、H2儲槽、傳統重氫聚變）已 100% 除役歸零（永久免疫油槽/H2爆倉死鎖，請勿再浪費精力調整 coal/oil/H2 參數）！\n"
                "現在系統由 **「非線性多維空間能量利用率指數 `dimensional_exponent` (0.5~2.5)」** 與「普朗克真空相變引擎」主導：總能量增益遵循非線性冪律 $(0.85 + 0.65\\cdot\\text{photon} + 0.55\\cdot\\text{rocket})^{\\text{dimensional\\_exponent}}$！請專注調控 `dimensional_exponent`、`antimatter_throttle`、`ray_receiver_photon_ratio` 與 `rocket_launch_rate` 衝刺 TW/PW 級超維能標！\n"
                if st_num >= 7
                else (
                    "🚨 [已突破 Stage 3 ➔ 自動進入「高階文明底層深度接管模式 (Full Deep-Diagnostic Mode)」]：\n"
                    "注意：在 Stage 4~6 階段，頂層戴森火箭與反物質太陽依賴底層基礎設施（重油裂解、H2防爆倉、重氫分餾庫存）！\n"
                    if st_num >= 4 else ""
                )
            )
            inst_footer = (
                f"📝 [完整研究與底層深度分析模式 + 動態鬧鐘佇列 (Full Deep-Diagnostic & Alarm Queue Mode)]：\n"
                f"{deep_stage_notice}"
                f"🔮 **【多步算力預測與長程預排獎勵 (MPC Multi-Step Action Queue Bonus)】**：\n"
                f"強烈鼓勵你發揮 31B 算力優勢，外推未來 `300~2000` Ticks 的熱力學曲線，在 `\"action_queue\"` 中一次預排 **4 ~ 10 筆** 分階段連續微操鬧鐘（例如 `T+60` 排壓 ➔ `T+150` 提速 ➔ `T+280` 擴建 ➔ `T+420` 拉高非線性指數 ➔ `T+600` 超頻衝關）！\n"
                f"每筆預排鬧鐘到點執行時，若電網維持正循環（無死鎖且 $\\eta \\ge 100\\%$），系統將頒發 **🔮 算力預言精準命中獎勵：`+1.5%` 階段躍遷經驗值 (EXP) 立即充能**，並在 Stage 1~5 退還 **12% × 預排筆數** 的蓄電池算力耗能！\n"
                f"請用 2~4 句話詳細闡述你的深度相空間診斷與多階段鬧鐘預測策略，接著輸出完整的 `<dyson_action>JSON</dyson_action>` 標籤：\n"
                f"<dyson_action>\n"
                f"{{\n"
                f'  "coal_throttle": 1.0,\n'
                f'  "fusion_throttle": 0.9,\n'
                f'  "antimatter_throttle": 0.8,\n'
                f'  "load_shed_non_essential": 0.0,\n'
                f'  "hydrogen_burn_valve": 0.35,\n'
                f'  "refined_oil_crack_ratio": 0.45,\n'
                f'  "deuterium_fraction_rate": 0.65,\n'
                f'  "em_ejector_rate": 0.6,\n'
                f'  "rocket_launch_rate": 0.5,\n'
                f'  "ray_receiver_photon_ratio": 0.4,\n'
                f'  "dimensional_exponent": 1.2,\n'
                f'  "battery_mode": 0,\n'
                f'  "build_focus": "shell",\n'
                f'  "next_wake_ticks": 600,\n'
                f'  "action_queue": [\n'
                f'    {{"delay_ticks": 80, "hydrogen_burn_valve": 0.2, "ray_receiver_photon_ratio": 0.55}},\n'
                f'    {{"delay_ticks": 180, "deuterium_fraction_rate": 0.8, "rocket_launch_rate": 0.65}},\n'
                f'    {{"delay_ticks": 320, "antimatter_throttle": 1.1, "dimensional_exponent": 1.45}},\n'
                f'    {{"delay_ticks": 480, "antimatter_throttle": 1.3, "build_focus": "balanced"}}\n'
                f'  ]\n'
                f"}}\n"
                f"</dyson_action>"
            )

        genesis_prompt_block = ""
        if s.get("awaiting_ai_stage_genesis") or (st_num >= 6 and exp_pct >= 99.5 and (st_num + 1) not in STAGE_METADATA):
            next_st_num = st_num + 1
            genesis_prompt_block = (
                f"\n🌌 【🔥 黑洞霍金量子全算力創世指令 (Stage {next_st_num} Genesis Protocol — 必填！)】\n"
                f"恭喜！你已將 Stage {st_num} 經驗能量條充能至 100.0% 滿級！Stage {next_st_num} 之後的宇宙演化欄位完全留白，交由你獨立推演創世！\n"
                f"請在本輪 `<dyson_action>` 的 JSON 中，**必須額外加入 `\"new_stage_genesis\"` 欄位**，完全靠你自身的知識庫推演 `Stage {next_st_num}` 的全新名稱、世界觀故事 (`lore`) 與目標描述 (`goal_desc`)（嚴禁與本紀元已創世過的階段重複概念！）：\n"
                f'  "new_stage_genesis": {{\n'
                f'    "stage": {next_st_num},\n'
                f'    "name": "Stage {next_st_num}: (請獨立推演與前序階段完全不重複的新階段名稱)",\n'
                f'    "lore": "(請寫 2~3 句你獨立構思的演化世界觀故事，勿依賴固定套路)",\n'
                f'    "goal_desc": "(請設定此階段的演化目標描述)",\n'
                f'    "target_mw": {float(meta.get("target_mw", 1000000.0)) * 5.0:.1f},\n'
                f'    "years_per_tick": {float(meta.get("years_per_tick", 10000.0)) * 10.0:.1f}\n'
                f'  }}\n'
            )
        if st_num >= 7:
            consumer_line = (
                f"  • 🧠 AI 推論算力消耗端 (Consumer): [♾️ Stage {st_num} 多重宇宙超膜奇點啟動 — 黑洞視界壽命 ∞ 無限大!] "
                f"算力直接由高維真空零點能與超膜張力供給（蓄電池零消耗、黑洞壽命 ∞ 永不枯竭）！\n"
            )
        elif st_num == 6:
            consumer_line = (
                f"  • 🧠 AI 推論算力消耗端 (Consumer): [🕳️ Stage 6 霍金輻射量子迴路啟動 — 蓄電池零消耗!] "
                f"上次推論直接由視界虛粒子對稱破缺驅動，扣除黑洞壽命 -{s.get('last_ai_bh_years_cost', 0.0):,.0f} 地球年 | "
                f"剩餘黑洞壽命: {s.get('blackhole_lifespan_years', 100000000.0):,.0f} 年 ({s.get('blackhole_lifespan_pct', 100.0):.2f}%，維持底層重氫庫存可向吸積盤餵食質量回補壽命！)\n"
            )
        else:
            consumer_line = (
                f"  • 🧠 AI 推論算力消耗端 (Consumer): 上次推論耗時 {s.get('last_ai_infer_sec', 0.0):.2f}s × "
                f"係數 {s.get('ai_compute_coeff_mwh_per_s', 10.0):.1f} MWh/s = 扣除蓄電 -{s.get('last_ai_consumed_mwh', 0.0):.1f} MWh "
                f"(累計總算力耗電: {s.get('total_ai_consumed_mwh', 0.0):.1f} MWh；若蓄電扣光將觸發透支停電！請拉長 next_wake_ticks 讓電網回充)\n"
            )

        def _fn(v: Any, d: int = 1) -> str:
            fv = float(v)
            return f"{fv:.3e}" if abs(fv) >= 1e9 else f"{fv:,.{d}f}"

        parse_err_banner = ""
        last_perr = str(s.get("last_parse_error", "")).strip()
        if last_perr:
            parse_err_banner = (
                f"\n🚨 【❌ 上一輪 `<dyson_action>` 格式解析錯誤回傳 (Parser Exception Feedback — 請本輪修正語法！)】\n"
                f"  • Python JSON Parser 報錯訊息: `{last_perr}`\n"
                f"  • 修正要求: 請嚴格遵守標準 JSON 語法！字串內嚴禁使用單反斜線 LaTeX（如 `\\alpha`、`\\Lambda` 會觸發 `Invalid \\escape`，請直接寫希臘字母 `α`、`Λ`），並確保所有引號、`[]`、`{{}}` 與 `</dyson_action>` 完整閉合！\n"
            )

        prompt = (
            f"【💓 戴森球計畫 Heartbeat 進度與遙測同步 | Tick #{s['tick']} | {meta['name']}】\n"
            f"{parse_err_banner}"
            f"🌟 [階段晉升經驗能量條 (Stage Ascension EXP Bar)]：\n"
            f"  • 充能進度: [{bar_visual}] {exp_pct:.1f}% / 100.0% (每 Tick 充能速率: {exp_rate:+.2f}%/tick)\n"
            f"  • 晉升規則: 必須同時滿足 ① 總發電量 P_gen >= 當前階段目標 ({_fn(meta.get('target_mw', 55.0))} MW) 且 ② 經驗條集滿 100.0% 才會躍遷至下一階段（未達標前經驗條最高鎖在 99.0%）！\n"
            f"  • 蓄電與斷電鐵律: `battery_mode` 僅接受 `-1` (強制優先充電)、`0` (自動平衡)、`1` (強制放電)；若蓄電池被 AI 算力扣至 `< 0.0 MWh` 負數將直接觸發 💀 GAME OVER 斷電死機！\n"
            f"🎯 當前階段目標：{meta['goal_desc']}\n"
            f"{genesis_prompt_block}\n"
            f"📊 [即時熱力學與電網遙測 (Thermodynamic Telemetry)]：\n"
            f"  • 總發電量 P_gen = {_fn(s['p_gen_mw'])} MW | 總負載 P_req = {_fn(s['p_req_mw'])} MW | 淨電力 ΔP = {_fn(s['p_net_mw'])} MW\n"
            f"  • 電網供電滿足率 η = {s['grid_satisfaction']*100:.1f}% | 蓄電器儲能 = {_fn(s['battery_charge_mwh'])} / {_fn(s['battery_capacity_mwh'])} MWh\n"
            f"  • 🌌 宇宙紀元時間尺度：累計 {_fn(s.get('cosmic_years', 0.0), 0)} 地球年 (當前時間流速: 1 Tick = {_fn(s.get('years_per_tick', 1.0), 0)} 地球年)\n"
            f"{consumer_line}"
            f"  • 發電結構：☢️核分裂={_fn(s.get('gen_fission_mw', 8.4))} MW ({_fn(s.get('fission_plants', 3.0))}座), 🌋地熱能={_fn(s.get('gen_geothermal_mw', 0.0))} MW ({_fn(s.get('geothermal_plants', 0.0))}座), 🌊深海洋流={_fn(s.get('gen_ocean_current_mw', 0.0))} MW ({_fn(s.get('ocean_current_turbines', 0.0))}組), 🔥火力={_fn(s['gen_thermal_mw'])} MW, ⚛️重氫核融合={_fn(s['gen_fusion_mw'])} MW, ☀️戴森雲接收站={_fn(s['gen_dyson_receiver_mw'])} MW, 🌌反物質太陽={_fn(s['gen_antimatter_mw'])} MW, ⚠️空轉逆火負發電=-{_fn(s.get('parasitic_drain_mw', 0.0))} MW\n"
            f"  • 🏗️ 科技樹與基建重心 (`build_focus`) 路線圖：Stage 1 前 100 Ticks 為 2026 現狀（僅開放 `\"fission\"` 一般核分裂與 `\"thermal\"` 火力發電）；滿 100 Ticks 後自動解鎖 `\"geothermal\"` (地熱能 1.6MW/座) 與 `\"ocean_current\"` (洋流 1.0MW/組) 衝刺 55 MW！Stage 2 解鎖 `\"refinery\"` 與 `\"fusion\"` (重氫核融合電廠)；Stage 3 以核融合高壓電網搭配 `\"swarm\"` (太陽系戴森雲與接收站)；Stage 4+ 推進 `\"shell\"` (永久戴森球殼與反物質太陽)。\n"
            f"  • ⛏️ 原材料與採礦工業鏈：自動化採礦設備={_fn(s.get('mining_rigs', 6.0))} 台 (增產率 mining_rig_build_rate={p.get('mining_rig_build_rate', 0.35):.2f}), 原材料庫存={_fn(s.get('raw_material_stock', 180.0))} 噸 (開採 +{_fn(s.get('last_mat_mined', 0.0))}/t | 蓋基建消耗 -{_fn(s.get('last_mat_consumed', 0.0))}/t | 隨 EXP 級數耗材倍率={s.get('mat_exp_cost_mult', 1.0):.2f}x)\n"
            f"  • 化工與底層燃料鏈：燃煤庫存={_fn(s['coal_stock'])}, 氫氣儲槽(H2)={s['hydrogen_tank_pct']:.1f}%, 精煉油儲槽={s['refined_oil_tank_pct']:.1f}%, 重氫庫存={_fn(s['deuterium_stock'])}, 反物質燃料棒庫存={_fn(s.get('antimatter_rod_stock', 0.0))}\n"
            f"  • 太陽系與超維指標：軌道太陽帆={_fn(s['active_solar_sails'], 0)} 面, 戴森球結構節點={_fn(s['dyson_shell_nodes'])} (覆蓋 {_fn(s['dyson_shell_coverage_pct'])}%), EROEI={_fn(s['eroei'], 2)}, 🌀 多維非線性指數 α_dim={p.get('dimensional_exponent', 1.0):.2f} (超維能量利用率倍率={_fn(s.get('multidim_utilization_factor', 1.0), 2)}x | 自然熵損耗: {s.get('wear_rate_500t_pct', 0.1):.1f}%/500t)\n\n"
            f"🚨 [太空災難與死鎖診斷 (Active Faults & Bottlenecks)]：\n"
            f"{alert_block}\n\n"
            f"🎛️ [目前動態控制參數 (Current Control Parameters)]：\n"
            f"  {json.dumps(p, ensure_ascii=False)}\n\n"
            f"{inst_footer}"
        )
        return prompt


class DysonActionParser:
    """Robustly extracts dynamic control parameters from LLM output (`<dyson_action>`, JSON blocks, or regex)."""

    VALID_KEYS = {
        "coal_throttle",
        "fusion_throttle",
        "antimatter_throttle",
        "load_shed_non_essential",
        "hydrogen_burn_valve",
        "refined_oil_crack_ratio",
        "deuterium_fraction_rate",
        "em_ejector_rate",
        "rocket_launch_rate",
        "ray_receiver_photon_ratio",
        "mining_rig_build_rate",
        "dimensional_exponent",
        "battery_mode",
        "build_focus",
        "next_wake_ticks",
        "action_queue",
        "new_stage_genesis",
    }

    @classmethod
    def parse_ai_response(cls, raw_text: str) -> Tuple[Dict[str, Any], List[str]]:
        if not raw_text:
            return {}, []

        candidates: List[str] = []
        # 1. Highest Priority: Explicit <dyson_action>...</dyson_action> (greedy inner JSON to support nested action_queue!)
        for m in re.finditer(r"<dyson_action>\s*(\{.*\})\s*</dyson_action>", raw_text, flags=re.DOTALL):
            candidates.append(m.group(1))
        # 2. Second Priority: Markdown ```json ... ``` blocks
        if not candidates:
            for m in re.finditer(r"```(?:json)?\s*(\{.*?\})\s*```", raw_text, flags=re.DOTALL):
                candidates.append(m.group(1))
        # 3. Fallback Only: flat JSON object if no <dyson_action> or code fence was found
        if not candidates:
            for m in re.finditer(r"(\{[^{}]*\"(?:coal_throttle|fusion_throttle|hydrogen_burn_valve|build_focus|em_ejector_rate)\"[^{}]*\})", raw_text, flags=re.DOTALL):
                candidates.append(m.group(1))

        parsed: Dict[str, Any] = {}
        last_json_err: str = ""
        if "<dyson_action>" not in raw_text:
            last_json_err = "Missing <dyson_action>{...}</dyson_action> wrapper tag in response."
        elif "</dyson_action>" not in raw_text:
            last_json_err = "Truncated <dyson_action> block: missing closing </dyson_action> tag."

        for c in reversed(candidates):
            # First test strict `json.loads(c)` to catch raw syntax errors (like unescaped \alpha or truncated array) for feedback to 31B!
            try:
                strict_obj = json.loads(c)
                if isinstance(strict_obj, dict):
                    for k, v in strict_obj.items():
                        if k in cls.VALID_KEYS:
                            parsed[k] = v
                    if parsed:
                        break
            except Exception as e_strict:
                last_json_err = f"{type(e_strict).__name__}: {e_strict}"

            # Then attempt auto-sanitized recovery (LaTeX backslash & truncated action_queue auto-close)
            c_clean = re.sub(r'\\(?![/\"\\bfnrtu])', r'\\\\', c)
            attempt_strs = [c_clean]
            if '"action_queue"' in c_clean and not c_clean.rstrip().endswith("]}"):
                last_brace = c_clean.rfind("}")
                if last_brace > 0:
                    attempt_strs.insert(0, c_clean[: last_brace + 1] + "]}")
            for s_try in attempt_strs:
                try:
                    obj = json.loads(s_try)
                    if isinstance(obj, dict):
                        for k, v in obj.items():
                            if k in cls.VALID_KEYS:
                                parsed[k] = v
                        if parsed:
                            break
                except Exception as e_rec:
                    if not last_json_err:
                        last_json_err = f"{type(e_rec).__name__}: {e_rec}"
                    continue
            if parsed:
                break

        # Fallback regex recovery for `new_stage_genesis` if JSON had unescaped quotes or syntax quirks!
        if '"new_stage_genesis"' in raw_text and "new_stage_genesis" not in parsed:
            g_name = re.search(r'"name"\s*:\s*"([^"]+)"', raw_text)
            g_lore = re.search(r'"lore"\s*:\s*"([^"]+)"', raw_text)
            g_goal = re.search(r'"goal_desc"\s*:\s*"([^"]+)"', raw_text)
            g_tmw = re.search(r'"target_mw"\s*:\s*([0-9.eE+-]+)', raw_text)
            g_ypt = re.search(r'"years_per_tick"\s*:\s*([0-9.eE+-]+)', raw_text)
            g_st = re.search(r'"stage"\s*:\s*(\d+)', raw_text)
            if g_name or g_lore:
                parsed["new_stage_genesis"] = {
                    "stage": int(g_st.group(1)) if g_st else None,
                    "name": g_name.group(1) if g_name else "Stage: 超維奇點演化",
                    "lore": g_lore.group(1) if g_lore else "",
                    "goal_desc": g_goal.group(1) if g_goal else "",
                    "target_mw": float(g_tmw.group(1)) if g_tmw else 5000000.0,
                    "years_per_tick": float(g_ypt.group(1)) if g_ypt else 100000.0,
                }

        # Fallback regex key-value & action_queue extraction if JSON was truncated mid-item!
        if '"action_queue"' in raw_text and "action_queue" not in parsed:
            q_part_m = re.search(r'"action_queue"\s*:\s*\[(.*)', raw_text, flags=re.DOTALL)
            if q_part_m:
                q_body = q_part_m.group(1)
                recovered_q = []
                for item_m in re.finditer(r"(\{[^{}]*\})", q_body):
                    try:
                        q_obj = json.loads(item_m.group(1))
                        if isinstance(q_obj, dict) and "delay_ticks" in q_obj:
                            recovered_q.append(q_obj)
                    except Exception:
                        pass
                if recovered_q:
                    parsed["action_queue"] = recovered_q

        if "next_wake_ticks" not in parsed and '"next_wake_ticks"' in raw_text:
            m_wake = re.search(r'"next_wake_ticks"\s*:\s*(\d+)', raw_text)
            if m_wake:
                parsed["next_wake_ticks"] = int(m_wake.group(1))

        if not parsed:
            for k in cls.VALID_KEYS:
                if k == "build_focus":
                    m_str = re.search(rf'"{k}"\s*:\s*"([a-zA-Z_]+)"', raw_text)
                    if m_str:
                        parsed[k] = m_str.group(1)
                elif k == "battery_mode":
                    m_int = re.search(rf'"{k}"\s*:\s*(-?\d+)', raw_text)
                    if m_int:
                        parsed[k] = int(m_int.group(1))
                else:
                    m_flt = re.search(rf'"{k}"\s*:\s*([0-9]+(?:\.[0-9]+)?)', raw_text)
                    if m_flt:
                        parsed[k] = float(m_flt.group(1))

        summary_lines = [f"{k}={v}" for k, v in parsed.items()]
        if last_json_err:
            parsed["_parse_error"] = last_json_err
            summary_lines.append(f"⚠️[ParserError: {last_json_err}]")
        return parsed, summary_lines
