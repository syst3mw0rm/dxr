import dxr.plugins
import csv
import os
from dxr.languages import language_schema

__all__ = dxr.plugins.indexer_exports()

PLUGIN_NAME = 'rust'
PATH_TO_RUSTC = "/home/ncameron/rust/x86_64-unknown-linux-gnu/stage1/bin/rustc"
RUST_DXR_FLAG = " --save-analysis"

def pre_process(tree, env):
    print("rust-dxr pre-process")
    # Setup environment variables for using the rust-dxr tool
    # We'll store all the havested metadata in the plugins temporary folder.
    plugin_folder = os.path.join(tree.config.plugin_folder, PLUGIN_NAME)
    temp_folder = os.path.join(tree.temp_folder, 'plugins', PLUGIN_NAME)
    env['RUST'] = PATH_TO_RUSTC + RUST_DXR_FLAG
    if 'RUSTFLAGS' in env:
        env['RUSTFLAGS'] += RUST_DXR_FLAG
    else:
        env['RUSTFLAGS'] = RUST_DXR_FLAG
    env['DXR_RUST_OBJECT_FOLDER'] = tree.object_folder
    env['DXR_RUST_TEMP_FOLDER'] = temp_folder


schema = dxr.schema.Schema({
    # modules
    "modules": [
        ("id", "INTEGER", False),
        ("name", "VARCHAR(256)", False),
        ("qualname", "VARCHAR(256)", False),
        ("def_file", "INTEGER", False),
        ("extent_start", "INTEGER", True),
        ("extent_end", "INTEGER", True),
        ("_location", True),
        ("_key", "id"),
        ("_index", "qualname"),
    ],
    # References to modules
    "module_refs": [
        ("refid", "INTEGER", False),      # ID of the module referenced
        ("aliasid", "INTEGER", False),    # ID of the alias being referenced (if it exists)
        ("extent_start", "INTEGER", True),
        ("extent_end", "INTEGER", True),
        ("qualname", "VARCHAR(256)", False), # Used when we don't have a refid from rustc
        ("_location", True),
        ("_location", True, 'referenced'),
        ("_fkey", "refid", "modules", "id"),
        ("_index", "refid"),
    ],
    # module aliases (aka use items)
    "module_aliases": [
        ("id", "INTEGER", False),
        ("refid", "INTEGER", False),      # ID of the module being aliased
        ("name", "VARCHAR(256)", False),
        ("qualname", "VARCHAR(256)", False),
        ("extent_start", "INTEGER", True),
        ("extent_end", "INTEGER", True),
        ("_location", True),
        ("_key", "id"),
        ("_fkey", "refid", "modules", "id"),
        ("_index", "qualname"),
    ],
    # References to functions
    "function_refs": [
        ("refid", "INTEGER", True),      # ID of the function defintion, if it exists
        ("declid", "INTEGER", True),     # ID of the funtion declaration, if it exists
        ("extent_start", "INTEGER", True),
        ("extent_end", "INTEGER", True),
        ("_location", True),
        ("_location", True, 'referenced'),
        ("_fkey", "refid", "functions", "id"),
        ("_fkey", "declid", "functions", "id"),
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
        ("qualname", "VARCHAR(256)", False), # Used when we don't have a refid from rustc
        ("_location", True),
        ("_location", True, 'referenced'),
        ("_fkey", "refid", "types", "id"),
        ("_index", "refid"),
    ],
    # impls
    "impl_defs": [
        ("id", "INTEGER", False),
        ("refid", "INTEGER", False),
        ("extent_start", "INTEGER", True),
        ("extent_end", "INTEGER", True),
        ("_location", True),
        # id is not a primary key - an impl can have two representations - one
        # for the trait and one for the struct.
        ("_fkey", "refid", "types", "id"),
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

    print " - Updating references"
    fixup_struct_ids(conn)
    fixup_sub_mods(conn)

    print " - Generating inheritance graph"
    generate_inheritance(conn)

    print " - Committing changes"
    conn.commit()

# file/record cache
files = {}
# map from ctor_id to def_id for structs
# The domains should be disjoint
ctor_ids = {}

# map from the id of a module to the id of its parent (or 0), if there is no parent
# TODO are we going to use this? If not remove stuff from dxr.rs too
mod_parents = {}

# list of (base, derived) trait ids
inheritance = []

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
    try:
        f = open(file_name, 'rb')
        parsed_iter = csv.reader(f)
        # the first item on a line is the kind of entity we are dealing with and so
        # we can use that to dispatch to the appropriate process_... function
        limit = 0
        for line in parsed_iter:
            # convert key:value pairs to a map
            args = {}
            for i in range(1, len(line), 2):
                args[line[i]] = line[i + 1]

            globals()['process_' + line[0]](args, conn)

            limit += 1
            if limit > 10000:
                print " - Committing changes (eager commit)"
                conn.commit()
                limit = 0
    except Exception:
        print file_name, line
        raise
    finally:
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

def process_method_decl(args, conn):
    args['name'] = args['qualname'].split('::')[-1]
    args['language'] = 'rust'
    args['args'] = ''
    args['type'] = ''
    args['file_id'] = get_file_id(args['file_name'], conn)

    # TODO either share code with process_function, or store the decl somewhere else
    execute_sql(conn, language_schema.get_insert_sql('functions', args))

def process_fn_call(args, conn):
    args['file_id'] = get_file_id(args['file_name'], conn)

    execute_sql(conn, schema.get_insert_sql('function_refs', args))

def process_method_call(args, conn):
    args['file_id'] = get_file_id(args['file_name'], conn)
    if args['refid'] == '0':
        args['refid'] = None

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

    # TODO add to scopes too
    execute_sql(conn, language_schema.get_insert_sql('types', args))

def process_trait(args, conn):
    args['name'] = args['qualname'].split('::')[-1]
    args['file_id'] = get_file_id(args['file_name'], conn)
    args['kind'] = 'trait'
    args['language'] = 'rust'

    # TODO add to scopes too
    execute_sql(conn, language_schema.get_insert_sql('types', args))

def process_struct_ref(args, conn):
    if 'qualname' not in args:
        args['qualname'] = ''
    process_type_ref(args, conn)

def process_module(args, conn):
    mod_parents[int(args['id'])] = int(args['parent'])

    args['name'] = args['qualname'].split('::')[-1]
    args['language'] = 'rust'
    args['file_id'] = get_file_id(args['file_name'], conn)
    args['def_file'] = get_file_id(args['def_file'], conn)

    # TODO add to scopes too
    execute_sql(conn, schema.get_insert_sql('modules', args))

def process_mod_ref(args, conn):
    args['file_id'] = get_file_id(args['file_name'], conn)
    args['aliasid'] = 0

    execute_sql(conn, schema.get_insert_sql('module_refs', args))

def process_module_alias(args, conn):
    args['file_id'] = get_file_id(args['file_name'], conn)
    args['qualname'] = args['file_name'] + "$" + args['name']

    execute_sql(conn, schema.get_insert_sql('module_aliases', args))

def process_impl(args, conn):
    args['file_id'] = get_file_id(args['file_name'], conn)

    # TODO add to scopes too
    execute_sql(conn, schema.get_insert_sql('impl_defs', args))

def process_typedef(args, conn):
    args['name'] = args['qualname'].split('::')[-1]
    args['file_id'] = get_file_id(args['file_name'], conn)
    args['kind'] = 'typedef'
    args['language'] = 'rust'

    execute_sql(conn, language_schema.get_insert_sql('types', args))

# When we have a path like a::b::c, we want to have info for a and a::b.
# Unfortunately Rust does not give us much info, so we have to
# construct it ourselves from the module info we have.
# We have the qualname for the module (e.g, a or a::b) but we do not have
# the refid
def fixup_sub_mods(conn):
    fixup_sub_mods_impl(conn, 'modules', 'module_refs')
    # paths leading up to a static method have a module path, then a type at the
    # so we have to fixup the type in the same way as we do modules.
    fixup_sub_mods_impl(conn, 'types', 'type_refs')

def fixup_sub_mods_impl(conn, table_name, table_ref_name):
    # First create refids for module refs whose qualnames match the qualname of
    # the module (i.e., no aliases).
    conn.execute("""
        UPDATE %(ref)s SET
            refid=(SELECT id FROM %(tab)s WHERE %(tab)s.qualname = %(ref)s.qualname)
        WHERE refid=0 AND
            (SELECT id FROM %(tab)s WHERE %(tab)s.qualname = %(ref)s.qualname) IS NOT NULL
        """%{'tab':table_name,'ref':table_ref_name})

    if table_name == 'modules':
        # Next account for where the path is an aliased modules e.g., alias::c,
        # where c is already accounted for.
        # We can't do all this in one statement because sqlite does not have joins.
        cur = conn.execute("""
            SELECT refs.extent_start, module_aliases.id, modules.id,
               module_aliases.name, modules.name, modules.qualname,
               (SELECT path FROM files WHERE files.id = refs.file_id)
            FROM module_refs AS refs, module_aliases, modules
            WHERE refs.refid = 0 AND
               refs.file_id = module_aliases.file_id AND
               module_aliases.name = refs.qualname AND
               modules.id = module_aliases.refid
            """)

        for ex_start, aliasid, refid, name, mod_name, qualname, file_name in cur:
            # Aliases only have file scope, but we don't need to qualify purely
            # truncating aliases (the implicit kind).
            if name != mod_name:
                qualname = file_name + "$" + name
            conn.execute("""
                UPDATE module_refs SET
                   refid = ?,
                   aliasid = ?,
                   qualname = ?
                WHERE extent_start=?
                """,
                (refid, aliasid, qualname, ex_start))

    # And finally, the most complex case where the path is of the form
    # alias::b::c (this subsumes the above case, but I separate them out because
    # this LIKE query is probably heinously slow).

    # Note that in the following there are two modules and their qualnames - in
    # the first query the module is the one the alias refers to, in the second
    # it is the one which the whole path refers to.
    cur = conn.execute("""
        SELECT refs.extent_start,
            module_aliases.name, modules.name, modules.qualname, refs.qualname,
            (SELECT path FROM files WHERE files.id = refs.file_id)
        FROM %s as refs, module_aliases, modules
        WHERE refs.refid = 0 AND
            refs.file_id = module_aliases.file_id AND
            refs.qualname LIKE module_aliases.name || '%%' AND
            modules.id = module_aliases.refid
        """%table_ref_name)
    for ex_start, alias_name, mod_name, qualname, ref_name, file_name in cur:
        no_alias = ref_name.replace(alias_name, qualname)
        cur = conn.execute("""
            SELECT id, qualname
            FROM modules
            WHERE qualname = ?
            """,
            (no_alias, ))
        mod = cur.fetchone()
        if mod:
            (refid, qualname) = mod
            conn.execute("""
                UPDATE %s SET
                   refid = ?,
                   qualname = ?
                WHERE extent_start=?
                """%table_ref_name,
                (refid, qualname, ex_start))

def fixup_struct_ids(conn):
    # Sadness. Structs have an id for their definition and an id for their ctor.
    # Sometimes, we get one, sometimes the other. This method fixes up any refs
    # to the latter into refs to the former.
    for ctor in ctor_ids.keys():
        conn.execute('UPDATE type_refs SET refid=? WHERE refid=?', (ctor_ids[ctor],ctor))

def process_type_ref(args, conn):
    args['file_id'] = get_file_id(args['file_name'], conn)
    if 'qualname' not in args:
        args['qualname'] = ''

    execute_sql(conn, schema.get_insert_sql('type_refs', args))

def process_inheritance(args, conn):
    inheritance.append((args['base'], args['derived']))

# compute the transitive closure of the inheritance graph and save it to the db
def generate_inheritance(conn):
    for (base, deriv) in inheritance:
        conn.execute("INSERT OR IGNORE INTO impl(tbase, tderived, inhtype) VALUES (?, ?, 'direct')",
                     (base, deriv))

    # transitive inheritance
    closure = set(inheritance)
    while True:
        next_set = set([(b,dd) for (b,d) in closure for (bb,dd) in closure if d == bb])
        next_set |= closure

        if next_set == closure:
            break

        closure = next_set

    for (base, deriv) in closure:
        if (base, deriv) not in inheritance:
            conn.execute("INSERT OR IGNORE INTO impl(tbase, tderived, inhtype) VALUES (?, ?, NULL)",
                         (base, deriv))