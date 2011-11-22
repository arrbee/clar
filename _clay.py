#!/usr/bin/env python

from __future__ import with_statement
from string import Template
import re, fnmatch, os

VERSION = "0.9.0"

TEST_FUNC_REGEX = r"^(void\s+(test_%s__(\w+))\(\s*void\s*\))\s*\{"

CLAY_HEADER = """
/*
 * Clay v0.9.0
 *
 * This is an autogenerated file. Do not modify.
 * To add new unit tests or suites, regenerate the whole
 * file with `./clay`
 */
"""

def main():
    from optparse import OptionParser

    parser = OptionParser()

    parser.add_option('-c', '--clay-path', dest='clay_path')
    parser.add_option('-v', '--report-to', dest='print_mode', default='default')

    options, args = parser.parse_args()

    for folder in args or ['.']:
        builder = ClayTestBuilder(folder,
            clay_path = options.clay_path,
            print_mode = options.print_mode)

        builder.render()


class ClayTestBuilder:
    def __init__(self, path, clay_path = None, print_mode = 'default'):
        self.declarations = []
        self.suite_names = []
        self.callback_data = {}
        self.suite_data = {}

        self.clay_path = os.path.abspath(clay_path) if clay_path else None

        self.path = os.path.abspath(path)
        self.modules = [
            "clay_sandbox.c",
            "clay_fixtures.c",
            "clay_fs.c"
        ]

        self.modules.append("clay_print_%s.c" % print_mode)

        print("Loading test suites...")

        for root, dirs, files in os.walk(self.path):
            module_root = root[len(self.path):]
            module_root = [c for c in module_root.split(os.sep) if c]

            tests_in_module = fnmatch.filter(files, "*.c")

            for test_file in tests_in_module:
                full_path = os.path.join(root, test_file)
                test_name = "_".join(module_root + [test_file[:-2]])

                with open(full_path) as f:
                    self._process_test_file(test_name, f.read())

        if not self.suite_data:
            raise RuntimeError(
                'No tests found under "%s"' % folder_name)

    def render(self):
        main_file = os.path.join(self.path, 'clay_main.c')
        with open(main_file, "w") as out:
            out.write(self._render_main())

        header_file = os.path.join(self.path, 'clay.h')
        with open(header_file, "w") as out:
            out.write(self._render_header())

        print ('Written Clay suite to "%s"' % self.path)

    #####################################################
    # Internal methods
    #####################################################

    def _render_cb(self, cb):
        return '{"%s", &%s}' % (cb['short_name'], cb['symbol'])

    def _render_suite(self, suite):
        template = Template(
r"""
    {
        "${clean_name}",
        ${initialize},
        ${cleanup},
        ${cb_ptr}, ${cb_count}
    }
""")

        callbacks = {}
        for cb in ['initialize', 'cleanup']:
            callbacks[cb] = (self._render_cb(suite[cb])
                if suite[cb] else "{NULL, NULL}")

        return template.substitute(
            clean_name = suite['name'].replace("_", "::"),
            initialize = callbacks['initialize'],
            cleanup = callbacks['cleanup'],
            cb_ptr = "_clay_cb_%s" % suite['name'],
            cb_count = suite['cb_count']
        ).strip()

    def _render_callbacks(self, suite_name, callbacks):
        template = Template(
r"""
static const struct clay_func _clay_cb_${suite_name}[] = {
    ${callbacks}
};
""")
        callbacks = [
            self._render_cb(cb)
            for cb in callbacks
            if cb['short_name'] not in ('initialize', 'cleanup')
        ]

        return template.substitute(
            suite_name = suite_name,
            callbacks = ",\n\t".join(callbacks)
        ).strip()

    def _render_header(self):
        template = Template(self._load_file('clay.h'))

        declarations = "\n".join(
            "extern %s;" % decl
            for decl in sorted(self.declarations)
        )

        return template.substitute(
            extern_declarations = declarations,
        )

    def _render_main(self):
        template = Template(self._load_file('clay.c'))
        suite_names = sorted(self.suite_names)

        suite_data = [
            self._render_suite(self.suite_data[s])
            for s in suite_names
        ]

        callbacks = [
            self._render_callbacks(s, self.callback_data[s])
            for s in suite_names
        ]

        callback_count = sum(
            len(cbs) for cbs in self.callback_data.values()
        )

        return template.substitute(
            clay_modules = self._get_modules(),
            clay_callbacks = "\n".join(callbacks),
            clay_suites = ",\n\t".join(suite_data),
            clay_suite_count = len(suite_data),
            clay_callback_count = callback_count,
        )

    def _load_file(self, filename):
        if self.clay_path:
            filename = os.path.join(self.clay_path, filename)
            with open(filename) as cfile:
                return cfile.read()

        else:
            import zlib, base64, sys
            content = CLAY_FILES[filename]

            if sys.version_info >= (3, 0):
                content = bytearray(content, 'utf_8')
                content = base64.b64decode(content)
                content = zlib.decompress(content)
                return str(content)
            else:
                content = base64.b64decode(content)
                return zlib.decompress(content)

    def _get_modules(self):
        return "\n".join(self._load_file(f) for f in self.modules)

    def _parse_comment(self, comment):
        comment = comment[2:-2]
        comment = comment.splitlines()
        comment = [line.strip() for line in comment]
        comment = "\n".join(comment)

        return comment

    def _process_test_file(self, suite_name, contents):
        regex_string = TEST_FUNC_REGEX % suite_name
        regex = re.compile(regex_string, re.MULTILINE)

        callbacks = []
        initialize = cleanup = None

        for (declaration, symbol, short_name) in regex.findall(contents):
            data = {
                "short_name" : short_name,
                "declaration" : declaration,
                "symbol" : symbol
            }

            if short_name == 'initialize':
                initialize = data
            elif short_name == 'cleanup':
                cleanup = data
            else:
                callbacks.append(data)

        if not callbacks:
            return

        tests_in_suite = len(callbacks)

        suite = {
            "name" : suite_name,
            "initialize" : initialize,
            "cleanup" : cleanup,
            "cb_count" : tests_in_suite
        }

        if initialize:
            self.declarations.append(initialize['declaration'])

        if cleanup:
            self.declarations.append(cleanup['declaration'])

        self.declarations += [
            callback['declaration']
            for callback in callbacks
        ]

        callbacks.sort(key=lambda x: x['short_name'])
        self.callback_data[suite_name] = callbacks
        self.suite_data[suite_name] = suite
        self.suite_names.append(suite_name)

        print("  %s (%d tests)" % (suite_name, tests_in_suite))
