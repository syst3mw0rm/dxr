import dxr.plugins
import csv
import os
from dxr.languages import language_schema

__all__ = dxr.plugins.indexer_exports()

PLUGIN_NAME = 'rust'

def pre_process(tree, env):
    print("rust-dxr pre-process")
    # Setup environment variables for using the rust-dxr tool
    # We'll store all the havested metadata in the plugins temporary folder.
    plugin_folder = os.path.join(tree.config.plugin_folder, PLUGIN_NAME)
    temp_folder = os.path.join(tree.temp_folder, 'plugins', PLUGIN_NAME)
    env['RUST']   = "/home/ncameron/rust/x86_64-unknown-linux-gnu/stage1/bin/rustc" #os.path.join(plugin_folder, 'rust-dxr')
    env['DXR_RUST'] = env['RUST']
    env['DXR_RUST_OBJECT_FOLDER']  = tree.object_folder
    env['DXR_RUST_TEMP_FOLDER']    = temp_folder


# We'll need more things in here at some point
schema = dxr.schema.Schema({
    # References to functions
    "function_refs": [
        ("refid", "INTEGER", True),      # ID of the function being referenced
        ("extent_start", "INTEGER", True),
        ("extent_end", "INTEGER", True),
        ("_location", True),
        ("_location", True, 'referenced'),
        ("_fkey", "refid", "functions", "id"),
        ("_index", "refid"),
    ],
    # References to variables
    "variable_refs": [
        ("refid", "INTEGER", True),      # ID of the variable being referenced
        ("extent_start", "INTEGER", True),
        ("extent_end", "INTEGER", True),
        ("_location", True),
        ("_location", True, 'referenced'),
        ("_fkey", "refid", "variables", "id"),
        ("_index", "refid"),
    ],
})


def post_process(tree, conn):
    print "rust-dxr post-process"

    print " - Adding tables"
    conn.executescript(schema.get_create_sql())

    print " - Processing files"
    temp_folder = os.path.join(tree.temp_folder, 'plugins', PLUGIN_NAME)
    #TODO one csv file per crate now
    for root, dirs, files in os.walk(temp_folder):
        if not root.startswith(temp_folder):
            print "Unexpected - not a subdirectory"
            return
        crate_name = root[len(temp_folder)+1:]

        for f in [f for f in files if f.endswith('.csv')]:
            process_csv(os.path.join(root, f), crate_name, conn)

    print " - Committing changes"
    # TODO do this every 10,000 lines
    conn.commit()

# file/record cache
files = {}

# TODO need to take into account the crate?
def get_file_id(file_name, conn):
    file_id = files.get(file_name, False)

    if file_id is not False:
        return file_id

    cur = conn.cursor()
    row = cur.execute("SELECT id FROM files where path=?", (file_name,)).fetchone()
    file_id = None
    if row:
        file_id = row[0]
    else:
        print "no file record for" + file_name
    files[file_name] = file_id
    return file_id

def process_csv(file_name, crate_name, conn):
    # TODO wrap all this in a try block
    f = open(file_name, 'r')
    parsed_iter = csv.reader(f)

    if file_name.endswith('fn_calls.csv'):
        for line in parsed_iter:
            process_fn_call(line, conn)
    elif file_name.endswith('fn_defs.csv'):
        for line in parsed_iter:
            process_function(line, conn)
    elif file_name.endswith('var_defs.csv'):
        for line in parsed_iter:
            process_variable(line, conn)
            pass
    elif file_name.endswith('var_refs.csv'):
        for line in parsed_iter:
            process_var_ref(line, conn)
            pass
    else:
        #TODO remove this
        print "unexpected file " + file_name

    f.close()

def execute_sql(conn, stmt):
    if stmt == None:
        return
    if isinstance(stmt, list):
        for elem in list:
            conn.execute(elem[0], elem[1])
    elif isinstance(stmt, tuple):
        try:
            conn.execute(stmt[0], stmt[1])
        except Exception:
            print "Could not execute " + str(stmt)
            raise
    else:
        conn.execute(stmt)

def process_function(line, conn):
    # file, start row, start col, start extent, end row, end col, end extent, qual_name, fn id
    args = {}
    args['id'] = int(line[9])
    args['name'] = line[8].split('::')[-1]
    args['qualname'] = line[8]
    args['language'] = 'rust'
    args['args'] = ''
    args['type'] = ''
    args['extent_start'] = int(line[4])
    args['extent_end'] = int(line[7])
    args['file_id'] = get_file_id(line[1], conn)
    args['file_line'] = int(line[2])
    args['file_col'] = int(line[3])

    execute_sql(conn, language_schema.get_insert_sql('functions', args))

def process_fn_call(line, conn):
    # file, start row, start col, start extent, end row, end col, end extent, fn id
    args = {}
    args['refid'] = int(line[8])
    args['extent_start'] = int(line[4])
    args['extent_end'] = int(line[7])
    args['file_id'] = get_file_id(line[1], conn)
    args['file_line'] = int(line[2])
    args['file_col'] = int(line[3])

    execute_sql(conn, schema.get_insert_sql('function_refs', args))
    
def process_variable(line, conn):
    # file, start row, start col, start extent, end row, end col, end extent, id, name
    args = {}
    args['id'] = int(line[8])
    args['name'] = line[9]
    args['qualname'] = line[9] # TODO we don't have a qualname for variables, not sure if we need one
    args['language'] = 'rust'
    args['type'] = ''
    args['value'] = '' # XXX for const items etc., we can show the value as a tooltip
    args['extent_start'] = int(line[4])
    args['extent_end'] = int(line[7])
    args['file_id'] = get_file_id(line[1], conn)
    args['file_line'] = int(line[2])
    args['file_col'] = int(line[3])

    execute_sql(conn, language_schema.get_insert_sql('variables', args))

def process_var_ref(line, conn):
    # file, start row, start col, start extent, end row, end col, end extent, def id
    args = {}
    args['refid'] = int(line[8])
    args['extent_start'] = int(line[4])
    args['extent_end'] = int(line[7])
    args['file_id'] = get_file_id(line[1], conn)
    args['file_line'] = int(line[2])
    args['file_col'] = int(line[3])

    execute_sql(conn, schema.get_insert_sql('variable_refs', args))
