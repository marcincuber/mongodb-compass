"""Apply reviewed hooks to the integrity-pinned browser package; fail on drift."""
from pathlib import Path
import sys


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise ValueError("Browser package does not match the reviewed runtime integration")
    return source.replace(old, new, 1)


def prepare(source):
    start = source.index("\tfunction handleMongoConnection(fastify, socket, request) {")
    end = source.index("\n\t/**\n\t * Websocket proxy for MongoDB connections", start)
    source = source[:start] + """\tfunction handleMongoConnection(fastify, socket, request) {
        return globalThis.compassHandleMongoConnection(fastify, socket, request);
    }
""" + source[end:]
    # The embedded shell is disabled; do not load its optional native addon.
    source = replace_once(source, "const { WorkerRuntime } = require('@mongosh/node-runtime-worker-thread');",
                          "const WorkerRuntime = null; // Embedded shell is disabled by this container.")
    source = replace_once(source, "fastify.get('/shell', { websocket: true }",
                          "if (fastify.args.enableShell) fastify.get('/shell', { websocket: true }")
    source = replace_once(source, "async function createClientSafeConnectionString(cs) {", """async function createClientSafeConnectionString(cs) {
      cs = cs.clone();
      for (const key of [...cs.searchParams.keys()]) {
        if (['tlscafile', 'tlscertificatekeyfile', 'tlscertificatekeyfilepassword', 'tlscrlfile'].includes(key.toLowerCase())) {
          cs.searchParams.delete(key);
        }
      }""")
    source = replace_once(source, "__dirname,\n\t        '..',\n\t        `connections-${passwordHash}.json`",
                          "process.env.XDG_CONFIG_HOME,\n\t        `connections-${passwordHash}.json`")
    return source


if __name__ == '__main__':
    path = Path(sys.argv[1])
    path.write_text(prepare(path.read_text()))
