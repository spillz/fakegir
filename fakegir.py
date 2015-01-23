##!/usr/bin/python3
"""Build a fake python package from the information found in gir files"""

import os
import sys
import keyword
import shutil
from lxml import etree

USE_ALL_GIR_FILES = False

GIR_PATH = "/usr/share/gir-1.0/"
GIR_FILES = ("GLib-2.0.gir", "Gio-2.0.gir", "GObject-2.0.gir",
             "Gtk-3.0.gir", "Atk-1.0.gir", "Gdk-3.0.gir",
#             "Gtk-2.0.gir", "Atk-1.0.gir", "Gdk-2.0.gir", ##older versions on Ubuntu 14.04
             "Polkit-1.0.gir")
FAKEGIR_PATH = os.path.expanduser("~/.cache/fakegir")
XMLNS = "http://www.gtk.org/introspection/core/1.0"
TYPE_MAP = {"gboolean": "bool",
            "gpointer": "None",
            "gconstpointer": "None",
            "gchar": "str",
            "guchar": "str",
            "gint": "int",
            "guint": "int",
            "gint8": "int",
            "guint8": "int",
            "gint16": "int",
            "guint16": "int",
            "gint32": "int",
            "guint32": "int",
            "gint64": "int",
            "guint64": "int",
            "gshort": "int",
            "gushort": "int",
            "glong": "long",
            "gulong": "long",
            "gfloat": "float",
            "gdouble": "float",
            "gsize": "long",
            "gssize": "long",
            "goffset": "int",
            "guintptr": "int",
            "utf8": "unicode",
            "none": "None"}
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


def get_rtype(function):
    """Return return-type of a function"""
    assert isinstance(function, etree._Element)
    rtag = function.find("{%s}return-value" % XMLNS)
    child = rtag.find("{%s}type" % XMLNS)
    if child is None:
        return "None"
    rtype = child.get("name")
    return TYPE_MAP[rtype] if rtype in TYPE_MAP else rtype


def insert_function(name, args, depth, type="function", rtype="None", doc = ''):
    """Yields a function definition"""
    indents = INDENT * (depth + 1)

    yield "\n" if depth != 0 else "\n\n"

    if type == "static method":
        yield INDENT * depth + "@staticmethod\n"

    if keyword.iskeyword(name):
        name = "_" + name

    if type != "init":
        signature = name + "(" + ", ".join((arg[0] if arg[0] != "..." else "*args" for arg in args)) + ")"
    else:
        signature = name + "(self)"
    statusmsg(indents + "Adding %s %s" % (type, signature))

    yield "%sdef %s:\n" % (INDENT if depth else "", signature)

    # Doc and Type hint helper
    if rtype is not "None" or doc is not '':
        yield indents + "\"\"\"\n"
        if doc is not "None":
            for line in doc.splitlines():
                yield indents + line +"\n"
        if rtype is not "None":
            yield indents + "@rtype: %s\n" % rtype
        yield indents + "\"\"\"\n"

    # Function body
    if (type != "init") or ((type == "init") and (len(args) == 1)):
        yield indents + "pass\n"
    else:
        for arg in args:
            if arg == "self":
                continue
            yield indents + "self.%s = None\n" % arg


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


def insert_class(cls, parents={}, is_struct=False):
    """Yields a complete class definition"""
    # class definition
    yield "\n\nclass "

    signature = "".join((cls.get("name"), "(", ", ".join(parents), ")"))
    statusmsg(INDENT + "Adding class %s" % signature)

    yield signature + ":\n"

    empty_class = True

    if(is_struct):
        empty_class = False
        fields = ["self"]
        for field in cls.iterchildren("{%s}field" % XMLNS):
            fields.append(field.get("name"))
        for c in (insert_function("__init__", fields, 1, "init")):
            yield c

    for doc in cls.iterchildren("{%s}doc" % XMLNS):
        yield INDENT + '"""\n'
        for line in doc.text.splitlines():
            yield INDENT + line + "\n"
        yield INDENT + '"""\n'

    for constructor in cls.iterchildren("{%s}constructor" % XMLNS):
        if constructor.get("deprecated") is None:
            empty_class = False
            for c in insert_function(constructor.get("name"), get_parameters(constructor), 1, "static method", get_rtype(constructor)):
                yield c

    for meth in cls.iterchildren("{%s}method" % XMLNS):
        if meth.get("deprecated") is None:
            empty_class = False
            doc = ''
            for d in meth.iterchildren("{%s}doc" % XMLNS):
                doc += d.text
            for c in insert_function(meth.get("name"), get_parameters(meth), 1, "method", get_rtype(meth), doc):
                yield c

    for v_meth in cls.iterchildren("{%s}virtual-method" % XMLNS):
        if v_meth.get("deprecated") is None:
            empty_class = False
            for c in insert_function("do_%s" % v_meth.get("name"), get_parameters(v_meth), 1, "method", get_rtype(v_meth)):
                yield c

    for func in cls.iterchildren("{%s}function" % XMLNS):
        if func.get("deprecated") is None:
            empty_class = False
            for c in insert_function(func.get("name"), get_parameters(func), 1, "static method", get_rtype(func)):
                yield c

    if empty_class:
        yield INDENT + "pass\n"


def process(elements):
    """Extract information from a gir namespace"""
    classes = []
    struct = []

    for element in elements:
        tag = etree.QName(element)
        tag_name = tag.localname

        if (tag_name in ("class", "interface")) and (element.get("deprecated") is None):
            classes.append(element)

        if (tag_name == "record") and (element.get("deprecated") is None):
            struct.append(element)

        elif (tag_name in ("enumeration", "bitfield")) and (element.get("deprecated") is None):
            yield "enum", insert_enum(element)

        elif (tag_name in ("function", "callback")) and (element.get("deprecated") is None):
            yield "func", insert_function(element.get("name"), get_parameters(element), 0, rtype=get_rtype(element))

        elif tag_name == "constant" and (element.get("deprecated") is None):
            type = element.find("{%s}type" % XMLNS).get("name")
            value = element.get("value", "None")

            if type == "utf8":
                yield "const", "".join((element.get("name"), " = \"", value.replace("\\", "\\\\"), "\"\n"))
            elif type == "gboolean":
                yield "const", "".join((element.get("name"), " = ", value.title(), "\n"))
            else:
                yield "const", "".join((element.get("name"), " = ", value, "\n"))

    # Yield classes and imports
    ordered_classes = []
    parents = {}

    for cls in classes:
        parents[cls] = []

        if cls.get("parent"):
            parents[cls].append(cls.get("parent"))

        for implement in cls.iterfind("{%s}implements" % XMLNS):
            parents[cls].append(implement.get("name"))

    while True:
        changed = False
        for cls in classes:
            local_parents = set([class_parent for class_parent in parents[cls] if "." not in class_parent])
            ordered_classes_name = set(map(lambda x: x.get("name"), ordered_classes))
            dependent = False
            for parent in local_parents:
                if parent not in ordered_classes_name:
                    dependent = True
                    break
            if not dependent and cls not in ordered_classes:
                ordered_classes.append(cls)
                changed = True
        if not changed:
            break

    for cls in ordered_classes:
        for parent in parents[cls]:
            if "." in parent:
                yield "import", parent[:parent.rindex(".")]
        yield "class", insert_class(cls, parents[cls])

    for str in struct:
        yield "class", insert_class(str, is_struct=True)


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
        for c in const:
            yield c

    # Enums
    for enum in enums:
        for c in enum:
            yield c

    # Classes
    for cls in classes:
        for c in cls:
            yield c

    # Functions
    for func in funcs:
        for c in func:
            yield c


def parse_gir(gir_path):
    """Extract everything from a gir file"""
    parser = etree.XMLParser(encoding="utf-8", recover=True)
    root = etree.parse(gir_path, parser)
    namespace = root.findall("{%s}namespace" % XMLNS)[0]
    return extract_namespace(namespace)


def iter_girs(gir_repo):
    """Yield all available gir files"""
    for gir_file in os.listdir(gir_repo):
        if not USE_ALL_GIR_FILES and gir_file not in GIR_FILES:
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
                fakegir_file.write(chunk.encode('utf8'))

if __name__ == "__main__":
    if len(sys.argv)>1:
        if sys.argv[1].lower() == 'all':
            USE_ALL_GIR_FILES = True
    main(sys.argv)
