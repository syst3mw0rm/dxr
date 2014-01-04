import dxr.plugins
import csv
import os
from dxr.languages import language_schema

__all__ = dxr.plugins.indexer_exports()

PLUGIN_NAME = 'rust'
PATH_TO_RUSTC = "/home/ncameron/rust/x86_64-unknown-linux-gnu/stage1/bin/rustc"

def pre_process(tree, env):
    print("rust-dxr pre-process")
    # Setup environment variables for using the rust-dxr tool
    # We'll store all the havested metadata in the plugins temporary folder.
    plugin_folder = os.path.join(tree.config.plugin_folder, PLUGIN_NAME)
    temp_folder = os.path.join(tree.temp_folder, 'plugins', PLUGIN_NAME)
    env['RUST'] = PATH_TO_RUSTC + " --save-analysis" #TODO - do people actually use $RUST?
    env['DXR_RUST_OBJECT_FOLDER'] = tree.object_folder
    env['DXR_RUST_TEMP_FOLDER'] = temp_folder


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
    # References to types
    "type_refs": [
        ("refid", "INTEGER", True),      # ID of the type being referenced
        ("extent_start", "INTEGER", True),
        ("extent_end", "INTEGER", True),
        ("_location", True),
        ("_location", True, 'referenced'),
        ("_fkey", "refid", "types", "id"),
        ("_index", "refid"),
    ],
})


def post_process(tree, conn):
    print "rust-dxr post-process"

    print " - Adding tables"
    conn.executescript(schema.get_create_sql())

    print " - Processing files"
    temp_folder = os.path.join(tree.temp_folder, 'plugins', PLUGIN_NAME)
    for root, dirs, files in os.walk(temp_folder):
        for f in [f for f in files if f.endswith('.csv')]:
            crate_name = root[:f.index('.csv')]
            process_csv(os.path.join(root, f), crate_name, conn)

        # don't need to look in sub-directories
        break

    fixup_struct_ids(conn)

    print " - Committing changes"
    # TODO do this every 10,000 lines
    conn.commit()

# file/record cache
files = {}
# map from ctor_id to def_id for structs
# The domains should be disjoint
ctor_ids = {}

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
    # the first item on a line is the kind of entity we are dealing with and so
    # we can use that to dispatch to the appropriate process_... function
    for line in parsed_iter:
        # convert key:value pairs to a map
        args = {}
        for i in range(1, len(line), 2):
            args[line[i]] = line[i + 1]

        globals()['process_' + line[0]](args, conn)

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

def process_function(args, conn):
    args['name'] = args['qualname'].split('::')[-1]
    args['language'] = 'rust'
    args['args'] = ''
    args['type'] = ''
    args['file_id'] = get_file_id(args['file_name'], conn)

    execute_sql(conn, language_schema.get_insert_sql('functions', args))

def process_fn_call(args, conn):
    args['file_id'] = get_file_id(args['file_name'], conn)

    execute_sql(conn, schema.get_insert_sql('function_refs', args))
    
def process_variable(args, conn):
    args['language'] = 'rust'
    args['type'] = ''
    args['value'] = '' # XXX for const items etc., we can show the value as a tooltip
    args['file_id'] = get_file_id(args['file_name'], conn)

    execute_sql(conn, language_schema.get_insert_sql('variables', args))

def process_var_ref(args, conn):
    args['file_id'] = get_file_id(args['file_name'], conn)

    execute_sql(conn, schema.get_insert_sql('variable_refs', args))

def process_struct(args, conn):
    # Used for fixing up the refid in fixup_struct_ids
    if args['ctor_id'] != '0':
        ctor_ids[args['ctor_id']] = args['id']

    args['name'] = args['qualname'].split('::')[-1]
    args['file_id'] = get_file_id(args['file_name'], conn)
    args['kind'] = 'struct'
    args['language'] = 'rust'

    execute_sql(conn, language_schema.get_insert_sql('types', args))

def process_struct_ref(args, conn):
    process_type_ref(args, conn)

def process_type_ref(args, conn):
    args['file_id'] = get_file_id(args['file_name'], conn)

    execute_sql(conn, schema.get_insert_sql('type_refs', args))

def fixup_struct_ids(conn):
    # Sadness. Structs have an id for their definition and an id for their ctor.
    # Sometimes, we get one, sometimes the other. This method fixes up any refs
    # to the latter into refs to the former.
    for ctor in ctor_ids.keys():
        conn.execute('UPDATE type_refs SET refid=? WHERE refid=?', (ctor_ids[ctor],ctor))
