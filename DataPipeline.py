from airflow import DAG
from airflow.operators.bash_operator import BashOperator
from airflow.operators.python_operator import PythonOperator
from airflow.utils.dates import days_ago
from datetime import timedelta

import pymysql.cursors
import pandas as pd
import requests


class Config:
    MYSQL_HOST = '#######'
    MYSQL_PORT = ###
    MYSQL_USER = '######'
    MYSQL_PASSWORD = '####'
    MYSQL_DB = '#####'
    MYSQL_CHARSET = '####'

# For PythonOperator

def get_data_from_db():

    # Connect to the database
    connection = pymysql.connect(host=Config.MYSQL_HOST,
                                port=Config.MYSQL_PORT,
                                user=Config.MYSQL_USER,
                                password=Config.MYSQL_PASSWORD,
                                db=Config.MYSQL_DB,
                                charset=Config.MYSQL_CHARSET,
                                cursorclass=pymysql.cursors.DictCursor)


    with connection.cursor() as cursor:
        # Read a single record
        sql = "SELECT * from online_retail"
        cursor.execute(sql)
        result_retail = cursor.fetchall()


    retail = pd.DataFrame(result_retail)
    retail['InvoiceTimestamp'] = pd.to_datetime(retail['InvoiceDate'])
    retail['InvoiceDate'] = pd.to_datetime(retail['InvoiceDate']).dt.date
    retail.to_csv("/home/airflow/gcs/data/retail_from_db.csv", index=False)
    

def get_data_from_api():
    url = "https://de-training-2020-7au6fmnprq-de.a.run.app/currency_gbp/all"
    response = requests.get(url)
    result_conversion_rate = response.json()

    conversion_rate = pd.DataFrame.from_dict(result_conversion_rate)
    conversion_rate = conversion_rate.reset_index().rename(columns={"index":"date"})

    conversion_rate['date'] = pd.to_datetime(conversion_rate['date']).dt.date
    conversion_rate.to_csv("/home/airflow/gcs/data/conversion_rate_from_api.csv", index=False)


def convert_to_thb():
    retail = pd.read_csv("/home/airflow/gcs/data/retail_from_db.csv")
    conversion_rate = pd.read_csv("/home/airflow/gcs/data/conversion_rate_from_api.csv")
    
    final_df = retail.merge(conversion_rate, how="left", left_on="InvoiceDate", right_on="date")

    final_df['THBPrice'] = final_df.apply(lambda x: x['UnitPrice'] * x['Rate'], axis=1)
    final_df.to_csv("/home/airflow/gcs/data/result.csv", index=False)


# Default Args

default_args = {
    'owner': 'ToEzBit',
    'depends_on_past': False,
    'start_date': days_ago(1),
    'email': ['airflow@example.com'],
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
    'schedule_interval': '@once',
}

# Create DAG

dag = DAG(
    'online_retail_w5',
    default_args=default_args,
    description='Pipeline for ETL online_retail data',
    schedule_interval=timedelta(days=1),
)

# Tasks

# db_ingest
t1 = PythonOperator(
    task_id='db_ingest',
    python_callable=get_data_from_db,
    dag=dag,
)

# api_call
t2 = PythonOperator(
    task_id='api_call',
    python_callable=get_data_from_api,
    dag=dag,
)

# convert_currency
t3 = PythonOperator(
    task_id='convert_currency',
    python_callable=convert_to_thb,
    dag=dag,
)

#  load to BigQuery
t4 = BashOperator(
    task_id='bq_load',
    bash_command='bq load --source_format=CSV --autodetect \
            [result].[Dataclean] \
            gs://[Dataflow]/data/result.csv',
    dag=dag,
)

#  Dependencies

[t1, t2] >> t3 >> t4
