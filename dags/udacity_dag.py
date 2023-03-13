from datetime import datetime, timedelta
import os
from airflow import DAG
from airflow.operators.dummy_operator import DummyOperator
from airflow.operators.subdag_operator import SubDagOperator
from airflow.operators import (StageToRedshiftOperator, LoadFactOperator,
                                LoadDimensionOperator, DataQualityOperator)
from helpers import SqlQueries
import configparser
from udacity_subdag import *

config = configparser.ConfigParser()
config.read('/home/workspace/airflow/config.cfg')
S3_BUCKET = config['AWS']['S3_BUCKET']
S3_SONG_KEY = config['AWS']['S3_SONG_KEY']
S3_LOG_KEY = config['AWS']['S3_LOG_KEY']
LOG_JSON_PATH = config['AWS']['LOG_JSON_PATH']
REGION = config['AWS']['REGION']
AWS_CREDENTIALS_ID = config['AWS']['AWS_CREDENTIALS_ID']
REDSHIFT_CONN_ID = config['AWS']['REDSHIFT_CONN_ID']

default_args = {
    'owner': 'udacity',
    'start_date': datetime(2019, 1, 12),
    'retry':3,
    'retry_delay':timedelta(minutes=5),
    'email_on_retry': False,
    'catchup': False,
}

dag = DAG('udacity_dag',
          default_args=default_args,
          description='Load and transform data in Redshift with Airflow',
          schedule_interval='@hourly'
        )

start_operator = DummyOperator(task_id='Begin_execution',  dag=dag)

stage_events_to_redshift = StageToRedshiftOperator(
    task_id='Stage_events',
    dag=dag,
    redshift_conn_id=REDSHIFT_CONN_ID,
    aws_credentials_id=AWS_CREDENTIALS_ID,
    table='staging_events',
    s3_bucket=S3_BUCKET,
    s3_key=S3_LOG_KEY,
    region=REGION,
    truncate=False,
    data_format=f"JSON '{LOG_JSON_PATH}'",
)

stage_songs_to_redshift = StageToRedshiftOperator(
    task_id='Stage_songs',
    dag=dag,
    redshift_conn_id=REDSHIFT_CONN_ID,
    aws_credentials_id=AWS_CREDENTIALS_ID,
    table='staging_songs',
    s3_bucket=S3_BUCKET,
    s3_key=S3_LOG_KEY,
    region=REGION,
    truncate=False,
    data_format="JSON 'auto'",
)

load_songplays_table = LoadFactOperator(
    task_id='Load_songplays_fact_table',
    dag=dag,
    postgres_conn_id=REDSHIFT_CONN_ID,
    sql=SqlQueries.songplay_table_insert,
    table='songplays',
    truncate=False,
)

load_dimension_table_task_id = 'Load_dim_table_subdag'
load_dimension_table = SubDagOperator(
    subdag=get_load_dimension_table(
        parent_dag_name='udacity_dag',
        task_id=load_dimension_table_task_id,
        default_args=default_args,
        postgres_conn_id=REDSHIFT_CONN_ID,
        sql_queries=[
            SqlQueries.user_table_insert,
            SqlQueries.song_table_insert,
            SqlQueries.artist_table_insert,
            SqlQueries.time_table_insert,
        ],
        tables=['users', 'songs', 'artists', 'time'],
        truncate_flags=[True]*4,
    ),
    dag=dag,
    task_id=load_dimension_table_task_id,
)

sparkify_tables = ['staging_events', 'staging_songs', 'songplays', 'users', 'songs', 'artists', 'time']
run_quality_checks = DataQualityOperator(
    task_id='Run_data_quality_checks',
    dag=dag,
    redshift_conn_id="redshift",
    tables=['songplays', 'users', 'songs', 'artists', 'time'],
)

end_operator = DummyOperator(task_id='Stop_execution', dag=dag)

start_operator >> stage_events_to_redshift
start_operator >> stage_songs_to_redshift
stage_events_to_redshift >> load_songplays_table
stage_songs_to_redshift >> load_songplays_table
load_songplays_table >> load_dimension_table
load_dimension_table >> run_quality_checks
run_quality_checks >> end_operator