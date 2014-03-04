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
        ("location", "VARCHAR(256)", True), # only used for extern mod
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
        ("scopeid", "INTEGER", True),    # ID of the scope in which the call occurs
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
    # impls
    "impl_defs": [
        ("id", "INTEGER", False),
        ("refid", "INTEGER", False),
        ("extent_start", "INTEGER", True),
        ("extent_end", "INTEGER", True),
        ("_location", True),
        # id is not a primary key - an impl can have two representations - one
        # for the trait and on for the struct.
        ("_fkey", "refid", "types", "id"),
    ],
    # We use a simpler version of the callgraph than the Clang plugin - there is
    # no targets table, and callers maps a caller to all possible callees.
    "callers": [
        ("callerid", "INTEGER", False), # The function in which the call occurs
        ("targetid", "INTEGER", False), # The target of the call
        ("_key", "callerid", "targetid"),
        ("_fkey", "callerid", "functions", "id")
    ],
    # Used for looking links for extern mods
    "extern_locations": [
        ("location", "VARCHAR(256)", False),
        ("docurl", "VARCHAR(256)", True),
        ("srcurl", "VARCHAR(256)", True),
        ("dxrurl", "VARCHAR(256)", True),
        ("_key", "location"),
    ],
    # indexed crates
    "crates": [
        ("name", "VARCHAR(256)", False),
        ("extent_start", "INTEGER", True),
        ("extent_end", "INTEGER", True),
        ("_location", True),
        ("_key", "name"),
    ],
    # items in other crates
    "unknowns": [
        ("id", "INTEGER", False),
        ("crate", "VARCHAR(256)", False),
        ("_key", "id"),
        ("_fkey", "crate", "crates", "name"),
    ],
    # References to items in other crates
    "unknown_refs": [
        ("refid", "INTEGER", False),
        ("extent_start", "INTEGER", False),
        ("extent_end", "INTEGER", False),
        ("_location", True),
        ("_location", True, 'referenced'),
        ("_fkey", "refid", "unknowns", "id"),
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
            process_csv(os.path.join(root, f), conn)

        # don't need to look in sub-directories
        break

    print " - Updating references"
    fixup_struct_ids(conn)
    fixup_sub_mods(conn)

    print " - Generating inheritance graph"
    generate_inheritance(conn)
    generate_callgraph(conn)

    print " - Generating crate info"
    generate_locations(conn)

    print " - Committing changes"
    conn.commit()

# file/record cache
files = {}
# map from ctor_id to def_id for structs
# The domains should be disjoint
ctor_ids = {}

# map from the id of a module to the id of its parent (or 0), if there is no parent
# TODO are we going to use this? it can be saved as scopeid in modules like we do
# with other scopes
mod_parents = {}

# list of (base, derived) trait ids
inheritance = []

# maps crate-local crate nums to global crate names and module ids
crate_map = {}

# We know these crates come from the rust distribution (probably, the user could
# override that, but lets assume for now...).
std_libs = ['std', 'extra', 'native', 'green', 'syntax', 'rustc', 'rustpkg', 'rustdoc', 'rustuv']
# These are the crates used in the current crate and indexed by DXR in the
# current run.
local_libs = []

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

def process_csv(file_name, conn):
    global crate_map
    crate_map = {}

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

next_id = 0;
id_map = {}

def get_next_id():
    global next_id
    next_id += 1
    return next_id

# maps a crate name and a node number to a globally unique id
def find_id_in(crate, node):
    global id_map

    if node == '0':
        return 0

    if (crate, node) not in id_map:
        result = get_next_id()
        # Our IDs are SQLite INTEGERS which are 64bit, so we are unlikely to overflow.
        # Python ints do not overflow.
        id_map[(crate, node)] = result
        return result

    return id_map[(crate, node)]

#TODO delete me
def find_id(crate, node):
    x = find_id_in(crate, node)
    #print crate, node, x
    return x

# XXX this feels a little bit fragile...
def convert_ids(args, conn):
    def convert(k, v):
        if k.endswith('crate'):
            return -1
        elif k == 'ctor_id' or k == 'aliasid':
            return v
        elif k == 'id' or k == 'scopeid':
            return find_id(crate_map['0'][0], v)
        elif k.endswith('id') or k == 'base' or k == 'derived':
            return find_id(crate_map[args[k + 'crate']][0], v)
        else:
            return v

    new_args = {k: convert(k, v) for k, v in args.items() if not k.endswith('crate')}
    new_args['file_id'] = get_file_id(args['file_name'], conn)
    return new_args

# Returns True if the refid in the args points to an item in an external crate.
def add_external_item(args, conn):
    node, crate = args['refid'], args['refidcrate']
    crate = crate_map[crate][0]
    if crate in local_libs or not node:
        return False

    requires_item = (crate, node) not in id_map
    execute_sql(conn, schema.get_insert_sql('unknown_refs', convert_ids(args, conn)))

    if not requires_item:
        return True

    item_args = {}
    item_args['id'] = find_id(crate, node)
    item_args['crate'] = crate
    execute_sql(conn, schema.get_insert_sql('unknowns', item_args))
    return True

def process_function(args, conn):
    args['name'] = args['qualname'].split('::')[-1]
    args['language'] = 'rust'
    args['args'] = ''
    args['type'] = ''

    execute_sql(conn, language_schema.get_insert_sql('functions', convert_ids(args, conn)))

def process_method_decl(args, conn):
    args['name'] = args['qualname'].split('::')[-1]
    args['language'] = 'rust'
    args['args'] = ''
    args['type'] = ''

    # TODO either share code with process_function, or store the decl somewhere else
    execute_sql(conn, language_schema.get_insert_sql('functions', convert_ids(args, conn)))

def process_fn_call(args, conn):
    if add_external_item(args, conn):
        return;

    execute_sql(conn, schema.get_insert_sql('function_refs', convert_ids(args, conn)))

def process_method_call(args, conn):
    if args['refid'] == '0':
        args['refid'] = None
    if add_external_item(args, conn):
        return;

    execute_sql(conn, schema.get_insert_sql('function_refs', convert_ids(args, conn)))

def process_variable(args, conn):
    args['language'] = 'rust'
    args['type'] = ''

    execute_sql(conn, language_schema.get_insert_sql('variables', convert_ids(args, conn)))

def process_var_ref(args, conn):
    if add_external_item(args, conn):
        return;

    execute_sql(conn, schema.get_insert_sql('variable_refs', convert_ids(args, conn)))

def process_struct(args, conn):
    # Used for fixing up the refid in fixup_struct_ids
    if args['ctor_id'] != '0':
        ctor_ids[args['ctor_id']] = find_id('', args['id'])

    args['name'] = args['qualname'].split('::')[-1]
    args['kind'] = 'struct'
    args['language'] = 'rust'

    # TODO add to scopes too
    execute_sql(conn, language_schema.get_insert_sql('types', convert_ids(args, conn)))

def process_trait(args, conn):
    args['name'] = args['qualname'].split('::')[-1]
    args['kind'] = 'trait'
    args['language'] = 'rust'

    # TODO add to scopes too
    execute_sql(conn, language_schema.get_insert_sql('types', convert_ids(args, conn)))

def process_struct_ref(args, conn):
    if 'qualname' not in args:
        args['qualname'] = ''
    if add_external_item(args, conn):
        return;
    process_type_ref(args, conn)

def process_module(args, conn):
    mod_parents[int(args['id'])] = int(args['scopeid'])

    args['name'] = args['qualname'].split('::')[-1]
    args['language'] = 'rust'
    args['def_file'] = get_file_id(args['def_file'], conn)

    # TODO add to scopes too
    execute_sql(conn, schema.get_insert_sql('modules', convert_ids(args, conn)))

def process_mod_ref(args, conn):
    if add_external_item(args, conn):
        return;
    args['aliasid'] = 0

    execute_sql(conn, schema.get_insert_sql('module_refs', convert_ids(args, conn)))

def process_module_alias(args, conn):
    args['qualname'] = args['file_name'] + "$" + args['name']

    execute_sql(conn, schema.get_insert_sql('module_aliases', convert_ids(args, conn)))

def process_impl(args, conn):
    args['file_id'] = get_file_id(args['file_name'], conn)

    # TODO add to scopes too
    execute_sql(conn, schema.get_insert_sql('impl_defs', convert_ids(args, conn)))

def process_typedef(args, conn):
    args['name'] = args['qualname'].split('::')[-1]
    args['kind'] = 'typedef'
    args['language'] = 'rust'

    execute_sql(conn, language_schema.get_insert_sql('types', convert_ids(args, conn)))

def process_type_ref(args, conn):
    if 'qualname' not in args:
        args['qualname'] = ''
    if add_external_item(args, conn):
        return;

    execute_sql(conn, schema.get_insert_sql('type_refs', convert_ids(args, conn)))

def process_extern_mod(args, conn):
    args['qualname'] = args['file_name'] + "$" + args['name']
    args['refid'] = '0'
    args['refidcrate'] = '0'
    crate = args['crate']
    args = convert_ids(args, conn)
    # module ids from crate_map are post-transform
    args['refid'] = crate_map[crate][1]

    execute_sql(conn, schema.get_insert_sql('module_aliases', args))

# These have to happen before anything else in the csv and have to be concluded by
# by 'end_external_crate'.
def process_external_crate(args, conn):
    global crate_map
    mod_id = get_next_id()
    crate_map[args['crate']] = (args['name'], mod_id)

    args = {'id': mod_id,
            'name': args['name'],
            'qualname': args['file_name'] + "$" + args['name'],
            'def_file': get_file_id(args['file_name'], conn),
            'extent_start': -1,
            'extent_end': -1}
    # don't need to convert_args because the args are all post-transform
    execute_sql(conn, schema.get_insert_sql('modules', args))

def process_end_external_crates(args, conn):
    # We've got all the info we're going to get about external crates now.
    global local_libs
    local_libs = [name for (name, cid) in crate_map.values() if name not in std_libs]

# There should only be one of these per crate and it gives info about the current
# crate.
def process_crate(args, conn):
    crate_map['0'] = (args['name'], 0)
    execute_sql(conn, schema.get_insert_sql('crates', convert_ids(args, conn)))

# When we have a path like a::b::c, we want to have info for a and a::b.
# Unfortunately Rust does not give us much info, so we have to
# construct it ourselves from the module info we have.
# We have the qualname for the module (e.g, a or a::b) but we do not have
# the refid
def fixup_sub_mods(conn):
    # First create refids for module refs whose qualnames match the qualname of
    # the module (i.e., no aliases).
    conn.execute("""
        UPDATE module_refs SET
            refid=(SELECT id FROM modules WHERE modules.qualname = module_refs.qualname)
        WHERE refid=0 AND aliasid=0 AND
            (SELECT id FROM modules WHERE modules.qualname = module_refs.qualname) IS NOT NULL
        """)

    # Next account for where the path is an aliased modules e.g., alias::c,
    # where c is already accounted for.
    # We can't do all this in one statement because sqlite does not have joins.
    cur = conn.execute("""
        SELECT module_refs.extent_start, module_aliases.id, modules.id,
           module_aliases.name, modules.name, modules.qualname,
           (SELECT path FROM files WHERE files.id = module_refs.file_id)
        FROM module_refs, module_aliases, modules
        WHERE module_refs.refid = 0 AND
           module_refs.aliasid = 0 AND
           module_refs.file_id = module_aliases.file_id AND
           module_aliases.name = module_refs.qualname AND
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
        SELECT module_refs.extent_start, module_aliases.id,
            module_aliases.name, modules.name, modules.qualname, module_refs.qualname,
            (SELECT path FROM files WHERE files.id = module_refs.file_id)
        FROM module_refs, module_aliases, modules
        WHERE module_refs.refid = 0 AND
            module_refs.aliasid = 0 AND
            module_refs.file_id = module_aliases.file_id AND
            module_refs.qualname LIKE module_aliases.name || '%' AND
            modules.id = module_aliases.refid
        """)
    for ex_start, aliasid, alias_name, mod_name, qualname, ref_name, file_name in cur:
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
                UPDATE module_refs SET
                   refid = ?,
                   aliasid = ?,
                   qualname = ?
                WHERE extent_start=?
                """,
                (refid, aliasid, qualname, ex_start))

def process_type_ref(args, conn):
    args['file_id'] = get_file_id(args['file_name'], conn)

    execute_sql(conn, schema.get_insert_sql('type_refs', args))

def fixup_struct_ids(conn):
    # Sadness. Structs have an id for their definition and an id for their ctor.
    # Sometimes, we get one, sometimes the other. This method fixes up any refs
    # to the latter into refs to the former.
    for ctor in ctor_ids.keys():
        conn.execute('UPDATE type_refs SET refid=? WHERE refid=?', (ctor_ids[ctor],ctor))

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

def generate_callgraph(conn):
    # staticaly  dispatched call
    sql = """
        SELECT refs.refid, refs.scopeid
        FROM function_refs as refs, functions
        WHERE
            functions.id = refs.scopeid
    """
    for callee, caller in conn.execute(sql):
        conn.execute("INSERT OR IGNORE INTO callers(callerid, targetid) VALUES (?, ?)",
                     (caller, callee))

    # dynamically dispatched call
    sql = """
        SELECT callee.id, refs.scopeid
        FROM function_refs as refs, functions as callee, functions as caller
        WHERE
            caller.id = refs.scopeid
            AND refs.refid IS NULL
            AND refs.declid = callee.declid
    """
    for callee, caller in conn.execute(sql):
        conn.execute("INSERT OR IGNORE INTO callers(callerid, targetid) VALUES (?, ?)",
                     (caller, callee))

def generate_locations(conn):
    # standard lib crates
    sql = """
        INSERT OR IGNORE INTO extern_locations(location, docurl, srcurl, dxrurl) VALUES (?, ?, ?, ?)
    """
    docurl = "http://static.rust-lang.org/doc/master/%s/index.html"
    srcurl = "https://github.com/mozilla/rust/tree/master/src/lib%s"
    dxrurl = "http://dxr.mozilla.org/rust/source/lib%s/lib.rs.html"
    for l in std_libs:
        conn.execute(sql, (l, docurl%l, srcurl%l, dxrurl%l))

    # crates from github
    sql = "SELECT location FROM module_aliases WHERE location LIKE 'github.com'"
    srcurl = "https://%s"
    for l in conn.execute(sql):
        conn.execute("INSERT OR IGNORE INTO extern_locations(location, docurl, srcurl, dxrurl) VALUES (?, '', ?, '')", (l, srcurl%l))
        
