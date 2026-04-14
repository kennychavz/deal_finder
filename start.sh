#!/usr/bin/env bash
set -e

# Start both backend and frontend in parallel.
# Ctrl+C kills both processes.

trap 'kill 0' EXIT

echo "Starting backend (port 8000)..."
uvicorn api:app --reload --port 8000 &

echo "Starting frontend (port 3333)..."
cd ui && npm run dev &

echo ""
echo "  Backend:  http://localhost:8000"
echo "  Frontend: http://localhost:3333"
echo ""

wait
