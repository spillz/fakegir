#!/usr/bin/python3
"""Build a fake python package from the information found in gir files"""

import os
import sys
import keyword
import shutil
from lxml import etree

GIR_PATH = "/usr/share/gir-1.0/"
GIR_FILES = ("GLib-2.0.gir", "Gio-2.0.gir", "GObject-2.0.gir", "Gtk-3.0.gir", "Atk-1.0.gir", "Gdk-3.0.gir")
FAKEGIR_PATH = os.path.expanduser("~/.cache/fakegir")
XMLNS = "http://www.gtk.org/introspection/core/1.0"
INDENT = "    "


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
                    param_name = "self"
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


def insert_function(name, args, depth, type="function"):
    """Yields a function definition"""
    indents = INDENT * (depth + 1)

    if depth != 0:
        yield "\n"
    else:
        yield "\n\n"

    if type == "static method":
        yield INDENT * depth + "@staticmethod\n"

    if keyword.iskeyword(name):
        name = "_" + name

    signature = name + "(" + ", ".join((arg[0] if arg[0] != "..." else "*args" for arg in args)) + ")"
    statusmsg(indents + "Adding %s %s" % (type, signature))

    yield "%sdef %s:\n" % (INDENT if depth else "", signature)
    yield indents
    yield "pass\n"


def insert_enum(element):
    """Yields a class definition with members only"""
    yield "\n\n"

    statusmsg(INDENT + "Adding enum %s" % element.get("name"))

    # Class definition
    yield "class %s(Enum):\n" % element.get("name")

    # Members
    for member in element.iterchildren("{%s}member" % XMLNS):
        name = member.get("name")

        # There seems to be some broken member without a name?
        if not name:
            errmsg(INDENT * 2 + "Enumeration member with empty name!")
            continue

        if name[0].isdigit():
            name = "_" + name

        yield INDENT + "%s = %s\n" % (name.upper(), member.get("value", "None").replace("\\", "\\\\"))


def insert_class(cls, parents):
    """Yields a complete class definition"""
    # class definition
    yield "\n\nclass "

    signature = "".join((cls.get("name"), "(", ", ".join(parents), ")"))
    statusmsg(INDENT + "Adding class %s" % signature)

    yield signature
    yield ":\n"

    empty_class = True

    for constructor in cls.iterchildren("{%s}constructor" % XMLNS):
        if constructor.get("deprecated") is None:
            empty_class = False
            yield from insert_function(constructor.get("name"), get_parameters(constructor), 1, "static method")

    for meth in cls.iterchildren("{%s}method" % XMLNS):
        if meth.get("deprecated") is None:
            empty_class = False
            yield from insert_function(meth.get("name"), get_parameters(meth), 1, "method")

    for meth in cls.iterchildren("{%s}virtual-method" % XMLNS):
        if meth.get("deprecated") is None:
            empty_class = False
            yield from insert_function("do_%s" % meth.get("name"), get_parameters(meth), 1, "method")

    for func in cls.iterchildren("{%s}function" % XMLNS):
        if func.get("deprecated") is None:
            empty_class = False
            yield from insert_function(func.get("name"), get_parameters(func), 1, "static method")

    if empty_class:
        yield INDENT + "pass\n"


def process(elements):
    """Extract information from a gir namespace"""
    classes = []

    for element in elements:
        tag = etree.QName(element)
        tag_name = tag.localname

        if tag_name in ("class", "interface"):
            classes.append(element)

        elif (tag_name in ("enumeration", "bitfield")) and (element.get("deprecated") is None):
            yield "enum", insert_enum(element)

        elif (tag_name == "function") and (element.get("deprecated") is None):
            yield "func", insert_function(element.get("name"), get_parameters(element), 0)

        elif tag_name == "constant" and (element.get("deprecated") is None):
            if element.find("{%s}type" % XMLNS).get("name") == "utf8":
                yield "const", "".join((element.get("name"), " = \"", element.get("value", "None").replace("\\", "\\\\"), "\"\n"))
            elif element.find("{%s}type" % XMLNS).get("name") == "gboolean" and element.get("value", "None") == "true":
                yield "const", "".join((element.get("name"), " = True\n"))
            elif element.find("{%s}type" % XMLNS).get("name") == "gboolean" and element.get("value", "None") == "false":
                yield "const", "".join((element.get("name"), " = False\n"))
            else:
                yield "const", "".join((element.get("name"), " = ", element.get("value", "None").replace("\\", "\\\\"), "\n"))

    # Yield classes and imports
    local_parents = set()

    parents = {}
    for cls in classes:
        parents[cls] = []

        if cls.get("parent"):
            parents[cls].append(cls.get("parent"))

        for implement in cls.iterfind("{%s}implements" % XMLNS):
            parents[cls].append(implement.get("name"))

        local_parents = local_parents.union(set([class_parent
                                                 for class_parent in parents[cls]
                                                 if "." not in class_parent]))

    for cls in classes:
        for parent in parents[cls]:
            if "." in parent:
                yield "import", parent[:parent.rindex(".")]

        yield "class", insert_class(cls, parents[cls])


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
    if len(enums) > 0:
        yield "from enum import Enum\n"

    for name in imports:
        statusmsg(INDENT + "Import %s" % name)
        yield "from . import %s\n" % name

    yield "\n"

    # Constants
    for const in consts:
        yield from const

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
    parser = etree.XMLParser(encoding="utf-8", recover=True)
    root = etree.parse(gir_path, parser)
    namespace = root.findall("{%s}namespace" % XMLNS)[0]
    return extract_namespace(namespace)


def iter_girs(gir_repo):
    """Yield all available gir files"""
    for gir_file in os.listdir(gir_repo):
        if gir_file not in GIR_FILES:
            continue
        module_name = gir_file[:gir_file.index("-")]
        yield (module_name, gir_file)


def main(argv):
    """Main function"""
    aboutmsg("FakeGIR 2015")
    aboutmsg("GObject Repository path: %s" % GIR_PATH)
    aboutmsg("FakeGIR path: %s" % FAKEGIR_PATH)
    statusmsg("Creating repository...")

    if os.path.exists(FAKEGIR_PATH):
        shutil.rmtree(FAKEGIR_PATH)

    repository = os.path.join(FAKEGIR_PATH, "gi", "repository")
    os.makedirs(repository)

    open(os.path.join(FAKEGIR_PATH, "gi", "__init__.py"), "a").close()
    open(os.path.join(FAKEGIR_PATH, "gi", "repository", "__init__.py"), "a").close()

    for name, file in iter_girs(GIR_PATH):
        statusmsg("Generating %s" % name)
        gir = os.path.join(GIR_PATH, file)

        content = parse_gir(gir)
        fakegir = os.path.join(repository, name + ".py")

        with open(fakegir, "w") as fakegir_file:
            fakegir_file.write("#!/usr/bin/python3\n\n")
            for chunk in content:
                fakegir_file.write(chunk)

if __name__ == "__main__":
    main(sys.argv)
