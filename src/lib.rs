use pyo3::prelude::*;
use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct DysonControlParams {
    pub coal_throttle: f64,             // 0.0 .. 1.5 (Thermal plant throttle)
    pub fusion_throttle: f64,           // 0.0 .. 1.5 (Deuterium mini-fusion throttle)
    pub antimatter_throttle: f64,       // 0.0 .. 1.5 (Artificial Sun throttle)
    pub load_shed_non_essential: f64,   // 0.0 .. 0.9 (Fraction of non-essential factory load shed during brownout)
    pub hydrogen_burn_valve: f64,       // 0.0 .. 1.0 (Overflow H2 routed to thermal burners to prevent tank deadlock)
    pub refined_oil_crack_ratio: f64,   // 0.0 .. 1.0 (X-ray cracking of refined oil -> H2 + energetic graphite)
    pub deuterium_fraction_rate: f64,   // 0.0 .. 1.0 (Fractionator power routing to convert H2 -> Deuterium)
    pub em_ejector_rate: f64,           // 0.0 .. 1.0 (Solar sail electromagnetic railgun launch rate)
    pub rocket_launch_rate: f64,        // 0.0 .. 1.0 (Small carrier rocket launch rate for permanent Dyson nodes)
    pub ray_receiver_photon_ratio: f64, // 0.0 .. 1.0 (0.0 = 100% Direct Grid Power, 1.0 = 100% Critical Photon generation)
    pub battery_mode: i32,              // -1 = Force Charge, 0 = Auto Buffer, 1 = Emergency Discharge
    pub build_focus: String,            // "solar" | "thermal" | "refinery" | "fusion" | "swarm" | "shell" | "balanced"
}

impl Default for DysonControlParams {
    fn default() -> Self {
        Self {
            coal_throttle: 1.0,
            fusion_throttle: 0.6,
            antimatter_throttle: 0.5,
            load_shed_non_essential: 0.0,
            hydrogen_burn_valve: 0.15,
            refined_oil_crack_ratio: 0.30,
            deuterium_fraction_rate: 0.40,
            em_ejector_rate: 0.35,
            rocket_launch_rate: 0.25,
            ray_receiver_photon_ratio: 0.20,
            battery_mode: 0,
            build_focus: "balanced".to_string(),
        }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct DysonSimState {
    pub tick: u64,
    pub stage: u32,                     // 1=Earth Grid, 2=Deuterium/Cracking, 3=Solar Swarm, 4=Dyson Shell
    pub auto_advance_stage: bool,

    // Power Grid (MW)
    pub p_gen_mw: f64,
    pub p_req_mw: f64,
    pub p_net_mw: f64,
    pub grid_satisfaction: f64,         // eta = min(1.0, p_gen / p_req)
    pub battery_charge_mwh: f64,
    pub battery_capacity_mwh: f64,

    // Breakdown of generation (MW)
    pub gen_solar_wind_mw: f64,
    pub gen_thermal_mw: f64,
    pub gen_fusion_mw: f64,
    pub gen_dyson_receiver_mw: f64,
    pub gen_antimatter_mw: f64,

    // Planetary & Orbital Assets
    pub solar_panels: f64,
    pub thermal_plants: f64,
    pub refineries: f64,
    pub fusion_plants: f64,
    pub em_ejectors: f64,
    pub rocket_silos: f64,
    pub ray_receivers: f64,
    pub artificial_suns: f64,

    // Resources & Storage Tanks (0.0 .. 100.0 % for tanks)
    pub coal_stock: f64,
    pub hydrogen_tank_pct: f64,
    pub refined_oil_tank_pct: f64,
    pub deuterium_stock: f64,
    pub solar_sail_stock: f64,
    pub rocket_stock: f64,
    pub antimatter_rod_stock: f64,

    // Dyson Swarm & Shell (Solar System Scale)
    pub active_solar_sails: f64,
    pub dyson_shell_nodes: f64,
    pub dyson_shell_coverage_pct: f64,
    pub dyson_total_luminosity_mw: f64,
    pub eroei: f64,

    // Faults / Alerts
    pub fault_dust_storm: f64,          // 0.0 .. 0.85 reduction in planetary solar
    pub fault_h2_deadlock: bool,        // True when H2 or Oil tank >= 99.5%
    pub fault_brownout_spiral: bool,    // True when grid_satisfaction < 0.55
    pub fault_seu_bitflip: bool,        // True when cosmic ray corrupted control params
    pub active_alerts: Vec<String>,

    // Control Parameters
    pub params: DysonControlParams,
}

impl Default for DysonSimState {
    fn default() -> Self {
        Self {
            tick: 0,
            stage: 1,
            auto_advance_stage: true,
            p_gen_mw: 28.0,
            p_req_mw: 24.0,
            p_net_mw: 4.0,
            grid_satisfaction: 1.0,
            battery_charge_mwh: 120.0,
            battery_capacity_mwh: 300.0,
            gen_solar_wind_mw: 14.0,
            gen_thermal_mw: 14.0,
            gen_fusion_mw: 0.0,
            gen_dyson_receiver_mw: 0.0,
            gen_antimatter_mw: 0.0,
            solar_panels: 28.0,
            thermal_plants: 8.0,
            refineries: 6.0,
            fusion_plants: 2.0,
            em_ejectors: 4.0,
            rocket_silos: 2.0,
            ray_receivers: 6.0,
            artificial_suns: 1.0,
            coal_stock: 180.0,
            hydrogen_tank_pct: 42.0,
            refined_oil_tank_pct: 38.0,
            deuterium_stock: 45.0,
            solar_sail_stock: 60.0,
            rocket_stock: 15.0,
            antimatter_rod_stock: 8.0,
            active_solar_sails: 120.0,
            dyson_shell_nodes: 4.0,
            dyson_shell_coverage_pct: 0.8,
            dyson_total_luminosity_mw: 36.0,
            eroei: 1.15,
            fault_dust_storm: 0.0,
            fault_h2_deadlock: false,
            fault_brownout_spiral: false,
            fault_seu_bitflip: false,
            active_alerts: Vec::new(),
            params: DysonControlParams::default(),
        }
    }
}

#[pyclass]
pub struct RustDysonSimulator {
    state: DysonSimState,
    last_sync_gen_mw: f64,
    last_sync_eroei: f64,
}

#[pymethods]
impl RustDysonSimulator {
    #[new]
    pub fn new() -> Self {
        let s = DysonSimState::default();
        Self {
            last_sync_gen_mw: s.p_gen_mw,
            last_sync_eroei: s.eroei,
            state: s,
        }
    }

    pub fn reset_stage(&mut self, stage: u32) -> String {
        let mut s = DysonSimState::default();
        s.stage = stage.clamp(1, 4);
        match s.stage {
            1 => {
                s.solar_panels = 24.0;
                s.thermal_plants = 7.0;
                s.coal_stock = 140.0;
            }
            2 => {
                s.solar_panels = 60.0;
                s.thermal_plants = 16.0;
                s.refineries = 18.0;
                s.fusion_plants = 8.0;
                s.hydrogen_tank_pct = 78.0;
                s.refined_oil_tank_pct = 52.0;
                s.deuterium_stock = 80.0;
                s.battery_capacity_mwh = 1200.0;
                s.battery_charge_mwh = 500.0;
            }
            3 => {
                s.solar_panels = 120.0;
                s.thermal_plants = 24.0;
                s.refineries = 28.0;
                s.fusion_plants = 22.0;
                s.em_ejectors = 18.0;
                s.ray_receivers = 24.0;
                s.active_solar_sails = 850.0;
                s.deuterium_stock = 260.0;
                s.battery_capacity_mwh = 5000.0;
                s.battery_charge_mwh = 2400.0;
            }
            4 => {
                s.solar_panels = 200.0;
                s.thermal_plants = 30.0;
                s.refineries = 40.0;
                s.fusion_plants = 45.0;
                s.em_ejectors = 36.0;
                s.rocket_silos = 16.0;
                s.ray_receivers = 64.0;
                s.artificial_suns = 6.0;
                s.active_solar_sails = 3200.0;
                s.dyson_shell_nodes = 38.0;
                s.dyson_shell_coverage_pct = 12.5;
                s.antimatter_rod_stock = 35.0;
                s.battery_capacity_mwh = 25000.0;
                s.battery_charge_mwh = 12000.0;
            }
            _ => {}
        }
        self.state = s;
        self.step_ticks(1);
        self.last_sync_gen_mw = self.state.p_gen_mw;
        self.last_sync_eroei = self.state.eroei;
        self.get_state_json()
    }

    pub fn step_ticks(&mut self, n_ticks: u32) -> String {
        for _ in 0..n_ticks.max(1) {
            self.step_single_tick();
        }
        self.get_state_json()
    }

    pub fn inject_fault(&mut self, fault_type: &str) -> String {
        match fault_type {
            "brownout" | "dust_storm" => {
                self.state.fault_dust_storm = 0.78;
                self.state.coal_stock = (self.state.coal_stock * 0.18).max(8.0);
                self.state.battery_charge_mwh *= 0.15;
                self.state.params.load_shed_non_essential = 0.0;
            }
            "h2_deadlock" => {
                self.state.hydrogen_tank_pct = 99.8;
                self.state.params.hydrogen_burn_valve = 0.0;
                self.state.params.deuterium_fraction_rate = 0.05;
                self.state.fault_h2_deadlock = true;
            }
            "seu_bitflip" => {
                self.state.fault_seu_bitflip = true;
                self.state.params.coal_throttle = 0.15;
                self.state.params.fusion_throttle = 0.10;
                self.state.params.hydrogen_burn_valve = 0.0;
                self.state.params.ray_receiver_photon_ratio = 0.95;
                self.state.params.battery_mode = -1;
            }
            "clear" => {
                self.state.fault_dust_storm = 0.0;
                self.state.fault_h2_deadlock = false;
                self.state.fault_brownout_spiral = false;
                self.state.fault_seu_bitflip = false;
                self.state.hydrogen_tank_pct = self.state.hydrogen_tank_pct.min(65.0);
                self.state.refined_oil_tank_pct = self.state.refined_oil_tank_pct.min(60.0);
                self.state.coal_stock = self.state.coal_stock.max(150.0);
            }
            _ => {}
        }
        self.step_single_tick();
        self.get_state_json()
    }

    pub fn apply_action_json(&mut self, action_json: &str) -> String {
        if let Ok(val) = serde_json::from_str::<serde_json::Value>(action_json) {
            if let Some(v) = val.get("coal_throttle").and_then(|x| x.as_f64()) {
                self.state.params.coal_throttle = v.clamp(0.0, 1.5);
            }
            if let Some(v) = val.get("fusion_throttle").and_then(|x| x.as_f64()) {
                self.state.params.fusion_throttle = v.clamp(0.0, 1.5);
            }
            if let Some(v) = val.get("antimatter_throttle").and_then(|x| x.as_f64()) {
                self.state.params.antimatter_throttle = v.clamp(0.0, 1.5);
            }
            if let Some(v) = val.get("load_shed_non_essential").and_then(|x| x.as_f64()) {
                self.state.params.load_shed_non_essential = v.clamp(0.0, 0.90);
            }
            if let Some(v) = val.get("hydrogen_burn_valve").and_then(|x| x.as_f64()) {
                self.state.params.hydrogen_burn_valve = v.clamp(0.0, 1.0);
            }
            if let Some(v) = val.get("refined_oil_crack_ratio").and_then(|x| x.as_f64()) {
                self.state.params.refined_oil_crack_ratio = v.clamp(0.0, 1.0);
            }
            if let Some(v) = val.get("deuterium_fraction_rate").and_then(|x| x.as_f64()) {
                self.state.params.deuterium_fraction_rate = v.clamp(0.0, 1.0);
            }
            if let Some(v) = val.get("em_ejector_rate").and_then(|x| x.as_f64()) {
                self.state.params.em_ejector_rate = v.clamp(0.0, 1.0);
            }
            if let Some(v) = val.get("rocket_launch_rate").and_then(|x| x.as_f64()) {
                self.state.params.rocket_launch_rate = v.clamp(0.0, 1.0);
            }
            if let Some(v) = val.get("ray_receiver_photon_ratio").and_then(|x| x.as_f64()) {
                self.state.params.ray_receiver_photon_ratio = v.clamp(0.0, 1.0);
            }
            if let Some(v) = val.get("battery_mode").and_then(|x| x.as_i64()) {
                self.state.params.battery_mode = (v as i32).clamp(-1, 1);
            }
            if let Some(v) = val.get("build_focus").and_then(|x| x.as_str()) {
                self.state.params.build_focus = v.to_string();
            }
            // If AI intervened, clear SEU bitflip flag if throttles restored
            if self.state.params.coal_throttle >= 0.5 || self.state.params.fusion_throttle >= 0.4 {
                self.state.fault_seu_bitflip = false;
            }
        }
        self.get_state_json()
    }

    pub fn evaluate_sync_window(&mut self) -> String {
        let prev_gen = self.last_sync_gen_mw.max(1.0);
        let cur_gen = self.state.p_gen_mw;
        let delta_mw = cur_gen - prev_gen;
        let healthy = !self.state.fault_brownout_spiral
            && !self.state.fault_h2_deadlock
            && self.state.grid_satisfaction >= 0.85;
        let passed = healthy && (delta_mw >= -2.0 || self.state.eroei >= 1.1);

        self.last_sync_gen_mw = cur_gen;
        self.last_sync_eroei = self.state.eroei;

        let res = serde_json::json!({
            "passed": passed,
            "exit_code": if passed { 0 } else { 1 },
            "delta_gen_mw": delta_mw,
            "grid_satisfaction": self.state.grid_satisfaction,
            "eroei": self.state.eroei,
            "Consolidation_mode": if passed { "LTM_CONSOLIDATED" } else { "ANTI_HEBBIAN_ROLLBACK" }
        });
        res.to_string()
    }

    pub fn get_state_json(&self) -> String {
        serde_json::to_string(&self.state).unwrap_or_else(|_| "{}".to_string())
    }
}

impl RustDysonSimulator {
    fn step_single_tick(&mut self) {
        let s = &mut self.state;
        s.tick += 1;

        // Gradual dust storm decay
        if s.fault_dust_storm > 0.01 {
            s.fault_dust_storm = (s.fault_dust_storm * 0.992).max(0.0);
        } else {
            s.fault_dust_storm = 0.0;
        }

        // Previous satisfaction governs miner & sorter speed (non-linear brownout curve!)
        let eta = s.grid_satisfaction.clamp(0.08, 1.0);
        let sorter_eff = if eta < 0.75 { eta * eta } else { eta };
        let non_ess_scale = (1.0 - s.params.load_shed_non_essential).clamp(0.1, 1.0);

        // 1. Coal Mining & Thermal Power
        let coal_mined = (1.8 + 0.35 * s.thermal_plants) * eta;
        let coal_burn_req = s.thermal_plants * 0.42 * s.params.coal_throttle * sorter_eff;
        let actual_coal_burned = coal_burn_req.min(s.coal_stock);
        s.coal_stock = (s.coal_stock + coal_mined - actual_coal_burned).clamp(0.0, 2000.0);

        // H2 overflow burning in thermal plants
        let h2_burn = (s.hydrogen_tank_pct * 0.08 * s.params.hydrogen_burn_valve).min(s.hydrogen_tank_pct);
        s.hydrogen_tank_pct = (s.hydrogen_tank_pct - h2_burn).max(0.0);

        s.gen_solar_wind_mw = s.solar_panels * 0.55 * (1.0 - s.fault_dust_storm);
        s.gen_thermal_mw = actual_coal_burned * 5.8 + h2_burn * 4.2;

        // 2. Plasma Refining & Chemical Loop (Stage 2+)
        s.fault_h2_deadlock = s.hydrogen_tank_pct >= 98.5 || s.refined_oil_tank_pct >= 98.5;
        let refinery_active = if s.fault_h2_deadlock { 0.05 } else { eta * non_ess_scale };
        let h2_prod = s.refineries * 0.26 * refinery_active * (1.0 + 0.5 * s.params.refined_oil_crack_ratio);
        let oil_prod = s.refineries * 0.22 * refinery_active * (1.0 - 0.65 * s.params.refined_oil_crack_ratio);

        // Deuterium Fractionation from H2
        let deut_conv = (s.hydrogen_tank_pct * 0.09 * s.params.deuterium_fraction_rate * eta * non_ess_scale)
            .min(s.hydrogen_tank_pct);
        s.hydrogen_tank_pct = (s.hydrogen_tank_pct + h2_prod - deut_conv).clamp(0.0, 100.0);
        s.refined_oil_tank_pct = (s.refined_oil_tank_pct + oil_prod - 0.12 * s.refineries * eta).clamp(0.0, 100.0);
        s.deuterium_stock = (s.deuterium_stock + deut_conv * 3.2).clamp(0.0, 5000.0);

        // Mini-Fusion Generation
        let deut_burn_req = s.fusion_plants * 0.35 * s.params.fusion_throttle * sorter_eff;
        let actual_deut_burned = deut_burn_req.min(s.deuterium_stock);
        s.deuterium_stock = (s.deuterium_stock - actual_deut_burned).max(0.0);
        s.gen_fusion_mw = actual_deut_burned * 48.0;

        // 3. Solar System Dyson Swarm & Shell (Stage 3 & 4)
        let sails_launched = s.em_ejectors * 2.4 * s.params.em_ejector_rate * eta * non_ess_scale;
        let sail_decay = s.active_solar_sails * 0.0025;
        s.active_solar_sails = (s.active_solar_sails + sails_launched - sail_decay).clamp(0.0, 250000.0);

        let rockets_launched = if s.stage >= 3 {
            s.rocket_silos * 0.18 * s.params.rocket_launch_rate * eta * non_ess_scale
        } else {
            0.0
        };
        s.dyson_shell_nodes = (s.dyson_shell_nodes + rockets_launched).clamp(0.0, 5000.0);
        s.dyson_shell_coverage_pct = ((s.dyson_shell_nodes / 240.0) * 100.0 + (s.active_solar_sails / 15000.0) * 15.0).clamp(0.0, 100.0);

        // Total Dyson Luminosity (Swarm + Permanent Shell)
        s.dyson_total_luminosity_mw = s.active_solar_sails * 1.65 + s.dyson_shell_nodes * 420.0;
        let receiver_cap_mw = s.ray_receivers * 185.0;
        let captured_dyson_mw = s.dyson_total_luminosity_mw.min(receiver_cap_mw);

        let direct_grid_ratio = (1.0 - s.params.ray_receiver_photon_ratio).clamp(0.0, 1.0);
        s.gen_dyson_receiver_mw = captured_dyson_mw * direct_grid_ratio;

        // Critical Photons -> Antimatter Fuel Rods -> Artificial Suns (Stage 4)
        let photon_power_mw = captured_dyson_mw * s.params.ray_receiver_photon_ratio;
        let am_rods_created = (photon_power_mw / 450.0) * eta;
        let am_rods_burned = (s.artificial_suns * 0.25 * s.params.antimatter_throttle).min(s.antimatter_rod_stock);
        s.antimatter_rod_stock = (s.antimatter_rod_stock + am_rods_created - am_rods_burned).clamp(0.0, 5000.0);
        s.gen_antimatter_mw = am_rods_burned * 7500.0;

        // 4. Power Demand Calculation
        let base_req = 8.0 + s.solar_panels * 0.05 + s.thermal_plants * 0.35;
        let chem_req = (s.refineries * 1.4 + s.fusion_plants * 1.8 * s.params.deuterium_fraction_rate) * non_ess_scale;
        let launch_req = (s.em_ejectors * 6.5 * s.params.em_ejector_rate
            + s.rocket_silos * 42.0 * s.params.rocket_launch_rate)
            * non_ess_scale;
        s.p_req_mw = (base_req + chem_req + launch_req).max(5.0);

        let raw_gen_mw = s.gen_solar_wind_mw + s.gen_thermal_mw + s.gen_fusion_mw + s.gen_dyson_receiver_mw + s.gen_antimatter_mw;

        // Battery Buffer Logic
        let mut net_mw = raw_gen_mw - s.p_req_mw;
        if s.params.battery_mode == 1 || (s.params.battery_mode == 0 && net_mw < 0.0) {
            let max_discharge = (s.battery_charge_mwh * 0.35).min(s.p_req_mw * 0.8);
            let discharge = if net_mw < 0.0 { (-net_mw).min(max_discharge) } else { max_discharge * 0.25 };
            s.battery_charge_mwh = (s.battery_charge_mwh - discharge * 0.1).max(0.0);
            net_mw += discharge;
        } else if net_mw > 0.0 && s.battery_charge_mwh < s.battery_capacity_mwh {
            let charge = (net_mw * 0.4).min(s.battery_capacity_mwh - s.battery_charge_mwh);
            s.battery_charge_mwh = (s.battery_charge_mwh + charge * 0.1).min(s.battery_capacity_mwh);
        }

        s.p_gen_mw = raw_gen_mw;
        s.p_net_mw = net_mw;
        s.grid_satisfaction = ((raw_gen_mw + if net_mw >= 0.0 { 0.0 } else { 0.0 }) / s.p_req_mw).clamp(0.05, 1.5);
        if net_mw >= 0.0 {
            s.grid_satisfaction = (raw_gen_mw / s.p_req_mw).max(1.0).min(1.5);
        }

        // Autonomous Infrastructure Growth when energy surplus exists
        if s.grid_satisfaction >= 0.98 && !s.fault_h2_deadlock {
            let growth = 0.08 * (s.grid_satisfaction - 0.95).clamp(0.02, 0.5);
            match s.params.build_focus.as_str() {
                "solar" => s.solar_panels += growth * 3.5,
                "thermal" => s.thermal_plants += growth * 1.2,
                "refinery" => s.refineries += growth * 1.5,
                "fusion" => {
                    s.fusion_plants += growth * 1.2;
                    s.refineries += growth * 0.6;
                }
                "swarm" => {
                    s.em_ejectors += growth * 1.4;
                    s.ray_receivers += growth * 1.2;
                }
                "shell" => {
                    s.rocket_silos += growth * 0.8;
                    s.ray_receivers += growth * 1.8;
                    s.artificial_suns += growth * 0.35;
                }
                _ => {
                    s.solar_panels += growth * 1.2;
                    if s.stage >= 2 {
                        s.fusion_plants += growth * 0.5;
                    }
                    if s.stage >= 3 {
                        s.em_ejectors += growth * 0.6;
                        s.ray_receivers += growth * 0.6;
                    }
                    if s.stage >= 4 {
                        s.rocket_silos += growth * 0.3;
                        s.artificial_suns += growth * 0.15;
                    }
                }
            }
        }

        // Compute EROEI
        let invested_mw = (launch_req + chem_req * 0.5).max(4.0);
        s.eroei = ((s.gen_dyson_receiver_mw + s.gen_fusion_mw + s.gen_antimatter_mw + s.gen_solar_wind_mw) / invested_mw).clamp(0.1, 25.0);

        // Update Alerts
        s.fault_brownout_spiral = s.grid_satisfaction < 0.65;
        s.active_alerts.clear();
        if s.fault_brownout_spiral {
            s.active_alerts.push(format!("⚡ 電網雪崩警報 (供電率 {:.0}% < 65%，礦機與分揀爪減速中！建議調高 load_shed_non_essential 或開啟電池放電 battery_mode=1)", s.grid_satisfaction * 100.0));
        }
        if s.fault_h2_deadlock {
            s.active_alerts.push(format!("🧪 化工雙輸出爆倉死鎖 (H2={:.1}%, Oil={:.1}%，精煉廠停擺！請立即調高 hydrogen_burn_valve 或 deuterium_fraction_rate)", s.hydrogen_tank_pct, s.refined_oil_tank_pct));
        }
        if s.fault_dust_storm > 0.20 {
            s.active_alerts.push(format!("☄️ 微隕石沙塵暴遮蔽 (地表太陽能效率損失 {:.0}%)", s.fault_dust_storm * 100.0));
        }
        if s.fault_seu_bitflip {
            s.active_alerts.push("☢️ 太陽閃焰單粒子翻轉 (SEU Bit-Flip：反應爐節流閥與接收站模式遭輻射篡改！)".to_string());
        }

        // Stage Auto-Promotion
        if s.auto_advance_stage && s.active_alerts.is_empty() && s.grid_satisfaction >= 1.0 {
            if s.stage == 1 && s.p_gen_mw >= 55.0 {
                s.stage = 2;
                s.battery_capacity_mwh = s.battery_capacity_mwh.max(1200.0);
            } else if s.stage == 2 && s.p_gen_mw >= 450.0 && s.hydrogen_tank_pct < 85.0 {
                s.stage = 3;
                s.battery_capacity_mwh = s.battery_capacity_mwh.max(5000.0);
            } else if s.stage == 3 && s.p_gen_mw >= 4500.0 && s.active_solar_sails >= 1200.0 {
                s.stage = 4;
                s.battery_capacity_mwh = s.battery_capacity_mwh.max(25000.0);
            }
        }
    }
}

#[pymodule]
fn dyson_sim_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<RustDysonSimulator>()?;
    Ok(())
}
