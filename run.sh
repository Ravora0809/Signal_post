#!/bin/bash
set -e

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

# Make local package importable
export PYTHONPATH="$ROOT_DIR:${PYTHONPATH:-}"

echo "======================================"
echo "       SIGNALPOST SETUP"
echo "======================================"

if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi

source .venv/bin/activate

python -m pip install --upgrade pip
pip install -r requirements.txt

if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "Created .env — add your API key."
fi

echo "Starting PostgreSQL..."
docker compose up -d db

echo "Waiting for database..."
sleep 5

echo "Running database migrations..."
alembic upgrade head

echo "Starting Signalpost API..."
uvicorn signalpost.api:app --host 0.0.0.0 --port 8000