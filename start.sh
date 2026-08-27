#!/bin/bash
cd "$(dirname "$0")"
nohup venv/bin/uvicorn main:app --host 0.0.0.0 --port 8001 &>/tmp/seller.log &
echo $! > /tmp/seller.pid
echo "Seller agent started with PID $(cat /tmp/seller.pid)"
