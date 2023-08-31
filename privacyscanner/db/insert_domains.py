import argparse
import base64
import os
import pandas as pd
import sys

from datetime import datetime
from glob import glob
from pathlib import Path

from privacyscanner.db.postgre_sql_connection import PostgreSQLConnection

LIST_PATH = os.sep.join([os.getcwd(), 'privacyscanner', 'scanning_lists'])


def _check_prerequisites() -> None:
    """Checks whether the folder with the scanning lists exists and is populated with at leas one file."""
    # If scanning list directory non-existent, quit
    if not os.path.exists(LIST_PATH):
        print('The path containing the input lists is non-existent: "{}"'.format(LIST_PATH))
        exit(-1)
    full_paths = [Path(f) for f in glob(str(LIST_PATH) + '/*') if os.path.isfile(f)]
    # If scanning list directory empty, quit
    if not full_paths:
        print('The path containing the input lists is empty: "{}"'.format(LIST_PATH))
        exit(0)


def _get_files(full_paths: list) -> list:
    """Returns the filenames for each full path provided as a list."""
    available_files = list()
    for full_path in full_paths:
        head, tail = os.path.split(full_path)
        available_files.append(tail)
    return available_files


def _read_file(full_path: str, number_of_entries: int = None) -> pd.DataFrame:
    """Opens a file to load it into the DB. Format should be simple list or CSV in the form of rank,domain ."""
    with open(full_path) as f:
        first_line = f.readline().strip()
    # If '.' present -> simple url list
    if ',' not in first_line:
        df = pd.read_csv(full_path, header=None)
        df.columns = ['domain']
    elif 'rank,domain' == first_line:
        df = pd.read_csv(full_path)
    else:
        df = pd.DataFrame(None)
    if number_of_entries:
        df = df.head(number_of_entries)
    return df


def gen_id():
    """Generates an ID for the sites in the DB."""
    return base64.b32encode(os.urandom(25)).decode().lower()


def create_insert_df(df: pd.DataFrame) -> pd.DataFrame:
    """Adapts the DataFrame so that it can be directly inserted into 'sites_sitelist'."""
    df = df[['domain']].copy()
    df['url'] = df['domain'].apply(lambda x: 'https://{}'.format(x))
    df['id'] = [gen_id() for i in df['domain']]
    df['is_private'] = 'f'
    df['latest_scan_id'] = 'NULL'
    df['date_created'] = datetime.now()
    df['num_views'] = 0
    df = df[['id', 'url', 'is_private', 'latest_scan_id', 'date_created', 'num_views']]
    df.reset_index()
    return df


def get_list_and_db_diff(db_df: pd.DataFrame, list_df: pd.DataFrame) -> pd.DataFrame:
    """Returns the difference between the DataFrame from the DB and the DataFrame from the loaded file."""
    diff_df = pd.concat([db_df, list_df]).drop_duplicates(subset=['url'], keep=False)
    return diff_df


def list_files(args: argparse.Namespace) -> None:
    """Prints all available scanning lists."""
    full_paths = [Path(f) for f in glob(str(LIST_PATH) + '/*') if os.path.isfile(f)]
    print(LIST_PATH)
    print(sys.path)
    print(os.path.curdir)
    available_files = _get_files(full_paths)
    file_string = ''.join('- {}\n'.format(file) for file in available_files)
    print('''The following scanning lists are available:\n{}'''.format(file_string[:-1]))
    exit(0)


def insert_list(args: argparse.Namespace) -> None:
    """Inserts a scanning list into the database."""
    file_path = os.sep.join([str(LIST_PATH), args.file])
    # If file not present, quit
    if not os.path.exists(file_path):
        print('File not found.')
        exit(-1)
    if args.number_of_entries:
        number_of_entries = args.number_of_entries
        df = _read_file(file_path, number_of_entries=number_of_entries)
    else:
        df = _read_file(file_path)
    if df.empty:
        print('''Scanning list not matching required format.
                Either a simple list in the form of:
                google.com
                netflix.com
                youtube.com
                    ...
                Or a CSV-file in the form of:
                rank,domain
                1,google.com
                2,netflix.com
                3,youtube.com
                    ...''')
        exit(0)
    from privacyscanner.scanner import load_config
    try:
        config = load_config(args.config)
        db_config = config['QUEUE_DB_DSN']
        conn = PostgreSQLConnection(db_config=db_config)
        result = conn.load_db_sitelist()
    except:
        print('Could not connect to database')
        exit(-1)
    if result.empty:
        print('No sites in the database.')
    else:
        print('The table is already populated with {} sites.'.format(len(result)))
        df = get_list_and_db_diff(db_df=result, list_df=df)
        if df.empty:
            print('The list contains no new sites that are not already in the database. Exiting.')
            exit(0)
        else:
            print('The script will insert {} additional sites into the database.'.format(len(df)))
    df = create_insert_df(df)
    try:
        conn.insert_df_to_db(df=df, table_name='sites_site')
        print('{} sites inserted.'.format(len(df)))
    except:
        print('Could not insert sites to database.')
        exit(-1)
    conn.close()
