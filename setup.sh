set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$REPO_DIR/venv"

echo "==> Installing system dependencies"
sudo apt update
sudo apt install -y \
    swig \
    build-essential \
    python3-dev \
    python3-venv \
    liblgpio-dev

echo "==> Setting up Python virtual environment"
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
    echo "    created venv at $VENV_DIR"
else
    echo "    venv already exists, skipping creation"
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

echo "==> Installing Python dependencies"
pip install --upgrade pip
pip install -r "$REPO_DIR/requirements.txt"

echo "==> Refreshing linker cache"
sudo ldconfig

echo "==> Done."
echo "Activate the environment with: source venv/bin/activate"
echo "Then run: python -m src.main -c 'config/default/config.json'"
