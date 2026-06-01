"""
Конфигурация pytest: добавляет корневую директорию проекта в sys.path,
чтобы импорты вида 'from core.score_manager import ...' работали корректно
независимо от того, из какой папки запускается pytest.
"""

import sys
from pathlib import Path

# Добавляем корень проекта в начало sys.path
sys.path.insert(0, str(Path(__file__).parent))