import argparse
import datetime
import json
import sys

import pandas as pd

from privacyscanner.db.postgre_sql_connection import PostgreSQLConnection
from privacyscanner.db.utils import module_exists


def _get_max_sequence_id(conn: PostgreSQLConnection, sequence_name: str) -> int:
    """Returns the max id present in a sequence."""
    query_string = 'SELECT LAST_VALUE FROM {};'.format(sequence_name)
    conn.cursor.execute(query_string)
    result = conn.cursor.fetchall()
    if result:
        return result[0][0]
    else:
        return 0


def _set_sequence_id(conn: PostgreSQLConnection, sequence_name: str, sequence_number: int) -> None:
    """Sets the id of a sequence."""
    query_string = "select setval('{}', {});".format(sequence_name, sequence_number)
    conn.cursor.execute(query_string)


def _create_id_sequence(last_id: int, number_of_entries: int) -> list:
    """Create an id sequence based on the last id present in the table and the number of entries to enter."""
    list_of_ids = list()
    for i in range(last_id + 1, last_id + number_of_entries + 1):
        list_of_ids.append(i)
    return list_of_ids


def _create_scanner_scan_df(df: pd.DataFrame, scanner_scan_max_id: int, number_of_entries: int) -> pd.DataFrame:
    """Accepts a df containing id and url and converts it into a df to be inserted into "scanner_scan"."""
    df['time_started'] = datetime.datetime.now()
    df['time_finished'] = 'NULL'
    df['is_latest'] = 't'
    result = [json.dumps({'site_url': url}) for url in df['url']]
    df['result'] = result
    id_column = _create_id_sequence(scanner_scan_max_id, number_of_entries)
    df['id'] = id_column
    df = df[['id', 'time_started', 'time_finished', 'result', 'is_latest', 'site_id']]
    df.reset_index()
    return df


def _create_scanner_scaninfo_df(df: pd.DataFrame, scan_modules: str) -> pd.DataFrame:
    """Accepts a df containing ids and scan_ids and converts it into a df to be inserted into "scanner_scaninfo"."""
    df['scan_module'] = str(scan_modules)
    df['scan_host'] = 'NULL'
    df['time_started'] = 'NULL'
    df['time_finished'] = 'NULL'
    df['num_tries'] = 0
    df = df[['id', 'scan_module', 'scan_host', 'time_started', 'time_finished', 'scan_id', 'num_tries']]
    return df


def _create_scanner_scanjob_df(df: pd.DataFrame, scan_modules: str) -> pd.DataFrame:
    """Create a df to be inserted into scanner_scanjob. Takes a df with ids and scan_ids."""
    df['scan_module'] = scan_modules
    df['priority'] = 0
    df['dependency_order'] = 1
    df['not_before'] = 'NULL'
    df = df[['id', 'scan_module', 'priority', 'dependency_order', 'scan_id', 'not_before']]
    return df


def main(args: argparse.Namespace):
    from privacyscanner.scanner import load_config
    scan_modules = args.module
    config = load_config(args.config)
    db_config = config['QUEUE_DB_DSN']

    scan_module_exists, module_name, list_of_available_modules = module_exists(config, scan_modules)
    if not scan_module_exists:
        print('''Error: The scan module "{0}" does not seem to exist. 
        The following modules are available: {1}'''.format(module_name,
                                                           ''.join('{}, '.format(module_name) for module_name in
                                                                   list_of_available_modules)[0:-2]))
        exit(-1)
    try:
        conn = PostgreSQLConnection(db_config=db_config)

        # Get the sequence numbers of the tables
        # scanner_scan_id_seq
        scanner_scan_id_seq_max = _get_max_sequence_id(conn, 'scanner_scan_id_seq')

        # scanner_scan df
        df = pd.DataFrame(conn.execute_query(query_string='SELECT id, url FROM sites_site;',
                                             column_list=['site_id', 'url']))
        if len(df) == 0:
            print('No available sites. Existing')
            sys.exit(0)
        scanner_scan_df = _create_scanner_scan_df(df, scanner_scan_id_seq_max, len(df))
        scanner_scan_id_seq_max_new = scanner_scan_df['id'].iloc[-1]

        # scanner_scaninfo df
        df['scan_id'] = df['id']
        df = df[['id', 'scan_id']].copy()
        scanner_scaninfo_df = _create_scanner_scaninfo_df(df, scan_modules)
        # scanner_scanjob df
        scanner_scanjob_df = _create_scanner_scanjob_df(df, scan_modules)

        # Insert dataframes
        conn.insert_df_to_db(scanner_scan_df, 'scanner_scan')
        conn.insert_df_to_db(scanner_scaninfo_df, 'scanner_scaninfo')
        conn.insert_df_to_db(scanner_scanjob_df, 'scanner_scanjob')

        # Update sequence ids
        _set_sequence_id(conn, 'scanner_scan_id_seq', scanner_scan_id_seq_max_new)
        _set_sequence_id(conn, 'scanner_scaninfo_id_seq', scanner_scan_id_seq_max_new)
        _set_sequence_id(conn, 'scanner_scanjob_id_seq', scanner_scan_id_seq_max_new)

        conn.close()
    except Exception as e:
        print('Could not insert sites to database.')
        print(e)
        exit(-1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    main(parser.parse_args())
