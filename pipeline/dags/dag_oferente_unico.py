"""DAG de Apache Airflow para el pipeline semanal (alternativa a GitHub Actions).

Se integra con el stack de Airflow del curso de Frameworks y Herramientas para Big Data: copiar este
archivo a la carpeta dags/ y montar la carpeta despliegue/ en /opt/airflow/despliegue.
Cada tarea es un paso del lakehouse; si una falla, las siguientes no se ejecutan.
"""
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator

RAIZ = "/opt/airflow/despliegue"
PY = f"cd {RAIZ} && python"

with DAG(
    dag_id="oferente_unico_semanal",
    description="SECOP II -> bronze -> silver (Spark) -> gold: alertas de oferente único",
    schedule="0 6 * * 1",                    # lunes 06:00
    start_date=datetime(2026, 11, 2),
    catchup=False,
    default_args={"retries": 2, "retry_delay": timedelta(minutes=10)},
    tags=["secop", "ia", "lakehouse"],
) as dag:
    bronze = BashOperator(
        task_id="bronze_ingesta_api",
        bash_command=f"{PY} -c \"from datetime import date, timedelta; from pipeline.ingesta import ingerir; "
                     f"ingerir('{RAIZ}/lakehouse', str(date.today()-timedelta(days=7)), str(date.today()+timedelta(days=1)), str(date.today()))\"",
    )
    silver = BashOperator(
        task_id="silver_spark",
        bash_command=f"{PY} -c \"from pipeline.medallon_spark import construir_silver; construir_silver('{RAIZ}/lakehouse')\"",
    )
    gold = BashOperator(
        task_id="gold_estado_y_puntaje",
        bash_command=f"{PY} pipeline/ejecutar_semana.py --sin-ingesta --motor spark",
    )
    validacion = BashOperator(
        task_id="validacion_prospectiva",
        bash_command=f"{PY} pipeline/validacion_prospectiva.py",
    )
    publicar = BashOperator(
        task_id="publicar_lakehouse",
        bash_command=f"{PY} pipeline/sincronizar.py subir --capas bronze gold estado",
    )
    bronze >> silver >> gold >> validacion >> publicar
