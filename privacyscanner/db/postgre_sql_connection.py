import csv
import pandas as pd
import psycopg2
import psycopg2.extras

from io import StringIO
from privacyscanner.db.utils import remove_url_prefix, parse_dsn_dict_from_string


class PostgreSQLConnection:

    def __init__(self, db_config: dict or str):
        """Differentiates between two types of Data Source Names (DSNs): One using a SSL-certificate and username/
           password combo for authentication (designated for remote hosts) and one using just using username/password
           (designated for localhost authentication). If the DSN is provided as string, it is parsed to a dictionary and
           then re-built. This is due to compatibility with the privacyscanner config since the DSN is provided as a
           string there, while the original standalone insert application worked with dicts."""
        if type(db_config) == str:
            db_config = parse_dsn_dict_from_string(dsn_str=db_config)
        if 'sslkey' in db_config:
            self.db_dsn = 'host={host} dbname={dbname} user={user} \
                password={password} sslkey={sslkey} sslcert={sslcert} \
                    sslrootcert={sslrootcert} sslmode={sslmode}'.format(**db_config)
        else:
            self.db_dsn = 'host=localhost dbname={dbname} user={user} \
                password={password}'.format(**db_config)
        self.conn = psycopg2.connect(self.db_dsn)
        self.cursor = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    def execute_query(self, query_string: str, column_list: list) -> list:
        """Executes a hard-coded query string and uses the names provided in column_list as as keys in the resulting
           list of dictionaries."""
        self.cursor.execute(query_string)
        results = [
            dict(zip(column_list, element)) for element in self.cursor.fetchall()
        ]
        self.conn.commit()
        return results

    def insert_df_to_db(self, df: pd.DataFrame, table_name: str) -> None:
        """Inserts a dataframe into a table by using a String buffer because this is fast.
           See: https://github.com/NaysanSaran/pandas2postgresql/blob/master/notebooks/Psycopg2_Bulk_Insert_Speed_Benchmark.ipynb"""
        buffer = StringIO()
        df.to_csv(buffer, index=False, header=False, sep=";", quoting=csv.QUOTE_NONE)
        buffer.seek(0)
        string = buffer.getvalue()
        self.cursor.copy_from(buffer, table_name, sep=";", null='NULL')
        self.conn.commit()

    def query_live_db(self) -> list:
        """Returns a list of the sites in the database that have/will be scanned."""
        original_db_query = """
        select result, scanner_scaninfo.time_started, scanner_scaninfo.time_finished, sites_site.url
        from scanner_scan, scanner_scaninfo, sites_site
        where scanner_scan.id = scanner_scaninfo.scan_id and 
        scanner_scan.site_id = sites_site.id and 
        scan_module = 'cookiebanner';"""
        result = self.execute_query(original_db_query)
        return result

    def query_previous_scanresult(self, table_name: str) -> list:
        """Returns a list of scanresults for a given table name."""
        saved_results_query = """
        SELECT result 
        FROM {};
        """.format(table_name)
        result = self.execute_query(saved_results_query)
        return result

    def load_db_sitelist(self) -> pd.DataFrame:
        """Returns a list of sites that have been saved into the database."""
        query = '''
        SELECT * 
            FROM sites_site;'''
        result = self.execute_query(query, column_list=['id', 'url', 'is_private', 'latest_scan_id', 'date_created',
                                                        'num_views'])
        result = pd.DataFrame(result)
        if result.empty:
            return result
        else:
            result['url'] = result['url'].apply(remove_url_prefix)
            return result

    def close(self):
        """Closes the database connection."""
        self.conn.close()
