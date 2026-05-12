#!/usr/bin/env python3
"""Telegram 發送工具 — 給 GitHub Actions 腳本共用"""
import os
import urllib.request
import urllib.parse
import json


def send_message(text: str, parse_mode: str = "HTML") -> bool:
    """發送 Telegram 訊息。Token 和 Chat ID 從環境變數讀取。"""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

    if not token or not chat_id:
        print("[telegram_utils] ⚠ TELEGRAM_BOT_TOKEN 或 TELEGRAM_CHAT_ID 未設定，僅輸出到 stdout")
        print(text)
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = json.dumps({
        "chat_id": int(chat_id),
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
            if result.get("ok"):
                print(f"[telegram_utils] ✅ 訊息已發送 ({len(text)} chars)")
                return True
            else:
                print(f"[telegram_utils] ❌ Telegram API 錯誤: {result}")
                return False
    except Exception as e:
        print(f"[telegram_utils] ❌ 發送失敗: {e}")
        print(text)  # fallback: print so it's in Actions log
        return False


def format_escape(text: str) -> str:
    """跳脫 HTML 特殊字元（Telegram parse_mode=HTML 需要）"""
    return (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;"))
