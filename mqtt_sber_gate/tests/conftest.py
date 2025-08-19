import sys
from pathlib import Path

# Добавляем rootfs/app в системный путь
sys.path.append(str(Path(__file__).parent.parent / "rootfs" / "app"))
