import os
import fnmatch
import dxr.plugins
from dxr.utils import search_url

_tree = None
_conn = None

def load(tree, conn):
    global _tree, _conn
    _tree = tree
    _conn = conn

class RustHtmlifier(object):
    def __init__(self, tree, conn, path, text, file_id):
        self.tree    = tree
        self.conn    = conn
        self.path    = path
        self.text    = text
        self.file_id = file_id

    def regions(self):
        return []

    def refs(self):
        """ Generate reference menus """
        # We'll need this argument for all queries here
        args = (self.file_id,)

        # Extents for functions definitions
        sql = """
            SELECT extent_start, extent_end, qualname
                FROM functions
              WHERE file_id = ?
        """
        for start, end, qualname in self.conn.execute(sql, args):
            yield start, end, (self.function_menu(qualname), qualname, None)

        # Add references to functions
        sql = """
            SELECT refs.extent_start, refs.extent_end,
                          functions.qualname,
                          (SELECT path FROM files WHERE files.id = functions.file_id),
                          functions.file_line
                FROM functions, function_refs AS refs
              WHERE functions.id = refs.refid AND refs.file_id = ?
        """
        for start, end, qualname, path, line in self.conn.execute(sql, args):
            menu = self.function_menu(qualname)
            self.add_jump_definition(menu, path, line)
            yield start, end, (menu, qualname, None)

        # Extents for variables defined here
        sql = """
            SELECT extent_start, extent_end, qualname, value
                FROM variables
              WHERE file_id = ?
        """
        for start, end, qualname, value in self.conn.execute(sql, args):
            yield start, end, (self.variable_menu(qualname), qualname, value)

        # Add references to variables
        sql = """
            SELECT refs.extent_start, refs.extent_end,
                          variables.qualname,
                          variables.value,
                          (SELECT path FROM files WHERE files.id = variables.file_id),
                          variables.file_line
                FROM variables, variable_refs AS refs
              WHERE variables.id = refs.refid AND refs.file_id = ?
        """
        for start, end, qualname, value, path, line in self.conn.execute(sql, args):
            menu = self.variable_menu(qualname)
            self.add_jump_definition(menu, path, line)
            yield start, end, (menu, qualname, value)

        # Add struct and trait defs
        sql = """
            SELECT extent_start, extent_end, qualname, kind
                FROM types
              WHERE file_id = ?
        """
        for start, end, qualname, kind in self.conn.execute(sql, args):
            yield start, end, (self.type_menu(qualname, kind), qualname, None)

        # Add references to types
        sql = """
            SELECT refs.extent_start, refs.extent_end,
                          types.qualname,
                          types.kind,
                          (SELECT path FROM files WHERE files.id = types.file_id),
                          types.file_line
                FROM types, type_refs AS refs
              WHERE types.id = refs.refid AND refs.file_id = ?
        """
        for start, end, qualname, kind, path, line in self.conn.execute(sql, args):
            menu = self.type_menu(qualname, kind)
            self.add_jump_definition(menu, path, line)
            yield start, end, (menu, qualname, None)

        # modules
        sql = """
            SELECT extent_start, extent_end, qualname
                FROM modules
              WHERE file_id = ?
        """
        for start, end, qualname in self.conn.execute(sql, args):
            menu = self.module_menu(qualname)
            if False: #TODO for module decls
                self.add_jump_definition(menu, mod_path, mod_line, "Jump to module implementation")
            yield start, end, (menu, qualname, None)

        # Add references to modules
        sql = """
            SELECT refs.extent_start, refs.extent_end,
                          modules.qualname,
                          (SELECT path FROM files WHERE files.id = modules.file_id),
                          modules.file_line
                FROM modules, module_refs AS refs
              WHERE modules.id = refs.refid AND
                refs.file_id = ? AND
                refs.aliasid = 0
        """
        for start, end, qualname, path, line in self.conn.execute(sql, args):
            menu = self.module_menu(qualname)
            if False: #TODO for module decls
                self.add_jump_definition(menu, mod_path, mod_line, "Jump to module implementation")
            self.add_jump_definition(menu, path, line)
            yield start, end, (menu, qualname, None)

        # Add references to modules via aliases
        sql = """
            SELECT refs.extent_start, refs.extent_end,
                          refs.qualname,
                          (SELECT path FROM files WHERE files.id = module_aliases.file_id),
                          module_aliases.file_line,
                          (SELECT path FROM files WHERE files.id = modules.file_id),
                          modules.file_line
                FROM modules, module_refs AS refs, module_aliases
              WHERE modules.id = refs.refid AND
                refs.file_id = ? AND
                refs.aliasid = module_aliases.id
        """
        for start, end, qualname, path, line, mod_path, mod_line in self.conn.execute(sql, args):
            menu = self.module_menu(qualname)
            if False: #TODO for module decls
                self.add_jump_definition(menu, mod_path, mod_line, "Jump to module implementation")
            self.add_jump_definition(menu, mod_path, mod_line, "jump to module definition")
            self.add_jump_definition(menu, path, line)
            yield start, end, (menu, qualname, None)

        # Add module aliases. 'use' without an explicit alias and without any wildcards,
        # etc. introduces an implicit alias for the module. E.g, |use a::b::c|
        # introduces an alias |c|. In these cases, we make the alias transparent - 
        # there is no link for the alias, but we add the alias menu stuff to the
        # module ref.
        sql = """
            SELECT module_aliases.extent_start,
                module_aliases.extent_end,
                module_aliases.qualname
                FROM module_aliases, modules
              WHERE module_aliases.file_id = ? AND
                module_aliases.refid = modules.id AND
                module_aliases.name != modules.name
        """
        for start, end, qualname in self.conn.execute(sql, args):
            menu = self.module_alias_menu(qualname)
            self.add_jump_definition(menu, mod_path, mod_line, "jump to module definition")
            yield start, end, (menu, qualname, None)



    def search(self, query):
        """ Auxiliary function for getting the search url for query """
        return search_url(self.tree.config.wwwroot,
                          self.tree.name,
                          query)

    def quote(self, qualname):
        """ Wrap qualname in quotes if it contains spaces """
        if ' ' in qualname:
            qualname = '"' + qualname + '"'
        return qualname

    #TODO factor out 'find references'

    def function_menu(self, qualname):
        """ Build menu for a function """
        menu = []
        menu.append({
            'text':   "Find references",
            'title':  "Find references to this function",
            'href':   self.search("+function-ref:%s" % self.quote(qualname)),
            'icon':   'reference'
        })
        return menu

    def variable_menu(self, qualname):
        """ Build menu for a variable """
        menu = []
        menu.append({
            'text':   "Find references",
            'title':  "Find reference to this variable",
            'href':   self.search("+var-ref:%s" % self.quote(qualname)),
            'icon':   'field'
        })
        return menu

    def type_menu(self, qualname, kind):
        """ Build menu for type """
        menu = []
        # TODO - inheritance
        if kind == 'trait':
            menu.append({
                'text':   "Find sub-traits",
                'title':  "Find sub-traits of this trait",
                'href':   self.search("+derived:%s" % self.quote(qualname)),
                'icon':   'type'
            })
            menu.append({
                'text':   "Find super-traits",
                'title':  "Find super-traits of this trait",
                'href':   self.search("+bases:%s" % self.quote(qualname)),
                'icon':   'type'
            })
        # TODO
        menu.append({
            'text':   "Find members",
            'title':  "Find members of this class",
            'href':   self.search("+member:%s" % self.quote(qualname)),
            'icon':   'members'
        })
        menu.append({
            'text':   "Find references",
            'title':  "Find references to this class",
            'href':   self.search("+type-ref:%s" % self.quote(qualname)),
            'icon':   'reference'
        })
        return menu

    def module_menu(self, qualname):
        """ Build menu for a module """
        menu = []
        menu.append({
            'text':   "Find references",
            'title':  "Find references to this module",
            'href':   self.search("+module-ref:%s" % self.quote(qualname)),
            'icon':   'reference'
        })
        menu.append({
            'text':   "Find uses",
            'title':  "Find 'use's of this module",
            'href':   self.search("+module-use:%s" % self.quote(qualname)),
            'icon':   'reference'
        })
        # TODO - jump to implementation
        return menu

    def module_alias_menu(self, qualname):
        """ Build menu for a module alias """
        menu = []
        menu.append({
            'text':   "Find references",
            'title':  "Find references to this module alias",
            'href':   self.search("+module-alias-ref:%s" % self.quote(qualname)),
            'icon':   'reference'
        })
        return menu

    def add_jump_definition(self, menu, path, line, text="Jump to definition"):
        """ Add a jump to definition to the menu """
        # Definition url
        url = self.tree.config.wwwroot + '/' + self.tree.name + '/source/' + path
        url += "#%s" % line
        menu.insert(0, { 
            'text':   text,
            'title':  "Jump to the definition in '%s'" % os.path.basename(path),
            'href':   url,
            'icon':   'jump'
        })

    def annotations(self):
        # TODO - compiler warnings
        return []

    def links(self):
        # TODO when we have methods in the functions table, we will need to be more
        # selective here
        # TODO only want top level functions
        # TODO probably need to think about how to organise the whole side bar thing properly
        sql = "SELECT name, file_line FROM functions WHERE file_id = ? ORDER BY file_line"
        links = []
        for name, line in self.conn.execute(sql, (self.file_id,)):
            if len(name) == 0: continue
            links.append(('function', name, "#%s" % line))
        yield (30, 'functions', links)

# XXX Does anyone use anything other than rs nowadays?
_patterns = ('*.rs', '*.rc')
def htmlify(path, text):
    fname = os.path.basename(path)
    if any((fnmatch.fnmatchcase(fname, p) for p in _patterns)):
        # Get file_id, skip if not in database
        sql = "SELECT files.id FROM files WHERE path = ? LIMIT 1"
        row = _conn.execute(sql, (path,)).fetchone()
        if row:
            print "Rust htmlification - " + path
            return RustHtmlifier(_tree, _conn, path, text, row[0])
    return None

__all__ = dxr.plugins.htmlifier_exports()
