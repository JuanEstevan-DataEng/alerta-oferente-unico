"""Sincroniza el lakehouse local con un repositorio de datos de Hugging Face (almacenamiento de objetos).

El repositorio de datos cumple el papel de MinIO/S3 en una arquitectura lakehouse: el pipeline
semanal (GitHub Actions) descarga bronze y estado, procesa y sube las capas actualizadas; la
aplicación web solo descarga gold y estado.

    python pipeline/sincronizar.py descargar --capas bronze estado
    python pipeline/sincronizar.py subir --capas bronze silver gold estado

Variables de entorno: HF_DATASET (p. ej. usuario/secop-oferente-unico-lakehouse) y HF_TOKEN.
"""
import argparse
import os
from pathlib import Path

from huggingface_hub import HfApi, snapshot_download

RAIZ = Path(__file__).resolve().parents[1]


def descargar(repo, lakehouse, capas):
    snapshot_download(repo_id=repo, repo_type="dataset", local_dir=str(lakehouse),
                      allow_patterns=[f"{c}/**" for c in capas], token=os.environ.get("HF_TOKEN"))


def subir(repo, lakehouse, capas, mensaje="Actualización semanal del lakehouse"):
    api = HfApi(token=os.environ.get("HF_TOKEN"))
    api.create_repo(repo, repo_type="dataset", private=False, exist_ok=True)
    api.upload_folder(repo_id=repo, repo_type="dataset", folder_path=str(lakehouse),
                      allow_patterns=[f"{c}/**" for c in capas], commit_message=mensaje)


if __name__ == "__main__":
    a = argparse.ArgumentParser()
    a.add_argument("accion", choices=["descargar", "subir"])
    a.add_argument("--capas", nargs="+", default=["gold", "estado"])
    a.add_argument("--lakehouse", default=str(RAIZ / "lakehouse"))
    a.add_argument("--repo", default=os.environ.get("HF_DATASET"))
    args = a.parse_args()
    if not args.repo:
        raise SystemExit("Defina HF_DATASET o --repo")
    (descargar if args.accion == "descargar" else subir)(args.repo, Path(args.lakehouse), args.capas)
    print(f"{args.accion}: {', '.join(args.capas)} <-> {args.repo}")
