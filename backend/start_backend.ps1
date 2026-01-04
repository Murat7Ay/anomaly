# Backend startup script
$env:DATABASE_URL = "postgresql+psycopg://anomaly:anomaly@localhost:5433/anomaly"
Write-Host "Starting backend server..."
Write-Host "Database URL: $env:DATABASE_URL"
python -m uvicorn app.main:app --reload --port 8000 --host 0.0.0.0

