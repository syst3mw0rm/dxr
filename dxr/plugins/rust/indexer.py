import dxr.plugins
import os

PLUGIN_NAME = 'rust'

def pre_process(tree, env):
    # Setup environment variables for using the rust-dxr tool
    # We'll store all the havested metadata in the plugins temporary folder.
    temp_folder   = os.path.join(tree.temp_folder, 'plugins', PLUGIN_NAME)
    plugin_folder = os.path.join(tree.config.plugin_folder, PLUGIN_NAME)
    env['RUST']   = os.path.join(plugin_folder, 'rust-dxr') #"/home/ncameron/rust/x86_64-unknown-linux-gnu/stage2/bin/rustc"
    env['DXR_RUST'] = env['RUST']
    env['DXR_RUST_OBJECT_FOLDER']  = tree.object_folder
    env['DXR_RUST_TEMP_FOLDER']    = temp_folder

def post_process(tree, conn):
    pass


__all__ = dxr.plugins.indexer_exports()
