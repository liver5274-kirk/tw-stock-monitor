#!/usr/bin/env python3
"""8:58 盤前預熱 — 確保 cron 服務活躍 + twstock 連線暖機"""
import twstock

# 試抓一筆資料暖連線
try:
    twstock.realtime.get('2330')
except:
    pass

# 寫入時間戳記供 debug
import datetime
with open('/tmp/hermes_premarket_warmup.log', 'a') as f:
    f.write(f"WARMUP {datetime.datetime.now().isoformat()}\n")
