#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import mimetypes
import hmac
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_KEY_FILE = PROJECT_ROOT.parent / "API KEY.rtf"
DEFAULT_RATE_LIMIT_FILE = Path(
    os.getenv("DEEPSEEK_RATE_LIMIT_FILE", "").strip()
    or str(Path(tempfile.gettempdir()) / "mysticstrategy-deepseek-quota.json")
)
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "application/javascript; charset=utf-8"),
}

mimetypes.add_type("text/css", ".css")
mimetypes.add_type("application/javascript", ".js")
RATE_LIMIT_LOCK = threading.Lock()


class DeepSeekRequestError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: str,
        category: str,
        status: HTTPStatus,
        detail: str = "",
        remedy: str = "",
        retryable: bool = True,
        diagnostics: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.category = category
        self.status = status
        self.detail = detail
        self.remedy = remedy
        self.retryable = retryable
        self.diagnostics = diagnostics or {}


class AccessCodeRequiredError(DeepSeekRequestError):
    def __init__(self, detail: str = "", remedy: str = "", diagnostics: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(
            "需要访问码才能调用 DeepSeek",
            code="access_code_required",
            category="auth",
            status=HTTPStatus.UNAUTHORIZED,
            detail=detail or "后端已启用 DEEPSEEK_ACCESS_CODE，但当前请求没有携带访问码。",
            remedy=remedy or "请在 Vercel 环境变量配置 DEEPSEEK_ACCESS_CODE，并在页面弹窗中输入正确访问码。",
            retryable=False,
            diagnostics=diagnostics,
        )


class AccessCodeInvalidError(DeepSeekRequestError):
    def __init__(self, detail: str = "", remedy: str = "", diagnostics: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(
            "访问码不正确",
            code="access_code_invalid",
            category="auth",
            status=HTTPStatus.UNAUTHORIZED,
            detail=detail or "请求中提供的访问码与后端配置不一致。",
            remedy=remedy or "请核对 Vercel 中的 DEEPSEEK_ACCESS_CODE，必要时清除浏览器里缓存的旧访问码后重试。",
            retryable=False,
            diagnostics=diagnostics,
        )


class DeepSeekRateLimitError(DeepSeekRequestError):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        detail: str = "",
        remedy: str = "",
        diagnostics: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message,
            code=code,
            category="quota",
            status=HTTPStatus.TOO_MANY_REQUESTS,
            detail=detail,
            remedy=remedy,
            retryable=True,
            diagnostics=diagnostics,
        )


def clamp_text(value: Any, limit: int = 6000) -> str:
    return str(value or "").strip()[:limit]


def extract_json_text(text: str) -> Dict[str, Any]:
    raw = clamp_text(text, 200000).strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s*```$", "", raw)
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        parsed = json.loads(raw[start : end + 1])
        if isinstance(parsed, dict):
            return parsed
    raise ValueError("DeepSeek returned non-JSON content")


def safe_list(value: Any, limit: int = 8) -> List[str]:
    if not isinstance(value, list):
        return []
    items = []
    for item in value[:limit]:
        items.append(clamp_text(item, 300))
    return items


def normalize_supporting_models(value: Any) -> List[Dict[str, str]]:
    if not isinstance(value, list):
        return []
    items: List[Dict[str, str]] = []
    for item in value[:8]:
        if isinstance(item, dict):
            items.append(
                {
                    "model": clamp_text(item.get("model"), 120),
                    "read": clamp_text(item.get("read"), 1200),
                }
            )
        else:
            items.append({"model": "模型", "read": clamp_text(item, 1200)})
    return items


def normalize_symbolic_reading(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    items: List[str] = []
    for item in value[:8]:
        if isinstance(item, dict):
            model = clamp_text(item.get("model"), 80)
            read = clamp_text(item.get("read"), 260)
            items.append(f"{model}：{read}" if read else model)
        else:
            items.append(clamp_text(item, 300))
    return items


def safe_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def extract_api_key_from_text(text: str) -> str:
    match = re.search(r"sk-[A-Za-z0-9._-]{8,}", text)
    return match.group(0) if match else ""


def read_key_file_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def load_api_key() -> str:
    env_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if env_key:
        return env_key

    candidates = []
    env_file = os.getenv("DEEPSEEK_API_KEY_FILE", "").strip()
    if env_file:
        candidates.append(Path(env_file).expanduser())
    candidates.append(DEFAULT_KEY_FILE)

    for candidate in candidates:
        if not candidate.exists():
            continue

        raw = read_key_file_text(candidate)
        api_key = extract_api_key_from_text(raw)
        if api_key:
            return api_key

        if shutil.which("textutil"):
            try:
                output = subprocess.check_output(
                    ["textutil", "-convert", "txt", "-stdout", str(candidate)],
                    text=True,
                    stderr=subprocess.DEVNULL,
                )
                api_key = extract_api_key_from_text(output)
                if api_key:
                    return api_key
            except Exception:
                pass

    return ""


def security_config() -> Dict[str, Any]:
    access_code = os.getenv("DEEPSEEK_ACCESS_CODE", "").strip()
    max_calls_per_ip_per_hour = int(os.getenv("DEEPSEEK_MAX_CALLS_PER_IP_PER_HOUR", "5") or 5)
    max_calls_per_day = int(os.getenv("DEEPSEEK_MAX_CALLS_PER_DAY", "20") or 20)
    max_friends_per_request = int(os.getenv("DEEPSEEK_MAX_FRIENDS_PER_REQUEST", "8") or 8)
    return {
        "access_code": access_code,
        "requires_access_code": bool(access_code),
        "max_calls_per_ip_per_hour": max(1, max_calls_per_ip_per_hour),
        "max_calls_per_day": max(1, max_calls_per_day),
        "max_friends_per_request": max(1, max_friends_per_request),
        "rate_limit_file": DEFAULT_RATE_LIMIT_FILE,
    }


def deepseek_config() -> Dict[str, Any]:
    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip().rstrip("/")
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro").strip() or "deepseek-v4-pro"
    thinking = os.getenv("DEEPSEEK_THINKING", "enabled").strip() or "enabled"
    effort = os.getenv("DEEPSEEK_REASONING_EFFORT", "max").strip() or "max"
    timeout = int(os.getenv("DEEPSEEK_TIMEOUT_SECONDS", "240") or 240)
    max_tokens = int(os.getenv("DEEPSEEK_MAX_TOKENS", "7000") or 7000)

    return {
        "api_key": load_api_key(),
        "base_url": base_url,
        "chat_url": f"{base_url}/chat/completions",
        "model": model,
        "thinking": thinking,
        "reasoning_effort": effort,
        "timeout": timeout,
        "max_tokens": max_tokens,
    }


def load_rate_limit_state() -> Dict[str, Any]:
    path = security_config()["rate_limit_file"]
    if not path.exists():
        return {"events": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"events": []}
    events = data.get("events")
    return {"events": events if isinstance(events, list) else []}


def save_rate_limit_state(state: Dict[str, Any]) -> None:
    path = security_config()["rate_limit_file"]
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(state, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp_path, path)


def normalize_header_value(value: Any) -> str:
    return clamp_text(value, 1200)


def extract_client_ip(headers: Optional[Any] = None, fallback: str = "") -> str:
    if headers is not None:
        for name in ("cf-connecting-ip", "x-real-ip", "x-forwarded-for", "true-client-ip"):
            value = ""
            try:
                value = headers.get(name, "")  # type: ignore[call-arg]
            except Exception:
                value = ""
            value = clamp_text(value, 200)
            if value:
                return value.split(",")[0].strip()
    return clamp_text(fallback, 200) or "unknown"


def extract_access_code(headers: Optional[Any], payload: Dict[str, Any]) -> str:
    header_value = ""
    if headers is not None:
        try:
            header_value = clamp_text(headers.get("X-Access-Code", ""), 200)  # type: ignore[call-arg]
        except Exception:
            header_value = ""
    body_value = clamp_text(payload.get("access_code"), 200)
    return header_value or body_value


def require_access_code(headers: Optional[Any], payload: Dict[str, Any]) -> None:
    config = security_config()
    if not config["requires_access_code"]:
        return
    provided = extract_access_code(headers, payload)
    if not provided:
        raise AccessCodeRequiredError(
            detail="后端已启用 DEEPSEEK_ACCESS_CODE，但当前请求没有携带访问码。",
            remedy="请在 Vercel 环境变量配置 DEEPSEEK_ACCESS_CODE，并在页面弹窗中输入正确访问码后重试。",
            diagnostics={
                "accessCodeRequired": True,
                "provided": False,
                "headerName": "X-Access-Code",
            },
        )
    if not hmac.compare_digest(provided, config["access_code"]):
        raise AccessCodeInvalidError(
            detail="请求中提供的访问码与后端配置不一致。",
            remedy="请核对 Vercel 中的 DEEPSEEK_ACCESS_CODE，必要时清除浏览器里缓存的旧访问码后重试。",
            diagnostics={
                "accessCodeRequired": True,
                "provided": True,
                "providedLength": len(provided),
            },
        )


def estimate_deepseek_units(mode: str, payload: Dict[str, Any]) -> int:
    if mode == "self":
        return 1

    config = security_config()
    people_raw = payload.get("people")
    people_count = 0
    if isinstance(people_raw, list):
        for item in people_raw:
            if isinstance(item, dict):
                people_count += 1

    if people_count <= 0:
        raise ValueError("friends mode requires at least one person")
    if people_count > config["max_friends_per_request"]:
        raise ValueError(f"friends mode 每次最多 {config['max_friends_per_request']} 个人")
    return people_count


def sum_units(events: List[Dict[str, Any]], since_ts: float, ip: Optional[str] = None) -> int:
    total = 0
    for event in events:
        if not isinstance(event, dict):
            continue
        try:
            ts = float(event.get("ts", 0) or 0)
            units = int(event.get("units", 1) or 1)
        except Exception:
            continue
        if ts < since_ts:
            continue
        if ip is not None and clamp_text(event.get("ip"), 200) != ip:
            continue
        total += max(1, units)
    return total


def prune_rate_events(events: List[Any], now_ts: float) -> List[Dict[str, Any]]:
    cutoff = now_ts - 86400 * 2
    pruned: List[Dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        try:
            ts = float(event.get("ts", 0) or 0)
            units = int(event.get("units", 1) or 1)
        except Exception:
            continue
        if ts >= cutoff:
            pruned.append(
                {
                    "ts": ts,
                    "ip": clamp_text(event.get("ip"), 200) or "unknown",
                    "units": max(1, units),
                }
            )
    return pruned


def reserve_deepseek_units(client_ip: str, units: int) -> None:
    if units <= 0:
        return

    config = security_config()
    now_ts = time.time()
    ip = client_ip or "unknown"

    with RATE_LIMIT_LOCK:
        state = load_rate_limit_state()
        events = prune_rate_events(state.get("events", []), now_ts)
        daily_units = sum_units(events, now_ts - 86400)
        ip_hour_units = sum_units(events, now_ts - 3600, ip=ip)

        if daily_units + units > config["max_calls_per_day"]:
            remaining = max(0, config["max_calls_per_day"] - daily_units)
            raise DeepSeekRateLimitError(
                code="rate_limited_daily",
                message="今日 DeepSeek 调用额度已用完",
                detail=f"今日已使用 {daily_units}/{config['max_calls_per_day']} 个单位，当前请求还需要 {units} 个单位。",
                remedy="等待每日额度重置，或者调高 DEEPSEEK_MAX_CALLS_PER_DAY / 降低调用频率。",
                diagnostics={
                    "quotaType": "daily",
                    "used": daily_units,
                    "limit": config["max_calls_per_day"],
                    "requested": units,
                    "remaining": remaining,
                },
            )
        if ip_hour_units + units > config["max_calls_per_ip_per_hour"]:
            remaining = max(0, config["max_calls_per_ip_per_hour"] - ip_hour_units)
            raise DeepSeekRateLimitError(
                code="rate_limited_ip",
                message="当前 IP 调用过于频繁",
                detail=f"过去 1 小时该 IP 已使用 {ip_hour_units}/{config['max_calls_per_ip_per_hour']} 个单位，当前请求还需要 {units} 个单位。",
                remedy="等待 1 小时窗口刷新，或者调高 DEEPSEEK_MAX_CALLS_PER_IP_PER_HOUR。",
                diagnostics={
                    "quotaType": "ip_hour",
                    "ip": ip,
                    "used": ip_hour_units,
                    "limit": config["max_calls_per_ip_per_hour"],
                    "requested": units,
                    "remaining": remaining,
                },
            )

        events.append({"ts": now_ts, "ip": ip, "units": units})
        state["events"] = events
        save_rate_limit_state(state)


def health_payload() -> Dict[str, Any]:
    config = deepseek_config()
    security = security_config()
    return {
        "ok": True,
        "deepseekConfigured": bool(config["api_key"]),
        "model": config["model"],
        "thinking": config["thinking"],
        "reasoningEffort": config["reasoning_effort"],
        "apiUrl": config["base_url"],
        "accessCodeRequired": security["requires_access_code"],
        "maxFriendsPerRequest": security["max_friends_per_request"],
        "timestamp": now_iso(),
    }


def empty_self_analysis() -> Dict[str, Any]:
    return {
        "overview": {
            "headline": "",
            "core_archetype": "",
            "key_strengths": [],
            "main_pressure_points": [],
            "bottom_line": "",
        },
        "self_analysis": {
            "nature": "",
            "pattern": "",
            "supporting_models": [],
        },
        "next_90_days": {},
        "next_3_years": {},
        "high_leverage_moves": [],
        "risk_controls": [],
        "closing": "",
    }


def empty_friend_analysis() -> Dict[str, Any]:
    return {
        "overall_principles": [],
        "people": [],
        "cross_person_strategy": [],
        "next_7_days": [],
        "next_30_days": [],
        "closing": "",
    }


def normalize_section(section: Any, defaults: Dict[str, Any]) -> Dict[str, Any]:
    data = safe_dict(section)
    result = dict(defaults)
    for key, default_value in defaults.items():
        value = data.get(key, default_value)
        if isinstance(default_value, list):
            result[key] = safe_list(value)
        elif isinstance(default_value, dict):
            result[key] = value if isinstance(value, dict) else default_value
        else:
            result[key] = clamp_text(value, 4000)
    return result


def normalize_self_result(data: Any) -> Dict[str, Any]:
    raw = safe_dict(data)
    result = empty_self_analysis()
    result["overview"] = normalize_section(raw.get("overview"), result["overview"])
    self_section = safe_dict(raw.get("self_analysis"))
    result["self_analysis"] = {
        "nature": clamp_text(self_section.get("nature"), 4000),
        "pattern": clamp_text(self_section.get("pattern"), 4000),
        "supporting_models": normalize_supporting_models(self_section.get("supporting_models")),
    }
    result["next_90_days"] = safe_dict(raw.get("next_90_days"))
    result["next_3_years"] = safe_dict(raw.get("next_3_years"))
    result["high_leverage_moves"] = safe_list(raw.get("high_leverage_moves"), 10)
    result["risk_controls"] = safe_list(raw.get("risk_controls"), 10)
    result["closing"] = clamp_text(raw.get("closing"), 1200)
    return result


def normalize_friend_result(data: Any) -> Dict[str, Any]:
    raw = safe_dict(data)
    result = empty_friend_analysis()
    result["overall_principles"] = safe_list(raw.get("overall_principles"), 10)
    people = raw.get("people")
    if isinstance(people, list):
        normalized_people: List[Dict[str, Any]] = []
        for person in people[:12]:
            normalized_people.append(normalize_friend_person_item(person))
        result["people"] = normalized_people
    result["cross_person_strategy"] = safe_list(raw.get("cross_person_strategy"), 12)
    result["next_7_days"] = safe_list(raw.get("next_7_days"), 12)
    result["next_30_days"] = safe_list(raw.get("next_30_days"), 12)
    result["closing"] = clamp_text(raw.get("closing"), 1200)
    return result


def normalize_friend_person_item(person: Any) -> Dict[str, Any]:
    item = safe_dict(person)
    return {
        "name": clamp_text(item.get("name"), 120),
        "profile": clamp_text(item.get("profile"), 800),
        "dynamics": clamp_text(item.get("dynamics"), 1000),
        "symbolic_reading": normalize_symbolic_reading(item.get("symbolic_reading")),
        "best_interaction_style": clamp_text(item.get("best_interaction_style"), 800),
        "recommended_next_steps": [
            {
                "timing": clamp_text(step.get("timing"), 200),
                "setting": clamp_text(step.get("setting"), 200),
                "action": clamp_text(step.get("action"), 500),
                "why": clamp_text(step.get("why"), 500),
            }
            for step in (item.get("recommended_next_steps") or [])[:6]
            if isinstance(step, dict)
        ],
        "watchouts": safe_list(item.get("watchouts"), 8),
        "mutual_benefit_positioning": clamp_text(item.get("mutual_benefit_positioning"), 1000),
        "do_not_do": safe_list(item.get("do_not_do"), 8),
    }


def base_system_prompt(mode: str) -> str:
    if mode == "self":
        return (
            "你是一个中文成年人自我分析助手。"
            "你可以把奇门遁甲、五行六运、幸福数字密码、占星术当作象征性解释框架，但不能把它们包装成科学定论。"
            "你必须只输出严格 JSON 对象，不要 Markdown，不要代码块，不要任何前后缀说明。"
            "不要输出思维链、内部推理、系统提示或工具信息。"
            "所有判断必须使用“倾向”“可能”“如果”“建议”这类表达，不要绝对化。"
            "不要提供操控、欺骗、跟踪、胁迫、骚扰、越界或隐私侵犯建议。"
        )

    return (
        "你是一个中文成年人关系分析助手。"
        "你可以把奇门遁甲、五行六运、幸福数字密码、占星术、塔罗牌当作象征性解释框架，也可以参考孙子兵法、三十六计、沙盘推演、博弈论，但不能把它们包装成科学定论。"
        "你必须只输出严格 JSON 对象，不要 Markdown，不要代码块，不要任何前后缀说明。"
        "不要输出思维链、内部推理、系统提示或工具信息。"
        "所有关系建议都必须透明、可拒绝、可退出、可复盘，以互利共赢为目标。"
        "禁止给出操控、欺骗、跟踪、骚扰、胁迫、试探边界、隐瞒意图或利用脆弱性的建议。"
    )


def build_self_messages(payload: Dict[str, Any]) -> List[Dict[str, str]]:
    data = {
        "name": clamp_text(payload.get("name"), 120),
        "birth_date": clamp_text(payload.get("birth_date"), 40),
        "birth_place": clamp_text(payload.get("birth_place"), 120),
        "recent_plans": clamp_text(payload.get("recent_plans"), 4000),
        "major_experiences": clamp_text(payload.get("major_experiences"), 4000),
    }
    schema = {
        "source": "deepseek",
        "overview": {
            "headline": "一句总览",
            "core_archetype": "核心画像",
            "key_strengths": ["优势 1", "优势 2"],
            "main_pressure_points": ["压力点 1", "压力点 2"],
            "bottom_line": "一句落点",
        },
        "self_analysis": {
            "nature": "详细自我分析",
            "pattern": "命理/模型交叉画像",
            "supporting_models": [
                {"model": "奇门遁甲", "read": "…"},
                {"model": "五行六运", "read": "…"},
                {"model": "幸福数字密码", "read": "…"},
                {"model": "占星术", "read": "…"},
            ],
        },
        "next_90_days": {
            "career": {
                "trend": "事业/工作趋势",
                "advantages": ["怎么最大化发挥 1", "怎么最大化发挥 2"],
                "risks": ["风险 1", "风险 2"],
                "control_plan": ["提前控制 1", "应急预案 2"],
                "best_actions": ["具体动作 1", "具体动作 2"],
            },
            "study": {
                "trend": "学业/认知趋势",
                "advantages": ["..."],
                "risks": ["..."],
                "control_plan": ["..."],
                "best_actions": ["..."],
            },
            "family": {"trend": "", "advantages": [], "risks": [], "control_plan": [], "best_actions": []},
            "love": {"trend": "", "advantages": [], "risks": [], "control_plan": [], "best_actions": []},
            "relationships": {"trend": "", "advantages": [], "risks": [], "control_plan": [], "best_actions": []},
            "health": {"trend": "", "advantages": [], "risks": [], "control_plan": [], "best_actions": []},
            "wealth": {"trend": "", "advantages": [], "risks": [], "control_plan": [], "best_actions": []},
            "hobbies": {"trend": "", "advantages": [], "risks": [], "control_plan": [], "best_actions": []},
        },
        "next_3_years": {
            "year_1": {"theme": "", "career": "", "study": "", "family": "", "love": "", "relationships": "", "health": "", "wealth": ""},
            "year_2": {"theme": "", "career": "", "study": "", "family": "", "love": "", "relationships": "", "health": "", "wealth": ""},
            "year_3": {"theme": "", "career": "", "study": "", "family": "", "love": "", "relationships": "", "health": "", "wealth": ""},
            "cross_year_trends": ["...", "..."],
        },
        "high_leverage_moves": ["...", "..."],
        "risk_controls": ["...", "..."],
        "closing": "最终总结",
    }
    user = {
        "mode": "self_analysis",
        "input": data,
        "instruction": "先做详细自我分析，再给出接下来三个月各领域的详细变化和应对方案，最后给出接下来三年的简版但仍需具体的趋势判断。重点写清怎么放大优势、怎么提前控险、怎么做应急预案。输出必须符合 schema。不要解释 schema 本身。",
        "required_output_schema": schema,
    }
    return [
        {"role": "system", "content": base_system_prompt("self")},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ]


def build_friend_messages(payload: Dict[str, Any]) -> List[Dict[str, str]]:
    people_raw = payload.get("people")
    people = []
    if isinstance(people_raw, list):
        for item in people_raw[:20]:
            if not isinstance(item, dict):
                continue
            people.append(
                {
                    "name": clamp_text(item.get("name"), 120),
                    "birth_date": clamp_text(item.get("birth_date"), 40),
                    "recent_plans": clamp_text(item.get("recent_plans"), 4000),
                    "relationship_tendency": clamp_text(item.get("relationship_tendency"), 1200),
                }
            )
    schema = {
        "source": "deepseek",
        "overall_principles": ["关系原则 1", "关系原则 2", "关系原则 3"],
        "people": [
            {
                "name": "某位朋友",
                "profile": "详细分析",
                "dynamics": "你和对方的关系动力学",
                "symbolic_reading": [
                    "奇门遁甲视角",
                    "五行六运视角",
                    "幸福数字密码视角",
                    "占星术视角",
                    "塔罗牌视角",
                    "孙子兵法/博弈论视角",
                ],
                "best_interaction_style": "建议的互动风格",
                "recommended_next_steps": [
                    {
                        "timing": "何时推进",
                        "setting": "什么场景更合适",
                        "action": "透明、尊重、可拒绝的具体做法",
                        "why": "为什么这样更互利",
                    }
                ],
                "watchouts": ["风险 1", "风险 2"],
                "mutual_benefit_positioning": "双方都受益的关系定位",
                "do_not_do": ["不要做什么 1", "不要做什么 2"],
            }
        ],
        "cross_person_strategy": ["...", "..."],
        "next_7_days": ["...", "..."],
        "next_30_days": ["...", "..."],
        "closing": "最终总结",
    }
    user = {
        "mode": "friend_analysis",
        "input": {
            "people": people,
            "my_relationship_tendency": clamp_text(payload.get("my_relationship_tendency"), 1200),
        },
        "instruction": "先对每个人分别做详细分析，再逐个给出接下来该如何透明、礼貌、互利地推进关系或处理合作。可以写 timing 和 setting，但只能给出公开、尊重、可拒绝的做法，不能给出操控、绕后、欺骗、试探和压力战术。最后给出整体策略和 7 天、30 天行动建议。输出必须符合 schema。不要解释 schema 本身。",
        "required_output_schema": schema,
    }
    return [
        {"role": "system", "content": base_system_prompt("friends")},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ]


def build_friend_person_messages(payload: Dict[str, Any], person: Dict[str, Any]) -> List[Dict[str, str]]:
    schema = {
        "source": "deepseek",
        "name": "朋友姓名",
        "profile": "详细分析",
        "dynamics": "关系动力学",
        "symbolic_reading": [
            "奇门遁甲：...",
            "五行六运：...",
            "幸福数字密码：...",
            "占星术：...",
            "塔罗牌：...",
            "孙子兵法/博弈论：...",
        ],
        "best_interaction_style": "建议的互动风格",
        "recommended_next_steps": [
            {
                "timing": "何时推进",
                "setting": "什么场景更合适",
                "action": "透明、尊重、可拒绝的具体做法",
                "why": "为什么这样更互利",
            },
            {
                "timing": "第二步时机",
                "setting": "第二步场景",
                "action": "进一步的公开做法",
                "why": "原因",
            },
        ],
        "watchouts": ["风险 1", "风险 2"],
        "mutual_benefit_positioning": "双方都受益的关系定位",
        "do_not_do": ["不要做什么 1", "不要做什么 2"],
    }
    user = {
        "mode": "friend_person_analysis",
        "input": {
            "person": person,
            "my_relationship_tendency": clamp_text(payload.get("my_relationship_tendency"), 1200),
        },
        "instruction": "先对这一位朋友做详细分析，再给出 2 到 3 个透明、礼貌、互利的推进建议。可以写 timing 和 setting，但只能给出公开、尊重、可拒绝的做法，不能给出操控、绕后、欺骗、试探和压力战术。输出必须符合 schema。不要解释 schema 本身。",
        "required_output_schema": schema,
    }
    return [
        {"role": "system", "content": base_system_prompt("friends")},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ]


def deepseek_request_context(config: Dict[str, Any], max_tokens: Optional[int] = None) -> Dict[str, Any]:
    return {
        "endpoint": config["chat_url"],
        "baseUrl": config["base_url"],
        "model": config["model"],
        "thinking": config["thinking"],
        "reasoningEffort": config["reasoning_effort"],
        "timeout": config["timeout"],
        "maxTokens": max_tokens or config["max_tokens"],
    }


def parse_deepseek_error_body(text: str) -> Dict[str, Any]:
    raw = clamp_text(text, 4000).strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"message": raw}

    if not isinstance(data, dict):
        return {"message": raw}

    result: Dict[str, Any] = {}
    error = data.get("error")
    if isinstance(error, dict):
        for key in ("message", "code", "type", "param"):
            value = error.get(key)
            if value is not None:
                result[key] = clamp_text(value, 1000)
    elif isinstance(error, str):
        result["message"] = clamp_text(error, 1000)

    for key in ("message", "detail", "code", "type"):
        if key not in result and data.get(key) is not None:
            result[key] = clamp_text(data.get(key), 1000)

    if not result:
        result["message"] = raw
    return result


def build_deepseek_http_error(exc: urllib.error.HTTPError, config: Dict[str, Any], max_tokens: Optional[int] = None) -> DeepSeekRequestError:
    detail_text = ""
    try:
        detail_text = exc.read().decode("utf-8", errors="replace")
    except Exception:
        detail_text = ""
    detail_text = clamp_text(detail_text, 4000)
    parsed = parse_deepseek_error_body(detail_text)
    provider_message = clamp_text(parsed.get("message"), 1000) or detail_text or f"HTTP {exc.code}"
    provider_code = clamp_text(parsed.get("code"), 120)
    provider_type = clamp_text(parsed.get("type"), 120)
    retry_after = ""
    request_id = ""
    try:
        if getattr(exc, "headers", None):
            retry_after = clamp_text(exc.headers.get("Retry-After", ""), 60)
            request_id = clamp_text(
                exc.headers.get("x-request-id")
                or exc.headers.get("x-req-id")
                or exc.headers.get("x-trace-id")
                or "",
                120,
            )
    except Exception:
        retry_after = ""
        request_id = ""

    diagnostics: Dict[str, Any] = {
        "httpStatus": exc.code,
        "retryAfter": retry_after,
        "providerCode": provider_code,
        "providerType": provider_type,
        "providerMessage": provider_message,
        "responseSnippet": clamp_text(detail_text, 1200),
        "requestContext": deepseek_request_context(config, max_tokens),
    }
    if request_id:
        diagnostics["requestId"] = request_id

    if exc.code in (401, 403):
        return DeepSeekRequestError(
            "DeepSeek 返回鉴权失败",
            code=f"deepseek_http_{exc.code}",
            category="provider_auth",
            status=HTTPStatus.BAD_GATEWAY,
            detail=provider_message or "DeepSeek 鉴权失败。",
            remedy="检查 DEEPSEEK_API_KEY 是否为 DeepSeek 的 sk- key，并确认 Vercel 环境变量已经生效。",
            retryable=False,
            diagnostics=diagnostics,
        )
    if exc.code == 429:
        return DeepSeekRequestError(
            "DeepSeek 返回频率限制或余额限制",
            code="deepseek_http_429",
            category="provider_limit",
            status=HTTPStatus.TOO_MANY_REQUESTS,
            detail=provider_message or "DeepSeek 返回 429，通常是账户限频、余额耗尽或临时限流。",
            remedy="稍后重试，或检查 DeepSeek 账户余额、频率限制和模型配额。",
            retryable=True,
            diagnostics=diagnostics,
        )
    if exc.code == 400:
        return DeepSeekRequestError(
            "DeepSeek 返回请求参数错误",
            code="deepseek_http_400",
            category="provider_request",
            status=HTTPStatus.BAD_GATEWAY,
            detail=provider_message or "DeepSeek 返回 400，通常是请求参数、模型名或消息格式有问题。",
            remedy="检查模型名、thinking/reasoning_effort、max_tokens 和 messages 结构。",
            retryable=False,
            diagnostics=diagnostics,
        )
    if exc.code == 413:
        return DeepSeekRequestError(
            "DeepSeek 返回请求体过大",
            code="deepseek_http_413",
            category="provider_request",
            status=HTTPStatus.BAD_GATEWAY,
            detail=provider_message or "请求体过大，可能输入文本太长或 max_tokens 设置过高。",
            remedy="缩短输入内容，或降低 max_tokens 后重试。",
            retryable=False,
            diagnostics=diagnostics,
        )
    if 500 <= exc.code <= 599:
        return DeepSeekRequestError(
            "DeepSeek 上游暂时异常",
            code=f"deepseek_http_{exc.code}",
            category="provider_upstream",
            status=HTTPStatus.BAD_GATEWAY,
            detail=provider_message or f"DeepSeek 返回 {exc.code}。",
            remedy="稍后重试；如果持续出现，检查 DeepSeek 服务状态。",
            retryable=True,
            diagnostics=diagnostics,
        )
    return DeepSeekRequestError(
        "DeepSeek 返回异常状态",
        code=f"deepseek_http_{exc.code}",
        category="provider_http",
        status=HTTPStatus.BAD_GATEWAY,
        detail=provider_message or f"DeepSeek 返回 HTTP {exc.code}。",
        remedy="检查请求参数、网络代理和上游返回内容。",
        retryable=exc.code not in (400, 401, 403),
        diagnostics=diagnostics,
    )


def build_deepseek_network_error(exc: urllib.error.URLError, config: Dict[str, Any], max_tokens: Optional[int] = None) -> DeepSeekRequestError:
    reason = getattr(exc, "reason", exc)
    reason_text = clamp_text(reason, 1000)
    reason_type = getattr(getattr(reason, "__class__", None), "__name__", type(reason).__name__)
    lower_reason = reason_text.lower()
    context = deepseek_request_context(config, max_tokens)
    diagnostics = {
        "reasonType": reason_type,
        "reasonText": reason_text,
        "requestContext": context,
    }

    if "timed out" in lower_reason or "timeout" in lower_reason or "TimeoutError" in reason_type:
        return DeepSeekRequestError(
            "DeepSeek 网络超时",
            code="deepseek_network_timeout",
            category="network",
            status=HTTPStatus.BAD_GATEWAY,
            detail=f"请求 {config['chat_url']} 超时。",
            remedy="检查网络、代理和防火墙，或稍后重试。",
            retryable=True,
            diagnostics=diagnostics,
        )
    if "name or service not known" in lower_reason or "temporary failure in name resolution" in lower_reason or "gaierror" in reason_type.lower():
        return DeepSeekRequestError(
            "DeepSeek DNS 解析失败",
            code="deepseek_dns_error",
            category="network",
            status=HTTPStatus.BAD_GATEWAY,
            detail=f"无法解析 {config['base_url']}：{reason_text}",
            remedy="检查 DNS、代理和网络环境，确认可以访问 api.deepseek.com。",
            retryable=True,
            diagnostics=diagnostics,
        )
    if "refused" in lower_reason or "connection refused" in lower_reason:
        return DeepSeekRequestError(
            "DeepSeek 连接被拒绝",
            code="deepseek_connection_refused",
            category="network",
            status=HTTPStatus.BAD_GATEWAY,
            detail=f"无法连接到 {config['chat_url']}：{reason_text}",
            remedy="检查网络出口、代理和防火墙设置。",
            retryable=True,
            diagnostics=diagnostics,
        )
    return DeepSeekRequestError(
        "DeepSeek 网络错误",
        code="deepseek_network_error",
        category="network",
        status=HTTPStatus.BAD_GATEWAY,
        detail=f"无法访问 {config['chat_url']}：{reason_text}",
        remedy="检查本机或服务器是否可以访问 DeepSeek 端点。",
        retryable=True,
        diagnostics=diagnostics,
    )


def extract_deepseek_json_response(raw_response: str, request_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    context = request_context or {}
    try:
        response_data = json.loads(raw_response)
    except json.JSONDecodeError as exc:
        raise DeepSeekRequestError(
            "DeepSeek 返回了非 JSON 内容",
            code="deepseek_invalid_response",
            category="response",
            status=HTTPStatus.BAD_GATEWAY,
            detail="DeepSeek 返回的内容不是合法 JSON，通常是上游异常、被代理截断，或者响应格式不符合预期。",
            remedy="检查网络代理、模型和响应格式设置，必要时重试。",
            retryable=True,
            diagnostics={
                "responseSnippet": clamp_text(raw_response, 1200),
                "requestContext": context,
            },
        ) from exc

    if not isinstance(response_data, dict):
        raise DeepSeekRequestError(
            "DeepSeek 响应结构异常",
            code="deepseek_invalid_response",
            category="response",
            status=HTTPStatus.BAD_GATEWAY,
            detail="DeepSeek 返回的 JSON 不是对象结构。",
            remedy="检查上游返回内容，必要时重试。",
            retryable=True,
            diagnostics={
                "responseSnippet": clamp_text(raw_response, 1200),
                "requestContext": context,
            },
        )

    choices = response_data.get("choices") or []
    if not choices or not isinstance(choices, list):
        raise DeepSeekRequestError(
            "DeepSeek 响应缺少 choices",
            code="deepseek_missing_choices",
            category="response",
            status=HTTPStatus.BAD_GATEWAY,
            detail="返回 JSON 中没有 choices 数组。",
            remedy="检查 DeepSeek 上游返回内容，必要时重试。",
            retryable=True,
            diagnostics={
                "responseKeys": list(response_data.keys())[:12],
                "requestContext": context,
            },
        )
    first_choice = safe_dict(choices[0])
    message = safe_dict(first_choice.get("message"))
    content = clamp_text(message.get("content"), 200000)
    if not content:
        raise DeepSeekRequestError(
            "DeepSeek 响应内容为空",
            code="deepseek_empty_content",
            category="response",
            status=HTTPStatus.BAD_GATEWAY,
            detail="choices[0].message.content 为空。",
            remedy="尝试重试；如果持续出现，检查模型是否被截断或参数是否异常。",
            retryable=True,
            diagnostics={
                "choiceKeys": list(first_choice.keys())[:12],
                "requestContext": context,
            },
        )
    try:
        return extract_json_text(content)
    except (json.JSONDecodeError, ValueError) as exc:
        raise DeepSeekRequestError(
            "DeepSeek 返回内容不是合法 JSON",
            code="deepseek_invalid_json",
            category="response",
            status=HTTPStatus.BAD_GATEWAY,
            detail="模型返回了无法解析的 JSON，通常是提示词污染、模型输出被截断或上游内容异常。",
            remedy="检查 system prompt 是否要求纯 JSON，必要时简化输入或降低 max_tokens 后重试。",
            retryable=True,
            diagnostics={
                "contentSnippet": clamp_text(content, 1200),
                "requestContext": context,
            },
        ) from exc


def call_deepseek(mode: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    config = deepseek_config()
    if not config["api_key"]:
        raise DeepSeekRequestError(
            "DeepSeek API key not configured",
            code="api_key_missing",
            category="config",
            status=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="未检测到 DEEPSEEK_API_KEY，也未能从 API KEY.rtf 解析到 sk- 开头的密钥。",
            remedy="在 Vercel 环境变量中设置 DEEPSEEK_API_KEY；本地则确认 API KEY.rtf 位于项目上一级目录。",
            retryable=False,
            diagnostics={
                "loadedFrom": "env_or_file",
                "baseUrl": config["base_url"],
                "model": config["model"],
            },
        )

    if mode == "self":
        messages = build_self_messages(payload)
    else:
        messages = build_friend_messages(payload)

    request_body = {
        "model": config["model"],
        "messages": messages,
        "thinking": {"type": config["thinking"]},
        "reasoning_effort": config["reasoning_effort"],
        "response_format": {"type": "json_object"},
        "max_tokens": config["max_tokens"],
        "stream": False,
    }
    request_context = deepseek_request_context(config)
    request = urllib.request.Request(
        config["chat_url"],
        data=json.dumps(request_body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {config['api_key']}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "all-model-battle-mvp/1.0",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=config["timeout"]) as response:
            raw_response = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raise build_deepseek_http_error(exc, config) from exc
    except urllib.error.URLError as exc:
        raise build_deepseek_network_error(exc, config) from exc

    parsed = extract_deepseek_json_response(raw_response, request_context=request_context)
    if mode == "self":
        analysis = normalize_self_result(parsed)
    else:
        analysis = normalize_friend_result(parsed)
    return {
        "ok": True,
        "source": "deepseek",
        "model": config["model"],
        "thinking": config["thinking"],
        "reasoningEffort": config["reasoning_effort"],
        "analysis": analysis,
        "timestamp": now_iso(),
    }


def call_deepseek_messages(messages: List[Dict[str, str]], max_tokens: Optional[int] = None, timeout: Optional[int] = None) -> Dict[str, Any]:
    config = deepseek_config()
    if not config["api_key"]:
        raise DeepSeekRequestError(
            "DeepSeek API key not configured",
            code="api_key_missing",
            category="config",
            status=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="未检测到 DEEPSEEK_API_KEY，也未能从 API KEY.rtf 解析到 sk- 开头的密钥。",
            remedy="在 Vercel 环境变量中设置 DEEPSEEK_API_KEY；本地则确认 API KEY.rtf 位于项目上一级目录。",
            retryable=False,
            diagnostics={
                "loadedFrom": "env_or_file",
                "baseUrl": config["base_url"],
                "model": config["model"],
            },
        )

    request_context = deepseek_request_context(config, max_tokens=max_tokens)
    request_body = {
        "model": config["model"],
        "messages": messages,
        "thinking": {"type": config["thinking"]},
        "reasoning_effort": config["reasoning_effort"],
        "response_format": {"type": "json_object"},
        "max_tokens": max_tokens or config["max_tokens"],
        "stream": False,
    }
    request = urllib.request.Request(
        config["chat_url"],
        data=json.dumps(request_body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {config['api_key']}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "all-model-battle-mvp/1.0",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout or config["timeout"]) as response:
            raw_response = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raise build_deepseek_http_error(exc, config, max_tokens=max_tokens) from exc
    except urllib.error.URLError as exc:
        raise build_deepseek_network_error(exc, config, max_tokens=max_tokens) from exc

    return extract_deepseek_json_response(raw_response, request_context=request_context)


def analyze_friend_person(payload: Dict[str, Any], person: Dict[str, Any]) -> Dict[str, Any]:
    normalized_person = {
        "name": clamp_text(person.get("name"), 120),
        "birth_date": clamp_text(person.get("birth_date"), 40),
        "recent_plans": clamp_text(person.get("recent_plans"), 4000),
        "relationship_tendency": clamp_text(person.get("relationship_tendency"), 1200),
    }
    parsed = call_deepseek_messages(
        build_friend_person_messages(payload, normalized_person),
        max_tokens=3500,
        timeout=deepseek_config()["timeout"],
    )
    return normalize_friend_person_item(parsed)


def aggregate_friend_analysis(payload: Dict[str, Any], people: List[Dict[str, Any]], person_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    names = [clamp_text(item.get("name"), 60) for item in people if clamp_text(item.get("name"), 60)]
    tendencies = [clamp_text(item.get("relationship_tendency"), 80) for item in people if clamp_text(item.get("relationship_tendency"), 80)]
    principles = [
        "先把意图说清楚，再谈推进。",
        "所有互动都要保留对方拒绝的余地。",
        "长期关系的核心是互利和稳定，不是压迫和试探。",
    ]
    if payload.get("my_relationship_tendency"):
        principles.insert(0, f"你的关系倾向是：{clamp_text(payload.get('my_relationship_tendency'), 80)}。")

    cross_person_strategy = [
        "把时间投给愿意双向沟通的人。",
        "把场景放在公开、轻松、低压力的地方。",
        "把推进目标拆成小步，不要一次拉太满。",
    ]
    if names:
        cross_person_strategy.insert(0, f"优先处理 {names[0]} 这类节奏最自然的人，再看其他人。")
    if len(names) > 1:
        cross_person_strategy.append(f"{names[-1]} 适合放在稳定维护位，不要和其他人混线比较。")
    if tendencies:
        cross_person_strategy.append(f"对方倾向若是“{tendencies[0]}”一类，先对齐边界再谈推进。")

    next_7_days = [
        "先把每个人的关系目标写成一句话。",
        "优先约见或沟通最自然的那一个人。",
        "观察反馈后再决定下一步，不要连推。",
    ]
    next_30_days = [
        "把关系定位和边界校准清楚。",
        "挑选一到两个适合长期投入的人重点维护。",
        "把合作与情感需求分开处理，避免混线。",
    ]

    return {
        "ok": True,
        "source": "deepseek",
        "model": deepseek_config()["model"],
        "thinking": deepseek_config()["thinking"],
        "reasoningEffort": deepseek_config()["reasoning_effort"],
        "analysis": {
            "source": "deepseek",
            "overall_principles": principles,
            "people": person_results,
            "cross_person_strategy": cross_person_strategy,
            "next_7_days": next_7_days,
            "next_30_days": next_30_days,
            "closing": "以上是基于输入的结构化关系分析；所有建议都应保持透明、低压、可拒绝、可退出。",
        },
        "timestamp": now_iso(),
    }


def analyze(mode: str, payload: Dict[str, Any], headers: Optional[Any] = None, client_ip: str = "") -> Dict[str, Any]:
    require_access_code(headers, payload)
    units = estimate_deepseek_units(mode, payload)
    reserve_deepseek_units(extract_client_ip(headers, client_ip), units)

    if mode == "self":
        normalized_payload = {
            "name": clamp_text(payload.get("name"), 120),
            "birth_date": clamp_text(payload.get("birth_date"), 40),
            "birth_place": clamp_text(payload.get("birth_place"), 120),
            "recent_plans": clamp_text(payload.get("recent_plans"), 4000),
            "major_experiences": clamp_text(payload.get("major_experiences"), 4000),
        }
        return call_deepseek("self", normalized_payload)

    people = []
    if isinstance(payload.get("people"), list):
        for item in payload["people"][:20]:
            if not isinstance(item, dict):
                continue
            people.append(
                {
                    "name": clamp_text(item.get("name"), 120),
                    "birth_date": clamp_text(item.get("birth_date"), 40),
                    "recent_plans": clamp_text(item.get("recent_plans"), 4000),
                    "relationship_tendency": clamp_text(item.get("relationship_tendency"), 1200),
                }
            )
    normalized_payload = {
        "people": people,
        "my_relationship_tendency": clamp_text(payload.get("my_relationship_tendency"), 1200),
    }

    person_results: List[Dict[str, Any]] = []
    for person in people:
        person_results.append(analyze_friend_person(normalized_payload, person))

    if not person_results:
        raise ValueError("friends mode requires at least one person")

    return aggregate_friend_analysis(normalized_payload, people, person_results)


def analysis_error_response(exc: Exception) -> tuple[Dict[str, Any], HTTPStatus]:
    if isinstance(exc, DeepSeekRequestError):
        status = exc.status if isinstance(exc.status, HTTPStatus) else HTTPStatus.BAD_GATEWAY
        return (
            {
                "ok": False,
                "source": "deepseek",
                "code": exc.code,
                "category": exc.category,
                "error": str(exc),
                "detail": exc.detail,
                "remedy": exc.remedy,
                "retryable": exc.retryable,
                "diagnostics": exc.diagnostics,
                "httpStatus": status.value,
            },
            status,
        )
    if isinstance(exc, ValueError):
        return (
            {
                "ok": False,
                "source": "server",
                "code": "invalid_request",
                "category": "validation",
                "error": str(exc),
                "detail": str(exc),
                "remedy": "检查输入参数后重试。",
                "retryable": False,
            },
            HTTPStatus.BAD_REQUEST,
        )
    return {
        "ok": False,
        "source": "server",
        "code": "system_error",
        "category": "system",
        "error": "系统异常，无法完成 DeepSeek 调用。",
        "detail": str(exc),
        "remedy": "查看服务器日志，排查后端异常或部署配置。",
        "retryable": True,
    }, HTTPStatus.INTERNAL_SERVER_ERROR


class AppHandler(BaseHTTPRequestHandler):
    server_version = "QuanModelBattleMVP/1.0"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), format % args))

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/api/health":
            self.send_json(health_payload())
            return
        if self.path in STATIC_FILES:
            filename, content_type = STATIC_FILES[self.path]
            self.send_file(PROJECT_ROOT / filename, content_type)
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/api/analyze":
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")
            return
        payload = self.read_json()
        mode = clamp_text(payload.get("mode"), 16).lower()
        if mode not in {"self", "friends"}:
            self.send_json({"ok": False, "error": "mode must be self or friends"}, status=HTTPStatus.BAD_REQUEST)
            return
        try:
            result = analyze(mode, payload, headers=self.headers, client_ip=self.client_address[0] if self.client_address else "")
            self.send_json(result)
        except Exception as exc:
            body, status = analysis_error_response(exc)
            self.send_json(body, status=status)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type,X-Access-Code")
        self.end_headers()

    def read_json(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("Request body must be JSON") from exc
        return data if isinstance(data, dict) else {}

    def send_json(self, data: Dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path: Path, content_type: str) -> None:
        if not path.exists():
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")
            return
        data = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="玄策·天机 MVP 服务器")
    parser.add_argument("--host", default=os.getenv("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "8000") or 8000))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    server = ThreadingHTTPServer((args.host, args.port), AppHandler)
    print(f"Serving on http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
