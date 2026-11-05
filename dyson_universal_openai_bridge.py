#!/usr/bin/env python3
"""
dyson_universal_openai_bridge.py - Universal OpenAI-Compatible API Bridge + PyQt6 GUI for `rust_dysonsphere_sim`
=================================================================================================================
Connects any OpenAI-compatible API endpoint (vLLM, Ollama, llama.cpp, SGLang, TensorRT-LLM, OpenRouter,
OpenAI, or enterprise LLM Gateways) to `rust_dysonsphere_sim` (`127.0.0.1:18960`).

Features:
  1. Native Dark-Theme PyQt6 Control Center (default when launched without `--nogui`):
     - Built-in Profile Selector (`configs/openai_bridge_profiles.json`) with persistent API Key storage!
     - Show/Hide API Key toggle (`••••••` / plain text) + One-Click `[💾 儲存當前 Profile (含 API Key)]`
     - `[🔍 探測 /v1/models 並自動選取模型]` button + `[🧪 測試 API 1-Token 連通性]`
     - `[🚀 啟動萬用 Bridge 連線模擬器]` / `[⏹️ 停止 Bridge]`
     - Real-time SSE token streaming monitor & TPS telemetry
  2. Automatic Model Detection & Session Tagging:
     - Automatically queries `GET /v1/models` (or probes 1-token `/v1/chat/completions`) upon connection.
     - Sends `bridge_hello` and tags every `ai_action_complete` packet with `model_id` and `engine_mode`
       so `dyson_pyqt_gui.py` records the exact model in `sessions/*.md`, `sessions/*.jsonl`, and `stage_list.json`!
"""

import argparse
import json
import os
import queue
import ssl
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

SIM_DIR = Path(__file__).resolve().parent
PROFILES_PATH = SIM_DIR / "configs" / "openai_bridge_profiles.json"
sys.path.insert(0, str(SIM_DIR))

from tcp_lockstep_protocol import DEFAULT_TCP_HOST, DEFAULT_TCP_PORT, DysonTcpSyncClient


DEFAULT_PROFILES_DATA: Dict[str, Any] = {
    "active_profile": "local_vllm_or_trtllm",
    "profiles": {
        "local_vllm_or_trtllm": {
            "name": "⚡ Local vLLM / TensorRT-LLM / SGLang (:8000)",
            "api_base": "http://127.0.0.1:8000/v1",
            "api_key": "",
            "model": "auto",
            "engine_label": "Local-vLLM-or-TRTLLM",
            "max_tokens": 1536,
            "temperature": 0.5,
            "top_p": 0.95,
            "tcp_host": "127.0.0.1",
            "tcp_port": 18960,
        },
        "local_llamacpp": {
            "name": "🖥️ Local llama.cpp Server (:8001)",
            "api_base": "http://127.0.0.1:8001/v1",
            "api_key": "",
            "model": "auto",
            "engine_label": "Local-LlamaCpp-Server",
            "max_tokens": 1536,
            "temperature": 0.5,
            "top_p": 0.95,
            "tcp_host": "127.0.0.1",
            "tcp_port": 18960,
        },
        "local_ollama": {
            "name": "🦙 Local Ollama Server (:11434)",
            "api_base": "http://127.0.0.1:11434/v1",
            "api_key": "",
            "model": "auto",
            "engine_label": "Local-Ollama",
            "max_tokens": 1536,
            "temperature": 0.5,
            "top_p": 0.95,
            "tcp_host": "127.0.0.1",
            "tcp_port": 18960,
        },
        "openrouter_cloud": {
            "name": "🌐 OpenRouter / Cloud OpenAI-Compatible API",
            "api_base": "https://openrouter.ai/api/v1",
            "api_key": "",
            "model": "auto",
            "engine_label": "OpenRouter-Cloud-API",
            "max_tokens": 1536,
            "temperature": 0.5,
            "top_p": 0.95,
            "max_session_calls": 60,
            "max_session_tokens": 250000,
            "tcp_host": "127.0.0.1",
            "tcp_port": 18960,
        },
        "google_gemini_native_rest": {
            "name": "☁️ Google AI Studio 原生 REST (v1beta/models:generateContent + 防爆)",
            "api_base": "https://generativelanguage.googleapis.com/v1beta",
            "api_key": "",
            "model": "gemini-2.5-flash",
            "engine_label": "Google-Gemini-Native-REST (Vanilla No-LoRA)",
            "max_tokens": 1280,
            "temperature": 0.5,
            "top_p": 0.95,
            "max_session_calls": 55,
            "max_session_tokens": 250000,
            "tcp_host": "127.0.0.1",
            "tcp_port": 18960,
        },
        "google_gemini_cloud": {
            "name": "☁️ Google Gemini Cloud API (OpenAI-Compat 防爆保護)",
            "api_base": "https://generativelanguage.googleapis.com/v1beta/openai",
            "api_key": "",
            "model": "gemini-2.5-flash",
            "engine_label": "Google-Gemini-Cloud (Vanilla No-LoRA)",
            "max_tokens": 1280,
            "temperature": 0.5,
            "top_p": 0.95,
            "max_session_calls": 55,
            "max_session_tokens": 250000,
            "tcp_host": "127.0.0.1",
            "tcp_port": 18960,
        },
        "custom_openai_compatible": {
            "name": "🔧 Custom Enterprise / Self-Hosted OpenAI API",
            "api_base": "http://127.0.0.1:8080/v1",
            "api_key": "",
            "model": "auto",
            "engine_label": "Custom-OpenAI-API",
            "max_tokens": 1536,
            "temperature": 0.5,
            "top_p": 0.95,
            "max_session_calls": 60,
            "max_session_tokens": 250000,
            "tcp_host": "127.0.0.1",
            "tcp_port": 18960,
        },
    },
}


def load_bridge_profiles() -> Dict[str, Any]:
    PROFILES_PATH.parent.mkdir(parents=True, exist_ok=True)
    if PROFILES_PATH.exists():
        try:
            data = json.loads(PROFILES_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "profiles" in data:
                return data
        except Exception:
            pass
    save_bridge_profiles(DEFAULT_PROFILES_DATA)
    return json.loads(json.dumps(DEFAULT_PROFILES_DATA))


def save_bridge_profiles(data: Dict[str, Any]) -> None:
    PROFILES_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROFILES_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _build_ssl_context(insecure: bool = True) -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    if insecure:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _build_headers(api_key: str, stream: bool = False) -> Dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream" if stream else "application/json",
        "User-Agent": "DysonUniversalOpenAIBridge/2.1",
    }
    clean_key = (api_key or "").strip()
    if clean_key:
        if clean_key.lower().startswith("bearer "):
            clean_key = clean_key[7:].strip()
        headers["Authorization"] = f"Bearer {clean_key}"
        headers["api-key"] = clean_key  # Delta APIM / Azure OpenAI compatibility
        headers["x-goog-api-key"] = clean_key  # Google AI Studio Native REST compatibility
    return headers


def is_google_native_rest(api_base: str) -> bool:
    b = (api_base or "").strip().lower()
    return "generativelanguage.googleapis.com" in b and "/openai" not in b


def normalize_api_base(api_base: str) -> str:
    b = (api_base or "").strip().rstrip("/")
    if is_google_native_rest(b):
        # Strip trailing :generateContent or /models/... if user pasted full URL from AI Studio docs
        if "/models/" in b:
            b = b.split("/models/")[0]
        if b.endswith("/models"):
            b = b[: -len("/models")]
        if not b.endswith("/v1beta") and not b.endswith("/v1"):
            b = b + "/v1beta"
        return b
    if b.endswith("/chat/completions"):
        b = b[: -len("/chat/completions")]
    if b.endswith("/models"):
        b = b[: -len("/models")]
    if not b.endswith("/v1") and not b.endswith("/v1beta") and "/openai" not in b:
        b = b + "/v1"
    return b


def auto_detect_openai_model(
    api_base: str,
    api_key: str = "",
    preferred_model: str = "auto",
    insecure_ssl: bool = True,
) -> Tuple[str, List[str]]:
    """
    Queries `GET {api_base}/models` to discover available models on the endpoint.
    Supports both OpenAI-compatible `/v1/models` and Google AI Studio Native `/v1beta/models`.
    """
    norm_base = normalize_api_base(api_base)
    models_url = f"{norm_base}/models"
    ctx = _build_ssl_context(insecure_ssl)
    discovered: List[str] = []

    try:
        req = urllib.request.Request(models_url, headers=_build_headers(api_key, stream=False), method="GET")
        with urllib.request.urlopen(req, timeout=10.0, context=ctx) as resp:
            raw = json.loads(resp.read().decode("utf-8", errors="ignore"))
            if isinstance(raw, dict) and "models" in raw and isinstance(raw["models"], list):
                # Google AI Studio Native `/v1beta/models` response format
                for item in raw["models"]:
                    if not isinstance(item, dict):
                        continue
                    methods = item.get("supportedGenerationMethods") or []
                    if methods and "generateContent" not in methods:
                        continue
                    name = str(item.get("name", ""))
                    if name.startswith("models/"):
                        name = name[len("models/") :]
                    if name:
                        discovered.append(name)
            else:
                data_list = raw.get("data") if isinstance(raw, dict) else (raw if isinstance(raw, list) else [])
                if isinstance(data_list, list):
                    for item in data_list:
                        if isinstance(item, dict) and item.get("id"):
                            mid = str(item["id"])
                            if mid.startswith("models/"):
                                mid = mid[len("models/") :]
                            discovered.append(mid)
                        elif isinstance(item, str):
                            discovered.append(item)
    except Exception:
        pass

    skip_keywords = ("embed", "rerank", "bge-", "whisper", "tts", "asr")
    chat_candidates = [m for m in discovered if not any(k in m.lower() for k in skip_keywords)]

    pref = (preferred_model or "").strip()
    if pref and pref.lower() != "auto":
        for m in discovered:
            if m.lower() == pref.lower():
                return m, discovered
        for m in discovered:
            if pref.lower() in m.lower():
                return m, discovered
        return pref, discovered

    if chat_candidates:
        return chat_candidates[0], discovered
    if discovered:
        return discovered[0], discovered

    # Fallback probe: 1-token chat completion to read response['model']
    try:
        probe_payload = {
            "model": "default",
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 1,
            "stream": False,
        }
        req = urllib.request.Request(
            f"{norm_base}/chat/completions",
            data=json.dumps(probe_payload).encode("utf-8"),
            headers=_build_headers(api_key, stream=False),
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10.0, context=ctx) as resp:
            r_obj = json.loads(resp.read().decode("utf-8", errors="ignore"))
            if isinstance(r_obj, dict) and r_obj.get("model"):
                det = str(r_obj["model"])
                return det, [det]
    except Exception:
        pass

    return "unknown-openai-model", discovered


def stream_openai_chat_turn(
    api_base: str,
    api_key: str,
    model_id: str,
    user_prompt: str,
    system_inst: str,
    conversation_history: List[Dict[str, str]],
    max_tokens: int,
    temperature: float,
    top_p: float,
    on_token_callback: Callable[[str], None],
    insecure_ssl: bool = True,
) -> Tuple[str, int, str]:
    """
    Streams chat completion from any OpenAI-compatible `/v1/chat/completions` endpoint.
    Returns `(full_reply_text, completion_tokens, actual_model_name_from_response)`.
    Automatically falls back to non-streaming if SSE fails.
    """
    norm_base = normalize_api_base(api_base)
    ctx = _build_ssl_context(insecure_ssl)

    # --- Branch A: Google AI Studio Native REST API (`:streamGenerateContent?alt=sse` / `:generateContent`) ---
    if is_google_native_rest(norm_base):
        clean_model = (model_id or "gemini-2.5-flash").strip()
        if clean_model.startswith("models/"):
            clean_model = clean_model[len("models/") :]
        if not clean_model or clean_model in ("auto", "default", "unknown-openai-model"):
            clean_model = "gemini-2.5-flash"

        contents: List[Dict[str, Any]] = []
        if conversation_history:
            for m in conversation_history:
                r = "model" if m.get("role") == "assistant" else "user"
                contents.append({"role": r, "parts": [{"text": str(m.get("content", ""))}]})
        contents.append({"role": "user", "parts": [{"text": user_prompt}]})

        g_payload: Dict[str, Any] = {
            "system_instruction": {"parts": [{"text": system_inst}]},
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "topP": top_p,
                "maxOutputTokens": max(max_tokens, 1536),
                "thinkingConfig": {"thinkingBudget": 256},
            },
        }

        accumulated_text = ""
        completion_tokens = 0
        chunk_steps = 0
        stream_url = f"{norm_base}/models/{clean_model}:streamGenerateContent?alt=sse"
        sync_url = f"{norm_base}/models/{clean_model}:generateContent"

        try:
            req = urllib.request.Request(
                stream_url,
                data=json.dumps(g_payload).encode("utf-8"),
                headers=_build_headers(api_key, stream=True),
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=180.0, context=ctx) as resp:
                for raw_line in resp:
                    line = raw_line.decode("utf-8", errors="ignore").strip()
                    if not line or not line.startswith("data:"):
                        continue
                    data_str = line[5:].strip()
                    if not data_str or data_str == "[DONE]":
                        continue
                    try:
                        chunk = json.loads(data_str)
                    except Exception:
                        continue
                    usage_meta = chunk.get("usageMetadata") or {}
                    if usage_meta.get("candidatesTokenCount"):
                        completion_tokens = max(completion_tokens, int(usage_meta["candidatesTokenCount"]))
                    cands = chunk.get("candidates") or []
                    if cands:
                        parts = (cands[0].get("content") or {}).get("parts") or []
                        for p in parts:
                            piece = p.get("text")
                            if piece:
                                accumulated_text += str(piece)
                                chunk_steps += 1
                                on_token_callback(str(piece))
        except Exception:
            req_fb = urllib.request.Request(
                sync_url,
                data=json.dumps(g_payload).encode("utf-8"),
                headers=_build_headers(api_key, stream=False),
                method="POST",
            )
            with urllib.request.urlopen(req_fb, timeout=180.0, context=ctx) as resp_fb:
                body = json.loads(resp_fb.read().decode("utf-8", errors="ignore"))
                usage_meta = body.get("usageMetadata") or {}
                cands = body.get("candidates") or []
                if cands:
                    parts = (cands[0].get("content") or {}).get("parts") or []
                    for p in parts:
                        piece = p.get("text")
                        if piece:
                            accumulated_text += str(piece)
                            on_token_callback(str(piece))
                completion_tokens = int(
                    usage_meta.get("candidatesTokenCount") or max(1, len(accumulated_text) // 3)
                )

        if "<dyson_action>" in accumulated_text and "</dyson_action>" not in accumulated_text:
            accumulated_text += "\n</dyson_action>"
            on_token_callback("\n</dyson_action>")
        return accumulated_text, max(completion_tokens, chunk_steps, 1), clean_model

    # --- Branch B: Standard OpenAI-Compatible `/chat/completions` ---
    url = f"{norm_base}/chat/completions"

    messages: List[Dict[str, str]] = [{"role": "system", "content": system_inst}]
    if conversation_history:
        messages.extend(conversation_history)
    messages.append({"role": "user", "content": user_prompt})

    payload: Dict[str, Any] = {
        "model": model_id,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "top_p": top_p,
        "stop": ["</dyson_action>", "<|im_end|>", "<|endoftext|>"],
        "stream": True,
    }

    accumulated_text = ""
    completion_tokens = 0
    chunk_steps = 0
    response_model = model_id

    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=_build_headers(api_key, stream=True),
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=180.0, context=ctx) as resp:
            ctype = (resp.headers.get("Content-Type") or "").lower()
            if "application/json" in ctype and "event-stream" not in ctype:
                body = json.loads(resp.read().decode("utf-8", errors="ignore"))
                if body.get("model"):
                    response_model = str(body["model"])
                choices = body.get("choices") or []
                if choices:
                    msg = choices[0].get("message") or {}
                    content = msg.get("content") or choices[0].get("text") or ""
                    if content:
                        accumulated_text = str(content)
                        on_token_callback(accumulated_text)
                usage = body.get("usage") or {}
                completion_tokens = int(usage.get("completion_tokens") or max(1, len(accumulated_text) // 3))
            else:
                for raw_line in resp:
                    line = raw_line.decode("utf-8", errors="ignore").strip()
                    if not line or not line.startswith("data:"):
                        continue
                    data_str = line[5:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                    except Exception:
                        continue
                    if chunk.get("model"):
                        response_model = str(chunk["model"])
                    if chunk.get("usage"):
                        completion_tokens = max(
                            completion_tokens,
                            int(chunk["usage"].get("completion_tokens", 0)),
                        )
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    content = delta.get("content")
                    if content is None and choices[0].get("message"):
                        content = choices[0]["message"].get("content")
                    if content:
                        piece = str(content)
                        accumulated_text += piece
                        chunk_steps += 1
                        on_token_callback(piece)
    except Exception:
        # Fallback to non-streaming without `stop` array if corporate gateway rejects stream/stop
        payload["stream"] = False
        payload.pop("stop", None)
        req_fb = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=_build_headers(api_key, stream=False),
            method="POST",
        )
        with urllib.request.urlopen(req_fb, timeout=180.0, context=ctx) as resp_fb:
            body = json.loads(resp_fb.read().decode("utf-8", errors="ignore"))
            if body.get("model"):
                response_model = str(body["model"])
            choices = body.get("choices") or []
            if choices:
                msg = choices[0].get("message") or {}
                content = msg.get("content") or ""
                if content:
                    accumulated_text = str(content)
                    on_token_callback(accumulated_text)
            usage = body.get("usage") or {}
            completion_tokens = int(usage.get("completion_tokens") or max(1, len(accumulated_text) // 3))

    if "<dyson_action>" in accumulated_text and "</dyson_action>" not in accumulated_text:
        accumulated_text += "\n</dyson_action>"
        on_token_callback("\n</dyson_action>")

    return accumulated_text, max(completion_tokens, chunk_steps, 1), response_model


class UniversalOpenAIBridgeWorker:
    """Background worker managing the TCP Lockstep Client & OpenAI-compatible inference loop."""

    def __init__(
        self,
        tcp_host: str,
        tcp_port: int,
        api_base: str,
        api_key: str,
        model_arg: str,
        engine_label: str,
        max_tokens: int,
        temp: float,
        top_p: float,
        max_session_calls: int = 60,
        max_session_tokens: int = 250000,
        ui_event_queue: Optional["queue.Queue[Dict[str, Any]]"] = None,
    ) -> None:
        self.tcp_host = tcp_host
        self.tcp_port = int(tcp_port)
        self.api_base = normalize_api_base(api_base)
        self.api_key = api_key
        self.model_arg = model_arg
        self.engine_label = engine_label
        self.max_tokens = int(max_tokens)
        self.temp = float(temp)
        self.top_p = float(top_p)
        self.max_session_calls = max(1, int(max_session_calls))
        self.max_session_tokens = max(1000, int(max_session_tokens))
        self.ui_queue = ui_event_queue

        self.detected_model = model_arg if (model_arg and model_arg != "auto") else "auto-detecting..."
        self.discovered_models: List[str] = []
        self.running = False
        self.client: Optional[DysonTcpSyncClient] = None
        self.thread: Optional[threading.Thread] = None
        self.history: List[Dict[str, str]] = []
        self.session_calls_used = 0
        self.session_tokens_used = 0

    def _emit_ui(self, evt_type: str, **kwargs: Any) -> None:
        if self.ui_queue is not None:
            pkt = {"type": evt_type}
            pkt.update(kwargs)
            self.ui_queue.put(pkt)

    def start(self) -> None:
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.running = False
        if self.client is not None:
            try:
                self.client.stop()
            except Exception:
                pass
        self._emit_ui("status", text="⏹️ Bridge 已停止", connected=False, model=self.detected_model)

    def clear_history(self) -> None:
        self.history.clear()
        self._emit_ui("log", text="\n🧹 [History Cleared] 已清空 Bridge 對話滑動記憶視窗。\n")

    def _run_loop(self) -> None:
        self._emit_ui("log", text=f"🔍 正在探測端點 `{self.api_base}/models` ...\n")
        det_model, all_models = auto_detect_openai_model(
            self.api_base, api_key=self.api_key, preferred_model=self.model_arg
        )
        self.detected_model = det_model
        self.discovered_models = all_models
        if all_models:
            self._emit_ui("models_discovered", models=all_models, selected=det_model)
            self._emit_ui("log", text=f"📋 偵測到伺服器共有 {len(all_models)} 個模型: {all_models}\n")
        self._emit_ui(
            "log",
            text=f"🤖 已自動選取推論模型: `{self.detected_model}` | 標記模式: `{self.engine_label}`\n",
        )

        system_inst = (
            "你是戴森球星系能源正循環與深空自癒總控 AI (Kuro-Dyson-Core)。"
            "你的任務是根據每個同步 Tick 的熱力學遙測，維持電網供電率 η >= 100%、解除氫氣/精煉油雙輸出死鎖、"
            "抵抗微隕石沙塵暴與太陽閃焰單粒子翻轉 (SEU)，並輸出 `<dyson_action>{...}</dyson_action>` 動態調整系統參數。"
        )

        self.client = DysonTcpSyncClient(host=self.tcp_host, port=self.tcp_port)
        self.client.start()
        self._emit_ui(
            "status",
            text=f"🟡 等待戴森球模擬器連線 ({self.tcp_host}:{self.tcp_port})...",
            connected=False,
            model=self.detected_model,
        )

        while self.running:
            try:
                pkt = self.client.inbound_queue.get(timeout=0.4)
            except queue.Empty:
                continue

            ptype = pkt.get("type", "")
            if ptype == "bridge_connected":
                re_model, re_list = auto_detect_openai_model(
                    self.api_base, api_key=self.api_key, preferred_model=self.model_arg
                )
                if re_model and re_model != "unknown-openai-model":
                    self.detected_model = re_model
                if re_list:
                    self._emit_ui("models_discovered", models=re_list, selected=self.detected_model)

                self.client.send_packet({
                    "type": "bridge_hello",
                    "model_id": self.detected_model,
                    "engine_mode": self.engine_label,
                    "api_base": self.api_base,
                })
                self._emit_ui(
                    "status",
                    text=f"🟢 已連線模擬器 ({pkt.get('target')}) | 模型: {self.detected_model}",
                    connected=True,
                    model=self.detected_model,
                )
                self._emit_ui(
                    "log",
                    text=(
                        f"\n🟢 [TCP Lockstep Connected] 已連上戴森球模擬器 ({pkt.get('target')})！\n"
                        f"📨 已發送 `bridge_hello` 握手標籤 -> Model=`{self.detected_model}`, Mode=`{self.engine_label}`\n"
                    ),
                )
            elif ptype == "bridge_disconnected":
                self._emit_ui(
                    "status",
                    text=f"🟡 模擬器斷線，等待重連 ({self.tcp_host}:{self.tcp_port})...",
                    connected=False,
                    model=self.detected_model,
                )
                self._emit_ui("log", text="\n🟡 [TCP Disconnected] 模擬器連線中斷，自動等待重連...\n")
            elif ptype == "tick_state_sync":
                tick = pkt.get("tick", 0)
                stage = pkt.get("stage", 1)
                prompt = pkt.get("prompt", "")
                is_compact = bool(pkt.get("compact_mode", True))
                eval_prev = pkt.get("eval_prev_window") or {}

                mode_tag = "⚡Compact" if is_compact else "📝Full-Deep"
                self._emit_ui(
                    "log",
                    text=(
                        f"\n==================== 🛰️ [Tick #{tick} | Stage {stage} | {mode_tag}] ====================\n"
                        f"• 前窗評估: {eval_prev.get('consolidation_mode', 'N/A')} (ΔP={eval_prev.get('delta_gen_mw', 0):+.1f} MW)\n"
                        f"• 正在呼叫 `{self.detected_model}` ({self.api_base})...\n>> "
                    ),
                )
                t0 = time.time()

                def _on_tok(piece: str) -> None:
                    self._emit_ui("token", piece=piece)
                    if self.client is not None:
                        self.client.send_packet({
                            "type": "ai_token_stream",
                            "piece": piece,
                            "entropy": 0.0,
                            "selected_experts": [],
                        })

                try:
                    if self.session_calls_used >= self.max_session_calls or self.session_tokens_used >= self.max_session_tokens:
                        warn_msg = (
                            f"\n🛑 [防爆保險絲觸發 Circuit Breaker] 已達單場安全上限 "
                            f"(Calls: {self.session_calls_used}/{self.max_session_calls}, "
                            f"Tokens: {self.session_tokens_used:,}/{self.max_session_tokens:,})！自動跳過雲端呼叫以保護帳單！\n"
                        )
                        self._emit_ui("log", text=warn_msg)
                        if self.client is not None:
                            self.client.send_packet({
                                "type": "ai_action_complete",
                                "tick": tick,
                                "raw_text": '<dyson_action>{"next_wake_ticks": 500}</dyson_action>',
                                "model_id": self.detected_model,
                                "engine_mode": self.engine_label,
                                "api_base": self.api_base,
                            })
                        continue

                    is_genesis_turn = "new_stage_genesis" in prompt
                    if is_genesis_turn:
                        turn_max_toks = max(self.max_tokens, 1536)
                        ctx_hist = self.history[-2:]
                    elif is_compact:
                        # Avoid clamping to 640 so Thinking models (e.g. Gemini 3.7 Flash) don't truncate <dyson_action>
                        turn_max_toks = max(self.max_tokens, 1280)
                        ctx_hist = self.history[-2:]
                    else:
                        turn_max_toks = max(self.max_tokens, 1536)
                        ctx_hist = self.history[-4:]

                    est_in_toks = max(1, (len(system_inst) + len(prompt) + sum(len(m.get("content", "")) for m in ctx_hist)) // 3)
                    full_reply, total_toks, actual_resp_model = stream_openai_chat_turn(
                        api_base=self.api_base,
                        api_key=self.api_key,
                        model_id=self.detected_model,
                        user_prompt=prompt,
                        system_inst=system_inst,
                        conversation_history=ctx_hist,
                        max_tokens=turn_max_toks,
                        temperature=self.temp,
                        top_p=self.top_p,
                        on_token_callback=_on_tok,
                    )
                    if actual_resp_model and actual_resp_model not in ("default", "unknown-openai-model"):
                        self.detected_model = actual_resp_model

                    self.session_calls_used += 1
                    self.session_tokens_used += (est_in_toks + total_toks)
                    elapsed = max(0.001, time.time() - t0)
                    tps = total_toks / elapsed
                    short_user = f"[Tick #{tick} Telemetry]" if is_compact else prompt
                    self.history.append({"role": "user", "content": short_user})
                    self.history.append({"role": "assistant", "content": full_reply})

                    if self.client is not None:
                        self.client.send_packet({
                            "type": "ai_action_complete",
                            "tick": tick,
                            "raw_text": full_reply,
                            "tokens": total_toks,
                            "elapsed_s": elapsed,
                            "model_id": self.detected_model,
                            "engine_mode": self.engine_label,
                            "api_base": self.api_base,
                        })
                    self._emit_ui(
                        "turn_done",
                        tick=tick,
                        tokens=total_toks,
                        session_calls=self.session_calls_used,
                        session_tokens=self.session_tokens_used,
                        elapsed=elapsed,
                        tps=tps,
                        model=self.detected_model,
                    )
                    self._emit_ui(
                        "log",
                        text=(
                            f"\n✅ [Tick #{tick} Done | {self.detected_model}] Out:{total_toks} toks ({tps:.1f} tok/s) | "
                            f"累計: {self.session_calls_used}/{self.max_session_calls} 輪, ~{self.session_tokens_used:,}/{self.max_session_tokens:,} toks -> 已回傳模擬器！\n"
                        ),
                    )
                except Exception as e:
                    self._emit_ui("log", text=f"\n❌ [Tick #{tick} API Error]: {e}\n")
                    if self.client is not None:
                        self.client.send_packet({
                            "type": "ai_action_complete",
                            "tick": tick,
                            "raw_text": "",
                            "model_id": self.detected_model,
                            "engine_mode": self.engine_label,
                            "api_base": self.api_base,
                        })


def launch_universal_bridge_gui() -> None:
    from PyQt6.QtCore import Qt, QTimer
    from PyQt6.QtGui import QFont, QTextCursor
    from PyQt6.QtWidgets import (
        QApplication,
        QComboBox,
        QDoubleSpinBox,
        QFormLayout,
        QGroupBox,
        QHBoxLayout,
        QInputDialog,
        QLabel,
        QLineEdit,
        QMainWindow,
        QMessageBox,
        QPlainTextEdit,
        QPushButton,
        QSpinBox,
        QVBoxLayout,
        QWidget,
    )

    class UniversalOpenAIBridgeGUI(QMainWindow):
        def __init__(self) -> None:
            super().__init__()
            self.setWindowTitle(
                "🌐 Dyson Universal OpenAI-Compatible API Bridge (公司 Qwen / 外部 API 對照測試控制台)"
            )
            self.resize(980, 760)
            self.setStyleSheet(
                """
                QMainWindow, QWidget { background-color: #0b1120; color: #e2e8f0; font-family: 'Segoe UI', 'Noto Sans CJK TC', sans-serif; }
                QGroupBox { border: 1px solid #1e293b; border-radius: 6px; margin-top: 8px; padding-top: 10px; font-weight: bold; color: #38bdf8; }
                QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }
                QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit {
                    background-color: #0f172a; color: #f8fafc; border: 1px solid #334155; border-radius: 4px; padding: 4px 6px;
                }
                QPushButton {
                    background-color: #1e293b; color: #f8fafc; border: 1px solid #475569; border-radius: 5px; padding: 6px 12px; font-weight: bold;
                }
                QPushButton:hover { background-color: #334155; }
                """
            )

            self.profiles_data = load_bridge_profiles()
            self.worker: Optional[UniversalOpenAIBridgeWorker] = None
            self.ui_queue: "queue.Queue[Dict[str, Any]]" = queue.Queue()
            self.total_turns = 0

            central = QWidget()
            self.setCentralWidget(central)
            root_v = QVBoxLayout(central)

            # 1. Profile & API Key Box
            prof_box = QGroupBox("🗂️ 1. 內部連線 Profile 與 API Key 持久化管理 (configs/openai_bridge_profiles.json)")
            prof_form = QFormLayout(prof_box)

            row_prof = QHBoxLayout()
            self.cmb_profile = QComboBox()
            self.cmb_profile.currentIndexChanged.connect(self._on_profile_selected)
            row_prof.addWidget(self.cmb_profile, stretch=1)

            btn_save_prof = QPushButton("💾 儲存當前設定與 API Key")
            btn_save_prof.setStyleSheet("background-color: #0284c7; color: white;")
            btn_save_prof.clicked.connect(self._save_current_profile)
            row_prof.addWidget(btn_save_prof)

            btn_new_prof = QPushButton("➕ 新增自訂 Profile")
            btn_new_prof.setStyleSheet("background-color: #4f46e5; color: white;")
            btn_new_prof.clicked.connect(self._create_new_profile)
            row_prof.addWidget(btn_new_prof)
            prof_form.addRow("選擇 Profile:", row_prof)

            self.edt_api_base = QLineEdit()
            self.edt_api_base.setPlaceholderText("例如: https://llmgateway.deltaww.com/v1 或 http://192.168.50.67:8000/v1")
            prof_form.addRow("API Base URL:", self.edt_api_base)

            row_key = QHBoxLayout()
            self.edt_api_key = QLineEdit()
            self.edt_api_key.setEchoMode(QLineEdit.EchoMode.Password)
            self.edt_api_key.setPlaceholderText("輸入公司 Qwen Gateway 或 OpenAI API Key (將自動存入 Profile JSON，免重複輸入)")
            row_key.addWidget(self.edt_api_key, stretch=1)

            self.btn_toggle_key = QPushButton("👁️ 顯示 Key")
            self.btn_toggle_key.setCheckable(True)
            self.btn_toggle_key.toggled.connect(self._toggle_api_key_visibility)
            row_key.addWidget(self.btn_toggle_key)
            prof_form.addRow("API Key (密鑰):", row_key)

            row_model = QHBoxLayout()
            self.cmb_model = QComboBox()
            self.cmb_model.setEditable(True)
            self.cmb_model.addItem("auto")
            row_model.addWidget(self.cmb_model, stretch=1)

            btn_probe_models = QPushButton("🔍 探測 /v1/models 並自動選取")
            btn_probe_models.setStyleSheet("background-color: #0d9488; color: white;")
            btn_probe_models.clicked.connect(self._probe_endpoint_models)
            row_model.addWidget(btn_probe_models)

            btn_test_chat = QPushButton("🧪 測試 1-Token 推論連通")
            btn_test_chat.setStyleSheet("background-color: #d97706; color: white;")
            btn_test_chat.clicked.connect(self._test_one_token_chat)
            row_model.addWidget(btn_test_chat)
            prof_form.addRow("推論 Model ID:", row_model)

            self.edt_engine_label = QLineEdit()
            self.edt_engine_label.setPlaceholderText("例如: Delta-LLM-Gateway (Vanilla No-LoRA) — 將寫入 Session 與 stage_list.json")
            prof_form.addRow("Session 標記標籤:", self.edt_engine_label)

            row_params = QHBoxLayout()
            row_params.addWidget(QLabel("Max Tokens:"))
            self.spn_max_tokens = QSpinBox()
            self.spn_max_tokens.setRange(128, 8192)
            self.spn_max_tokens.setSingleStep(128)
            self.spn_max_tokens.setValue(1536)
            row_params.addWidget(self.spn_max_tokens)

            row_params.addWidget(QLabel("Temp:"))
            self.spn_temp = QDoubleSpinBox()
            self.spn_temp.setRange(0.0, 2.0)
            self.spn_temp.setSingleStep(0.05)
            self.spn_temp.setValue(0.5)
            row_params.addWidget(self.spn_temp)

            row_params.addWidget(QLabel("Top-P:"))
            self.spn_top_p = QDoubleSpinBox()
            self.spn_top_p.setRange(0.1, 1.0)
            self.spn_top_p.setSingleStep(0.05)
            self.spn_top_p.setValue(0.95)
            row_params.addWidget(self.spn_top_p)

            row_params.addWidget(QLabel("🛡️最大輪數:"))
            self.spn_max_calls = QSpinBox()
            self.spn_max_calls.setRange(5, 500)
            self.spn_max_calls.setValue(55)
            self.spn_max_calls.setToolTip("單場防爆上限：超過此呼叫次數自動熔斷停止呼叫雲端 API")
            row_params.addWidget(self.spn_max_calls)

            row_params.addWidget(QLabel("🛡️Token上限(K):"))
            self.spn_max_budget_k = QSpinBox()
            self.spn_max_budget_k.setRange(10, 5000)
            self.spn_max_budget_k.setSingleStep(50)
            self.spn_max_budget_k.setValue(250)
            self.spn_max_budget_k.setToolTip("單場總 Token 預算上限 (單位: K Tokens)")
            row_params.addWidget(self.spn_max_budget_k)

            row_params.addWidget(QLabel("Simulator TCP:"))
            self.edt_tcp_host = QLineEdit("127.0.0.1")
            self.edt_tcp_host.setFixedWidth(95)
            row_params.addWidget(self.edt_tcp_host)
            self.spn_tcp_port = QSpinBox()
            self.spn_tcp_port.setRange(1024, 65535)
            self.spn_tcp_port.setValue(DEFAULT_TCP_PORT)
            row_params.addWidget(self.spn_tcp_port)
            prof_form.addRow("推論與防爆參數:", row_params)

            root_v.addWidget(prof_box)

            # 2. Bridge Start/Stop & Status Bar
            ctrl_box = QGroupBox("🚀 2. 雙向 Lockstep 橋接控制與即時模型標記狀態")
            ctrl_v = QVBoxLayout(ctrl_box)

            btn_row = QHBoxLayout()
            self.btn_start = QPushButton("🚀 啟動萬用 Bridge 並連線戴森球模擬器")
            self.btn_start.setStyleSheet("background-color: #059669; color: white; font-size: 13px; padding: 8px 16px;")
            self.btn_start.clicked.connect(self._start_bridge)
            btn_row.addWidget(self.btn_start, stretch=2)

            self.btn_stop = QPushButton("⏹️ 停止 Bridge")
            self.btn_stop.setStyleSheet("background-color: #be123c; color: white; font-size: 13px; padding: 8px 16px;")
            self.btn_stop.setEnabled(False)
            self.btn_stop.clicked.connect(self._stop_bridge)
            btn_row.addWidget(self.btn_stop, stretch=1)

            btn_clear_mem = QPushButton("🧹 清空對話記憶")
            btn_clear_mem.clicked.connect(self._clear_worker_history)
            btn_row.addWidget(btn_clear_mem)
            ctrl_v.addLayout(btn_row)

            self.lbl_status = QLabel("⚪ 狀態: 尚未啟動 (選好 Profile 後點擊『🚀 啟動萬用 Bridge』即可自動連線模擬器)")
            self.lbl_status.setStyleSheet("color: #facc15; font-weight: bold; font-size: 12px;")
            ctrl_v.addWidget(self.lbl_status)

            self.lbl_model_tag = QLabel("🤖 自動偵測模型標記: (等待探測)")
            self.lbl_model_tag.setStyleSheet("color: #38bdf8; font-weight: bold; font-size: 12px;")
            ctrl_v.addWidget(self.lbl_model_tag)

            root_v.addWidget(ctrl_box)

            # 3. Live Streaming Log
            log_box = QGroupBox("📡 3. 即時 OpenAI API 推論串流與 Lockstep 同步日誌")
            log_v = QVBoxLayout(log_box)
            self.txt_log = QPlainTextEdit()
            self.txt_log.setReadOnly(True)
            self.txt_log.setFont(QFont("Monospace", 10))
            log_v.addWidget(self.txt_log)
            root_v.addWidget(log_box, stretch=1)

            self._populate_profile_combo()

            self.timer = QTimer(self)
            self.timer.timeout.connect(self._poll_ui_events)
            self.timer.start(40)

        def _populate_profile_combo(self) -> None:
            self.cmb_profile.blockSignals(True)
            self.cmb_profile.clear()
            profs = self.profiles_data.get("profiles", {})
            active_key = self.profiles_data.get("active_profile", "delta_qwen_gateway")
            sel_idx = 0
            for idx, (k, v) in enumerate(profs.items()):
                disp = f"{v.get('name', k)} [{k}]"
                self.cmb_profile.addItem(disp, userData=k)
                if k == active_key:
                    sel_idx = idx
            self.cmb_profile.setCurrentIndex(sel_idx)
            self.cmb_profile.blockSignals(False)
            self._load_profile_into_fields(active_key)

        def _on_profile_selected(self) -> None:
            pkey = self.cmb_profile.currentData()
            if pkey:
                self.profiles_data["active_profile"] = pkey
                self._load_profile_into_fields(str(pkey))

        def _load_profile_into_fields(self, pkey: str) -> None:
            p = self.profiles_data.get("profiles", {}).get(pkey, {})
            self.edt_api_base.setText(str(p.get("api_base", "https://llmgateway.deltaww.com/v1")))
            self.edt_api_key.setText(str(p.get("api_key", "")))
            m_val = str(p.get("model", "auto"))
            if self.cmb_model.findText(m_val) < 0:
                self.cmb_model.insertItem(0, m_val)
            self.cmb_model.setCurrentText(m_val)
            self.edt_engine_label.setText(str(p.get("engine_label", "OpenAI-API (Vanilla No-LoRA)")))
            self.spn_max_tokens.setValue(int(p.get("max_tokens", 1536)))
            self.spn_temp.setValue(float(p.get("temperature", 0.5)))
            self.spn_top_p.setValue(float(p.get("top_p", 0.95)))
            self.spn_max_calls.setValue(int(p.get("max_session_calls", 55)))
            self.spn_max_budget_k.setValue(max(10, int(p.get("max_session_tokens", 250000)) // 1000))
            self.edt_tcp_host.setText(str(p.get("tcp_host", "127.0.0.1")))
            self.spn_tcp_port.setValue(int(p.get("tcp_port", DEFAULT_TCP_PORT)))

        def _toggle_api_key_visibility(self, checked: bool) -> None:
            if checked:
                self.edt_api_key.setEchoMode(QLineEdit.EchoMode.Normal)
                self.btn_toggle_key.setText("🙈 隱藏 Key")
            else:
                self.edt_api_key.setEchoMode(QLineEdit.EchoMode.Password)
                self.btn_toggle_key.setText("👁️ 顯示 Key")

        def _save_current_profile(self) -> None:
            pkey = str(self.cmb_profile.currentData() or "custom_openai_compatible")
            profs = self.profiles_data.setdefault("profiles", {})
            existing = profs.get(pkey, {})
            profs[pkey] = {
                "name": existing.get("name", f"Custom Profile ({pkey})"),
                "api_base": self.edt_api_base.text().strip(),
                "api_key": self.edt_api_key.text().strip(),
                "model": self.cmb_model.currentText().strip() or "auto",
                "engine_label": self.edt_engine_label.text().strip() or "OpenAI-API (Vanilla No-LoRA)",
                "max_tokens": int(self.spn_max_tokens.value()),
                "temperature": float(self.spn_temp.value()),
                "top_p": float(self.spn_top_p.value()),
                "max_session_calls": int(self.spn_max_calls.value()),
                "max_session_tokens": int(self.spn_max_budget_k.value()) * 1000,
                "tcp_host": self.edt_tcp_host.text().strip() or "127.0.0.1",
                "tcp_port": int(self.spn_tcp_port.value()),
            }
            self.profiles_data["active_profile"] = pkey
            save_bridge_profiles(self.profiles_data)
            self._append_log(f"💾 已將設定與 API Key 儲存至 Profile `{pkey}` ({PROFILES_PATH.name})！\n")

        def _create_new_profile(self) -> None:
            pid, ok1 = QInputDialog.getText(self, "新增 Profile", "請輸入新 Profile 代號 (例如 delta_qwen_72b):")
            if not ok1 or not pid.strip():
                return
            pid = pid.strip()
            pname, ok2 = QInputDialog.getText(self, "Profile 顯示名稱", "請輸入顯示名稱:", text=f"🏢 {pid}")
            if not ok2:
                return
            self.profiles_data.setdefault("profiles", {})[pid] = {
                "name": pname.strip() or pid,
                "api_base": self.edt_api_base.text().strip(),
                "api_key": self.edt_api_key.text().strip(),
                "model": self.cmb_model.currentText().strip() or "auto",
                "engine_label": self.edt_engine_label.text().strip() or f"{pid} (Vanilla No-LoRA)",
                "max_tokens": int(self.spn_max_tokens.value()),
                "temperature": float(self.spn_temp.value()),
                "top_p": float(self.spn_top_p.value()),
                "tcp_host": self.edt_tcp_host.text().strip() or "127.0.0.1",
                "tcp_port": int(self.spn_tcp_port.value()),
            }
            self.profiles_data["active_profile"] = pid
            save_bridge_profiles(self.profiles_data)
            self._populate_profile_combo()
            self._append_log(f"➕ 已新增並切換至 Profile `{pid}`！\n")

        def _probe_endpoint_models(self) -> None:
            api_b = self.edt_api_base.text().strip()
            api_k = self.edt_api_key.text().strip()
            pref_m = self.cmb_model.currentText().strip() or "auto"
            self._append_log(f"\n🔍 正在查詢 `{normalize_api_base(api_b)}/models` ...\n")
            QApplication.processEvents()
            det, models = auto_detect_openai_model(api_b, api_key=api_k, preferred_model=pref_m)
            self.cmb_model.clear()
            self.cmb_model.addItem("auto")
            for m in models:
                self.cmb_model.addItem(m)
            if det and det != "unknown-openai-model":
                if self.cmb_model.findText(det) < 0:
                    self.cmb_model.addItem(det)
                self.cmb_model.setCurrentText(det)
            self.lbl_model_tag.setText(
                f"🤖 自動偵測模型標記: {det} [{self.edt_engine_label.text().strip()}] (共發現 {len(models)} 個模型)"
            )
            self._append_log(f"✅ 探測完成！伺服器模型清單: {models} -> 已選取: `{det}`\n")

        def _test_one_token_chat(self) -> None:
            api_b = self.edt_api_base.text().strip()
            api_k = self.edt_api_key.text().strip()
            pref_m = self.cmb_model.currentText().strip() or "auto"
            det, _ = auto_detect_openai_model(api_b, api_key=api_k, preferred_model=pref_m)
            self._append_log(f"\n🧪 正在發送測試請求至 `{normalize_api_base(api_b)}/chat/completions` (Model=`{det}`)...\n")
            QApplication.processEvents()
            t0 = time.time()
            try:
                reply, toks, actual_m = stream_openai_chat_turn(
                    api_base=api_b,
                    api_key=api_k,
                    model_id=det,
                    user_prompt="請回覆 OK 兩個字。",
                    system_inst="You are a helpful assistant.",
                    conversation_history=[],
                    max_tokens=16,
                    temperature=0.1,
                    top_p=0.95,
                    on_token_callback=lambda p: None,
                )
                dt = time.time() - t0
                self.lbl_model_tag.setText(f"🤖 驗證成功模型: {actual_m} [{self.edt_engine_label.text().strip()}]")
                self._append_log(f"✅ API 連通測試成功 ({dt:.2f}s)！回傳模型=`{actual_m}` | 內容: `{reply.strip()}`\n")
            except Exception as e:
                self._append_log(f"❌ API 連通測試失敗: {e}\n")

        def _start_bridge(self) -> None:
            self._save_current_profile()
            if self.worker is not None:
                self.worker.stop()
            self.worker = UniversalOpenAIBridgeWorker(
                tcp_host=self.edt_tcp_host.text().strip() or "127.0.0.1",
                tcp_port=int(self.spn_tcp_port.value()),
                api_base=self.edt_api_base.text().strip(),
                api_key=self.edt_api_key.text().strip(),
                model_arg=self.cmb_model.currentText().strip() or "auto",
                engine_label=self.edt_engine_label.text().strip() or "OpenAI-API (Vanilla No-LoRA)",
                max_tokens=int(self.spn_max_tokens.value()),
                temp=float(self.spn_temp.value()),
                top_p=float(self.spn_top_p.value()),
                max_session_calls=int(self.spn_max_calls.value()),
                max_session_tokens=int(self.spn_max_budget_k.value()) * 1000,
                ui_event_queue=self.ui_queue,
            )
            self.worker.start()
            self.btn_start.setEnabled(False)
            self.btn_stop.setEnabled(True)

        def _stop_bridge(self) -> None:
            if self.worker is not None:
                self.worker.stop()
                self.worker = None
            self.btn_start.setEnabled(True)
            self.btn_stop.setEnabled(False)

        def _clear_worker_history(self) -> None:
            if self.worker is not None:
                self.worker.clear_history()
            else:
                self._append_log("\n🧹 對話記憶已清空。\n")

        def _append_log(self, text: str) -> None:
            cursor = self.txt_log.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            cursor.insertText(text)
            self.txt_log.setTextCursor(cursor)
            self.txt_log.ensureCursorVisible()

        def _poll_ui_events(self) -> None:
            while not self.ui_queue.empty():
                evt = self.ui_queue.get_nowait()
                etype = evt.get("type", "")
                if etype == "log":
                    self._append_log(str(evt.get("text", "")))
                elif etype == "token":
                    self._append_log(str(evt.get("piece", "")))
                elif etype == "status":
                    txt = str(evt.get("text", ""))
                    conn = bool(evt.get("connected", False))
                    mdl = str(evt.get("model", ""))
                    self.lbl_status.setText(txt)
                    self.lbl_status.setStyleSheet(
                        f"color: {'#34d399' if conn else '#facc15'}; font-weight: bold; font-size: 12px;"
                    )
                    self.lbl_model_tag.setText(
                        f"🤖 當前推論模型標記 (自動寫入 Session & stage_list): {mdl} [{self.edt_engine_label.text().strip()}]"
                    )
                elif etype == "models_discovered":
                    models = evt.get("models") or []
                    sel = str(evt.get("selected") or "auto")
                    self.cmb_model.blockSignals(True)
                    self.cmb_model.clear()
                    self.cmb_model.addItem("auto")
                    for m in models:
                        self.cmb_model.addItem(str(m))
                    if sel:
                        if self.cmb_model.findText(sel) < 0:
                            self.cmb_model.addItem(sel)
                        self.cmb_model.setCurrentText(sel)
                    self.cmb_model.blockSignals(False)
                elif etype == "turn_done":
                    self.total_turns = int(evt.get("session_calls", self.total_turns + 1))
                    tot_toks = int(evt.get("session_tokens", 0))
                    mdl = evt.get("model", "")
                    tps = float(evt.get("tps", 0.0))
                    self.lbl_model_tag.setText(
                        f"🤖 模型: {mdl} [{self.edt_engine_label.text().strip()}] | "
                        f"🛡️ 累計: {self.total_turns}/{self.spn_max_calls.value()} 輪 (~{tot_toks:,} toks, {tps:.1f} tok/s)"
                    )

    app = QApplication(sys.argv)
    win = UniversalOpenAIBridgeGUI()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Universal OpenAI-Compatible API Bridge (+PyQt6 GUI) for rust_dysonsphere_sim"
    )
    ap.add_argument("--nogui", action="store_true", help="Run in headless CLI mode instead of launching PyQt6 GUI")
    ap.add_argument("--profile", default="", help="Load a specific profile key from configs/openai_bridge_profiles.json")
    ap.add_argument("--host", default=DEFAULT_TCP_HOST)
    ap.add_argument("--port", type=int, default=DEFAULT_TCP_PORT)
    ap.add_argument("--api-base", default="")
    ap.add_argument("--api-key", default="")
    ap.add_argument("--model", default="auto")
    ap.add_argument("--engine-label", default="")
    ap.add_argument("--max-tokens", type=int, default=1536)
    ap.add_argument("--temp", type=float, default=0.5)
    ap.add_argument("--top-p", type=float, default=0.95)
    args = ap.parse_args()

    if not args.nogui and (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        launch_universal_bridge_gui()
    else:
        profs_data = load_bridge_profiles()
        pkey = args.profile or profs_data.get("active_profile", "delta_qwen_gateway")
        p_cfg = profs_data.get("profiles", {}).get(pkey, {})
        api_base = args.api_base or p_cfg.get("api_base", "http://192.168.50.67:8000/v1")
        api_key = args.api_key or p_cfg.get("api_key", "") or os.environ.get("OPENAI_API_KEY", "")
        model_arg = args.model if args.model != "auto" else p_cfg.get("model", "auto")
        eng_label = args.engine_label or p_cfg.get("engine_label", "OpenAI-API (Vanilla No-LoRA)")

        worker = UniversalOpenAIBridgeWorker(
            tcp_host=args.host or p_cfg.get("tcp_host", DEFAULT_TCP_HOST),
            tcp_port=args.port or int(p_cfg.get("tcp_port", DEFAULT_TCP_PORT)),
            api_base=api_base,
            api_key=api_key,
            model_arg=model_arg,
            engine_label=eng_label,
            max_tokens=args.max_tokens or int(p_cfg.get("max_tokens", 1536)),
            temp=args.temp or float(p_cfg.get("temperature", 0.5)),
            top_p=args.top_p or float(p_cfg.get("top_p", 0.95)),
            ui_event_queue=queue.Queue(),
        )
        worker.start()
        try:
            while True:
                evt = worker.ui_queue.get()
                if evt.get("type") in ("log", "token"):
                    sys.stdout.write(str(evt.get("text") or evt.get("piece") or ""))
                    sys.stdout.flush()
        except KeyboardInterrupt:
            worker.stop()
