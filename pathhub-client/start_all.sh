#!/usr/bin/env bash
# PathHub - One-click startup script
# Usage: bash pathhub/start_all.sh

set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "=== PathHub Startup ==="
echo "Repository root: $REPO_ROOT"
echo ""

# Check Python
if ! command -v python &> /dev/null; then
    echo "Error: python not found"
    exit 1
fi

# Check if uvicorn is available
if ! python -c "import uvicorn" 2>/dev/null; then
    echo "Error: uvicorn not installed. Run: pip install -r requirements.txt"
    exit 1
fi

# Check if database dependencies are installed
if ! python -c "import sqlalchemy" 2>/dev/null; then
    echo "Error: SQLAlchemy not installed. Run: pip install -r requirements.txt"
    exit 1
fi

# Check if npm is available for frontend
if ! command -v npm &> /dev/null; then
    echo "Warning: npm not found. Frontend will not start."
    SKIP_FRONTEND=1
fi

# Check if Docker is available
if ! command -v docker &> /dev/null; then
    echo "Warning: Docker not found. Please install Docker to run PostgreSQL."
    echo "You can also use an external PostgreSQL instance by setting DATABASE_URL."
    SKIP_DB_CHECK=1
fi

# Check if Docker Compose is available (try both v1 and v2)
DOCKER_COMPOSE_CMD=""
if command -v docker-compose &> /dev/null; then
    DOCKER_COMPOSE_CMD="docker-compose"
elif docker compose version &> /dev/null; then
    DOCKER_COMPOSE_CMD="docker compose"
else
    echo "Warning: Docker Compose not found."
    SKIP_DB_CHECK=1
fi

# Start PostgreSQL if not running
if [ -z "$SKIP_DB_CHECK" ]; then
    echo "[Database] Checking PostgreSQL status..."
    echo "[Database] Using: $DOCKER_COMPOSE_CMD"

    # Check if PostgreSQL container is running
    if ! $DOCKER_COMPOSE_CMD ps postgres 2>/dev/null | grep -q "Up"; then
        echo "[Database] PostgreSQL is not running. Starting..."
        $DOCKER_COMPOSE_CMD up -d postgres

        echo "[Database] Waiting for PostgreSQL to be ready..."
        sleep 3

        # Wait for PostgreSQL to be healthy
        for i in {1..30}; do
            if $DOCKER_COMPOSE_CMD exec -T postgres pg_isready -U pathhub > /dev/null 2>&1; then
                echo "[Database] ✓ PostgreSQL is ready!"
                break
            fi
            if [ $i -eq 30 ]; then
                echo "[Database] ✗ PostgreSQL failed to start. Check logs: $DOCKER_COMPOSE_CMD logs postgres"
                exit 1
            fi
            echo "[Database] Waiting... ($i/30)"
            sleep 1
        done

        # Check if database is initialized
        echo "[Database] Checking if database is initialized..."
        TABLE_COUNT=$($DOCKER_COMPOSE_CMD exec -T postgres psql -U pathhub -d pathhub -t -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public';" 2>/dev/null | tr -d ' ' || echo "0")

        if [ "$TABLE_COUNT" -eq "0" ]; then
            echo "[Database] Database not initialized. Running initialization..."
            python pathhub/services/backend/database/init_db.py
        else
            echo "[Database] ✓ Database already initialized ($TABLE_COUNT tables found)"
        fi
    else
        echo "[Database] ✓ PostgreSQL is already running"
    fi
    echo ""
else
    echo "[Database] Skipping database check (Docker not available)"
    echo "[Database] Make sure PostgreSQL is running and DATABASE_URL is set"
    echo ""
fi

# Create uploads directories if not exist
mkdir -p pathhub/uploads/ai_results
mkdir -p pathhub/uploads/thumbnails

echo "Starting services..."
echo ""

# Start Gateway (port 6100)
echo "[Backend 1/3] Starting Gateway on http://0.0.0.0:6100"
python -m uvicorn pathhub.services.gateway.main:app --host 0.0.0.0 --port 6100 --reload > /tmp/pathhub_gateway.log 2>&1 &
GATEWAY_PID=$!
echo "  PID: $GATEWAY_PID"

# Start Preprocessing Service (port 6101)
echo "[Backend 2/3] Starting Preprocessing Service on http://0.0.0.0:6101"
python -m uvicorn pathhub.services.backend.preprocessing.main:app --host 0.0.0.0 --port 6101 --reload > /tmp/pathhub_preprocessing.log 2>&1 &
PREPROCESSING_PID=$!
echo "  PID: $PREPROCESSING_PID"

# Start AI Service (port 6102)
echo "[Backend 3/3] Starting AI Service on http://0.0.0.0:6102"
python -m uvicorn pathhub.services.backend.ai.main:app --host 0.0.0.0 --port 6102 --reload > /tmp/pathhub_ai.log 2>&1 &
AI_PID=$!
echo "  PID: $AI_PID"

# Start Frontend (port 5173)
if [ -z "$SKIP_FRONTEND" ]; then
    echo "[Frontend] Starting Frontend on http://0.0.0.0:5173"
    cd pathhub/services/frontend

    # Install deps if node_modules missing
    if [ ! -d "node_modules" ]; then
        echo "  Installing frontend dependencies..."
        npm install > /tmp/pathhub_frontend_install.log 2>&1
    fi

    npm run dev -- --host 0.0.0.0 > /tmp/pathhub_frontend.log 2>&1 &
    FRONTEND_PID=$!
    echo "  PID: $FRONTEND_PID"
    cd "$REPO_ROOT"
else
    echo "[Frontend] Frontend skipped (npm not found)"
    FRONTEND_PID=""
fi

echo ""
echo "=========================================="
echo "✓ All services started successfully!"
echo "=========================================="
echo ""
echo "Services:"
if [ -z "$SKIP_DB_CHECK" ]; then
    echo "  Database:      postgresql://localhost:5432/pathhub"
    echo "  pgAdmin:       http://localhost:5050 (admin@pathhub.local / admin)"
fi
echo "  Gateway:       http://0.0.0.0:6100"
echo "  Preprocessing: http://0.0.0.0:6101"
echo "  AI:            http://0.0.0.0:6102"
if [ -n "$FRONTEND_PID" ]; then
    echo "  Frontend: http://0.0.0.0:5173"
fi
echo ""
echo "API Documentation:"
echo "  Gateway:       http://0.0.0.0:6100/docs"
echo "  Preprocessing: http://0.0.0.0:6101/docs"
echo "  AI:            http://0.0.0.0:6102/docs"
echo ""
echo "Logs:"
echo "  Gateway:       tail -f /tmp/pathhub_gateway.log"
echo "  Preprocessing: tail -f /tmp/pathhub_preprocessing.log"
echo "  AI:            tail -f /tmp/pathhub_ai.log"
if [ -n "$FRONTEND_PID" ]; then
    echo "  Frontend: tail -f /tmp/pathhub_frontend.log"
fi
if [ -z "$SKIP_DB_CHECK" ]; then
    echo "  Database: docker-compose logs -f postgres"
fi
echo ""
echo "To stop all services:"
echo "  kill $GATEWAY_PID $PREPROCESSING_PID $AI_PID${FRONTEND_PID:+ $FRONTEND_PID}"
if [ -z "$SKIP_DB_CHECK" ]; then
    echo "  docker-compose down"
fi
echo ""
echo "Or use: bash pathhub/stop_all.sh"
echo ""

# Save PIDs for stop script
cat > /tmp/pathhub_pids.txt <<EOF
GATEWAY_PID=$GATEWAY_PID
PREPROCESSING_PID=$PREPROCESSING_PID
AI_PID=$AI_PID
FRONTEND_PID=$FRONTEND_PID
EOF

echo "Press Ctrl+C to view logs (services will keep running in background)"
echo ""

# Wait a bit and show initial logs
sleep 2
echo "=== Initial logs ==="
echo ""
echo "--- Gateway ---"
tail -n 5 /tmp/pathhub_gateway.log 2>/dev/null || echo "No logs yet"
echo ""
echo "--- AI ---"
tail -n 5 /tmp/pathhub_ai.log 2>/dev/null || echo "No logs yet"
echo ""

if [ -n "$FRONTEND_PID" ]; then
    echo "--- Frontend ---"
    tail -n 5 /tmp/pathhub_frontend.log 2>/dev/null || echo "No logs yet"
    echo ""
fi

echo "All services running. Check logs above for any errors."

