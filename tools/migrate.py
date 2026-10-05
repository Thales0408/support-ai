from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.database import inicializar_banco


def main():

    inicializar_banco()
    print("Migracao concluida.")


if __name__ == "__main__":

    main()
