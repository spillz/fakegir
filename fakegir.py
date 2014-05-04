#!/usr/bin/python3.4
"""Build a fake python package from the information found in gir files"""

import os
import sys
import keyword
import shutil
from lxml import etree

GIR_PATH = '/usr/share/gir-1.0/'
FAKEGIR_PATH = os.path.expanduser('~/.cache/fakegir')
XMLNS = "http://www.gtk.org/introspection/core/1.0"


# Pretty output
if sys.stdout.isatty():
    def errmsg(string):
        print("\033[1;31m%s\033[0m" % string)

    def statusmsg(string):
        print("\033[32m%s\033[0m" % string)

    def aboutmsg(string):
        print("\033[34m%s\033[0m" % string)
else:
    def errmsg(string):
        print("ERROR: %s" % string)

    def statusmsg(string):
        print(string)

    def aboutmsg(string):
        print(string)


def get_docstring(callable_tag):
    """Return docstring text for a callable"""
    doc = callable_tag.find("{%s}doc" % XMLNS)
    return ""
    return doc.text.replace("\\x", "x").replace("\"\"\"", "\" \" \"") if doc is not None else ""


def get_parameter_type(element):
    """Returns the type of a parameter"""
    tp = element.find("{%s}type" % XMLNS)
    return tp.get("name", "") if tp is not None else ""


def get_parameters(element):
    """Return the parameters of a callable"""
    params = []
    for elem_property in element.iterchildren("{%s}parameters" % XMLNS):
        for param in elem_property:
            try:
                subtag = etree.QName(param)
                if subtag.localname == "instance-parameter":
                    param_name = 'self'
                else:
                    param_name = param.get("name", "_arg%i" % len(params))

                    if keyword.iskeyword(param_name) or param_name == "self":
                        param_name = "_" + param_name

                parm_type = get_parameter_type(param)

                if param_name in params:
                    param_name += "_%i" % len(params)

                params.append((param_name, parm_type))
            except KeyError:
                pass
    return params


def insert_function(name, args, depth, docstring='', type="function"):
    """Yields a function definition"""
    indent1 = '    ' * (depth + 1)

    yield "\n"

    if type == "static method":
        yield '    ' * depth + "@staticmethod\n"

    if keyword.iskeyword(name):
        name = "_" + name

    signature = name + "(" + ", ".join((arg[0] if arg[0] != "..." else "*args" for arg in args)) + ")"
    statusmsg(indent1 + "Adding %s %s" % (type, signature))

    yield "%sdef %s:\n" % ('    ' if depth else '', signature)

    # docstring
    yield indent1
    yield "\"\"\"\n"
    # params
    if len(args) > depth: # HAX: depth==1 only if method with self argument
        for pname, tp in args:
            if pname == "self": continue
            yield "%s@param %s: %s\n" % (indent1, pname, tp)
        yield "\n"
    # real docstring
    yield from (indent1 + line + "\n" for line in docstring.split("\n"))
    # end docstring
    yield indent1
    yield "\"\"\"\n"


def insert_enum(element):
    """Yields a class definition with members only"""
    yield "\n\n"

    statusmsg("    Adding enum %s" % element.get("name"))

    # Class definition
    yield "class %s:\n" % element.get("name")

    yield "    \"\"\"\n"
    yield from ('    ' + line + "\n" for line in get_docstring(element).split("\n"))
    yield "    \"\"\"\n"

    # Members
    for member in element.iterchildren("{%s}member" % XMLNS):
        name = member.get("name")

        # There seems to be some broken member without a name?
        if not name:
            errmsg("        Enumeration member with empty name!")
            continue

        if name[0].isdigit():
            name = "_" + name

        yield "    %s = '%s'\n" % (name.upper(), member.get("value", "None").replace("\\", "\\\\"))


def insert_class(cls, parents):
    """Yields a complete class definition"""

    # class definition
    yield "\n\nclass "

    signature = "".join((cls.get("name"), "(", ", ".join(parents), ")"))
    statusmsg("    Adding class %s" % signature)

    yield signature
    yield ":\n    \"\"\"\n"
    yield from ('    ' + line + "\n" for line in get_docstring(cls).split("\n"))
    yield "    \"\"\"\n"

    has_constructor = False
    for constructor in cls.iterchildren("{%s}constructor"):
        params, doc = get_parameters(constructor), get_docstring(constructor)
        if not has_constructor:
            yield from insert_function("__init__", params, 1, doc, "method")
            has_constructor = True
        # FIXME: should we add these?
        #yield from insert_function(constructor.get("name"), params, 1, doc, "method")

    for meth in cls.iterchildren("{%s}method" % XMLNS):
        yield from insert_function(meth.get("name"), get_parameters(meth), 1, get_docstring(meth), "method")

    for func in cls.iterchildren("{%s}function" % XMLNS):
        yield from insert_function(func.get("name"), get_parameters(func), 1, get_docstring(func), "static method")


def process(elements):
    """Extract information from a gir namespace"""
    classes = []

    for element in elements:
        tag = etree.QName(element)
        tag_name = tag.localname

        if tag_name in ('class', 'interface'):
            classes.append(element)

        elif (tag_name == 'enumeration') or (tag_name == "bitfield"):
            yield "enum", insert_enum(element)

        elif tag_name == 'function':
            yield "func", insert_function(element.get("name"), get_parameters(element), 0, get_docstring(element))

        elif tag_name == 'constant':
            yield "const", "".join((element.get("name"), " = \"", element.get("value", "None").replace("\\", "\\\\"), "\"\n"))

    # Fix classes and imports
    local_parents = set()
    written_classes = set()
    all_classes = set(map(lambda x: x.get("name"), classes))

    parents = {}
    for cls in classes:
        parents[cls] = []

        if cls.get("parent"):
            parents[cls].append(cls.get("parent"))

        for implement in cls.iterfind("{%s}implements" % XMLNS):
            parents[cls].append(implement.get('name'))

        local_parents = local_parents.union(set([class_parent
                                                 for class_parent in parents[cls]
                                                 if '.' not in class_parent]))

    while written_classes != all_classes:
        for cls in classes:
            if any(('.' not in parent and parent not in written_classes for parent in parents[cls])):
                continue

            if cls in written_classes:
                continue

            for parent in parents[cls]:
                if "." in parent:
                    yield "import", parent[:parent.rindex(".")]

            yield "class", insert_class(cls, parents[cls])
            written_classes.add(cls.get("name"))


def extract_namespace(namespace):
    """Yield all definitions"""
    funcs = []
    enums = []
    consts = []
    classes = []
    imports = set()

    for what, value in process(namespace):
        if what == "import":
            imports.add(value)
        elif what == "class":
            classes.append(value)
        elif what == "enum":
            enums.append(value)
        elif what == "func":
            funcs.append(value)
        elif what == "const":
            consts.append(value)
        else:
            errmsg("Unknown type %s: %s" % (what, value))

    # Imports
    for name in imports:
        statusmsg("    Import %s" % name)
        yield "from . import %s\n" % name

    yield "\n"

    # Constants
    #for const in consts:
    #    statusmsg("    const %s" % const)
    yield from consts

    # Enums
    for enum in enums:
        yield from enum

    # Classes
    for cls in classes:
        yield from cls

    # Functions
    for func in funcs:
        yield from func


def parse_gir(gir_path):
    """Extract everything from a gir file"""
    parser = etree.XMLParser(encoding='utf-8', recover=True)
    root = etree.parse(gir_path, parser)
    namespace = root.findall('{%s}namespace' % XMLNS)[0]
    return extract_namespace(namespace)


def iter_girs(gir_repo):
    """Yield all available gir files"""
    for gir_file in os.listdir(gir_repo):
        # Don't know what to do with those, guess nobody uses PyGObject
        # for Gtk 2.0 anyway
        if gir_file in ('Gtk-2.0.gir', 'Gdk-2.0.gir', 'GdkX11-2.0.gir'):
            continue
        module_name = gir_file[:gir_file.index('-')]
        yield (module_name, gir_file)


def touch(filename):
    open(filename, "a").close()


def main(argv):
    """Main function"""
    aboutmsg("FakeGIR 2014.05.03")
    aboutmsg("GObject Repository path: %s" % GIR_PATH)
    aboutmsg("FakeGIR path: %s" % FAKEGIR_PATH)
    statusmsg("Creating repository...")

    if os.path.exists(FAKEGIR_PATH):
        shutil.rmtree(FAKEGIR_PATH)

    repository = os.path.join(FAKEGIR_PATH, "gi", "repository")
    os.makedirs(repository)

    with open(os.path.join(FAKEGIR_PATH, "gi", "__init__.py"), "w") as f:
        f.write("print(\"NOTE: Tried to load fakeGIR; consider removing it from PYTHONPATH!\")\n")
        f.write("import sys\n")
        f.write("sys.path.remove(\"%s\")\n" % FAKEGIR_PATH)
        f.write("del sys.modules[\"gi\"]\n")
        f.write("import gi\n")
    touch(os.path.join(FAKEGIR_PATH, "gi", "repository", "__init__.py"))

    for name, file in iter_girs(GIR_PATH):
        statusmsg("Generating %s" % name)
        gir = os.path.join(GIR_PATH, file)

        content = parse_gir(gir)
        fakegir = os.path.join(repository, name + ".py")

        with open(fakegir, 'w') as fakegir_file:
            fakegir_file.write("#!/usr/bin/python3\n# This file is auto-generated!!!\n\n")
            for chunk in content:
                fakegir_file.write(chunk)

if __name__ == "__main__":
    main(sys.argv)
