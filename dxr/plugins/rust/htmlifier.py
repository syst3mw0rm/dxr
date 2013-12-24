import dxr.plugins


def load(tree, conn):
  pass

def htmlify(path, text):
  print("Rust htmlifier called")
  pass

__all__ = dxr.plugins.htmlifier_exports()
