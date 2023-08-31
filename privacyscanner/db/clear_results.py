import argparse

from privacyscanner.db.postgre_sql_connection import PostgreSQLConnection


def main(args: argparse.Namespace):
    from privacyscanner.scanner import load_config
    # Prompt before clearing DB
    while True:
        answer = input('This will clear all scanresults, queued scans and inserted sites from the database. '
                       'Proceed (y\\n)? ')
        if answer == 'y':
            print('Clearing database...')
            break
        elif answer == 'n':
            print('Exiting.')
            exit(0)
        else:
            print('Invalid answer.')
    try:
        config = load_config(args.config)
        db_config = config['QUEUE_DB_DSN']
        conn = PostgreSQLConnection(db_config=db_config)
        query_string = '''TRUNCATE TABLE scanner_scaninfo, scanner_logentry, scanner_scanjob, scanner_scan, 
                          sites_site CASCADE;'''
        conn.cursor.execute(query_string)
        conn.conn.commit()
        conn.close()
    except Exception as e:
        print('Could not clear database.')
        print(e)
        exit(-1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    main(parser.parse_args())
