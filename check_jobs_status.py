"""Verificar el status de los jobs en la base de datos."""
from app.database.database import ImageDatabase

db = ImageDatabase("visionvault.db")

print("=" * 80)
print("STATUS DE LOS JOBS EN LA BASE DE DATOS")
print("=" * 80)
print()

jobs = db.sticker_processing_jobs(limit=30)

print(f"Total de jobs encontrados: {len(jobs)}")
print()

# Contar por status
status_count = {}
for job in jobs:
    status = job.get("status", "Sin status")
    status_count[status] = status_count.get(status, 0) + 1

print("DISTRIBUCIÓN POR STATUS:")
for status, count in sorted(status_count.items(), key=lambda x: -x[1]):
    print(f"  {status}: {count} jobs")

print()
print("PRIMEROS 20 JOBS:")
print("-" * 80)

for i, job in enumerate(jobs[:20]):
    filename = job.get("source_path", "").split("\\")[-1] if job.get("source_path") else "???"
    status = job.get("status", "???")
    quality_status = job.get("quality_status", "???")
    engine = job.get("engine", "???")
    artifacts = job.get("artifacts", "{}")
    has_artifacts = len(artifacts) > 5
    
    print(f"{i+1:2}. {filename:30} | Status: {status:15} | Quality: {quality_status:10} | Engine: {engine:10} | Artifacts: {'Sí' if has_artifacts else 'No'}")

print("-" * 80)
