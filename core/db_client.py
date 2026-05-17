# ------------------------------------------------------------------------------
# DB CLIENT
# ------------------------------------------------------------------------------
# Database client for executing queries against SQL Server and ClickHouse.
# Supports multiple database backends.
# ------------------------------------------------------------------------------
import pandas as pd
import pyodbc
import clickhouse_connect
from core.utils import env


def sql_server_query(query):
    conn_str = (
        f"DRIVER={{ODBC Driver 17 for SQL Server}};"
        f"SERVER={env('SQLSERVER_HOST')};"
        f"DATABASE={env('SQLSERVER_DB')};"
        f"UID={env('SQLSERVER_USER')};"
        f"PWD={env('SQLSERVER_PASSWORD')};"
    )

    conn = pyodbc.connect(conn_str)
    df = pd.read_sql(query, conn)
    conn.close()

    return df


def clickhouse_query(query):

    client = clickhouse_connect.get_client(
        host=env("CLICKHOUSE_HOST"),
        username=env("CLICKHOUSE_USER"),
        password=env("CLICKHOUSE_PASSWORD"),
        database=env("CLICKHOUSE_DB")
    )

    df = client.query_df(query)

    return df


def run_query(db_type, query):

    if db_type == "sqlserver":
        return sql_server_query(query)

    if db_type == "clickhouse":
        return clickhouse_query(query)

    raise Exception("Invalid db type")
