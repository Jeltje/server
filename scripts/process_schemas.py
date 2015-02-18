"""
A script to generate the schemas for the GA4GH protocol. We download
the Avro definitions of the GA4GH protocol and use it to generate
the Python class definitions in ga4gh/_protocol_definitions.py.
"""
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import sys
import glob
import json
import shutil
import os.path
import tarfile
import tempfile
import requests
import argparse
import subprocess
import textwrap
import re

import avro.schema

HEADER_COMMENT = """
DO NOT EDIT THIS FILE!!
This file is automatically generated by the process_schemas.py program
in the scripts directory. It is not intended to be edited directly. If
you need to update the GA4GH protocol classes, please run the script
on the appropriate schema version.
"""


class SchemaClass(object):
    """
    Class to convert an Avro JSON definition of a GA4GH type into the
    corresponding Python class.
    """
    def __init__(self, sourceFile):
        self.sourceFile = sourceFile
        with open(sourceFile) as sf:
            self.schemaSource = sf.read()
            self.schema = avro.schema.parse(self.schemaSource)
        self.name = self.schema.name

    def getFields(self):
        """
        Returns the list of avro fields sorted in order of name.
        """
        return sorted(self.schema.fields, key=lambda f: f.name)

    def getEmbeddedTypes(self):
        """
        Returns the set of embedded types in this class.
        """
        # TODO need to clarify how we operate on Unions here. The current
        # code will break when we move to schema version 0.6 as we are
        # no longer assured that the first element of the union is null.
        # This would be a good opportunity to tidy this up.
        ret = []
        if isinstance(self.schema, avro.schema.RecordSchema):
            for field in self.getFields():
                if isinstance(field.type, avro.schema.ArraySchema):
                    if isinstance(field.type.items, avro.schema.RecordSchema):
                        ret.append((field.name, field.type.items.name))
                elif isinstance(field.type, avro.schema.RecordSchema):
                    ret.append((field.name, field.type.name))
                elif isinstance(field.type, avro.schema.UnionSchema):
                    t0 = field.type.schemas[0]
                    t1 = field.type.schemas[1]
                    if (isinstance(t0, avro.schema.PrimitiveSchema) and
                            t0.type == "null"):
                        if isinstance(t1, avro.schema.RecordSchema):
                            ret.append((field.name, t1.name))
                    else:
                        raise Exception("Schema union assumptions violated")
        return ret

    def formatSchema(self):
        """
        Formats the schema source so that we can print it literally
        into a Python source file.
        """
        schema = json.loads(self.schemaSource)
        stack = [schema]
        # Strip out all the docs
        while len(stack) > 0:
            elm = stack.pop()
            if "doc" in elm:
                elm["doc"] = ""
            for value in elm.values():
                if isinstance(value, dict):
                    stack.append(value)
                elif isinstance(value, list):
                    for dic in value:
                        if isinstance(dic, dict):
                            stack.append(dic)
        jsonData = json.dumps(schema)
        with tempfile.TemporaryFile() as tmp:
            tmp.write(jsonData)
            tmp.seek(0)
            # Filter the text through fmt to make it look like acceptable code.
            subproc = subprocess.Popen(
                ["fmt"], stdout=subprocess.PIPE, stdin=tmp)
            (output, err) = subproc.communicate()
            exitStatus = subproc.wait()
        if exitStatus != 0:
            msg = "Error occured running fmt: {0}: {1}".format(exitStatus, err)
            raise Exception(msg)
        return output

    def formatRequiredFields(self):
        """
        Returns a string encoding the set of required fields (i.e those
        fields that do not have a default value.
        """
        fields = []
        for field in self.getFields():
            if not field.has_default:
                fields.append(field)

        if len(fields) < 2:
            string = "set(["
            for field in fields:
                string += '"{0}"'.format(field.name)
            string += "])"
        else:
            string = "set([\n"
            for field in fields:
                string += (" " * 8) + '"{0}",\n'.format(field.name)
            string += (" " * 4) + "])"
        return string

    def writeConstructor(self, outputFile):
        # Force using slots to avoid the overhead of a dict per object;
        # when a query returns hundreds of thousands of calls this can
        # save a hundred megabytes or more.
        print("    __slots__ = ['",
              textwrap.fill(
                  "', '".join([field.name for field in self.getFields()]),
                  62, subsequent_indent='                 '), "']",
              sep='', file=outputFile)
        print(file=outputFile)
        print("    def __init__(self):", file=outputFile)
        for field in self.getFields():
            print("        self.{0} = {1}".format(
                field.name, field.default), file=outputFile)

    def writeEmbeddedTypesClassMethods(self, outputFile):
        """
        Returns the definition for the _embeddedTypes dictionary. This is a
        temporary mechanism to provide a simple path from the current
        approach to more efficient and type-safe methods that we want
        to transition to.
        """
        print("    @classmethod", file=outputFile)
        print("    def isEmbeddedType(cls, fieldName):", file=outputFile)
        et = self.getEmbeddedTypes()
        if len(et) == 0:
            string = (" " * 8) + "embeddedTypes = {}"
        else:
            string = (" " * 8) + "embeddedTypes = {\n"
            for fn, ft in self.getEmbeddedTypes():
                string += (" " * 12) + "'{0}': {1},\n".format(fn, ft)
            string += (" " * 8) + "}"
        print(string, file=outputFile)
        print(" " * 8 + "return fieldName in embeddedTypes", file=outputFile)
        print(file=outputFile)
        print("    @classmethod", file=outputFile)
        print("    def getEmbeddedType(cls, fieldName):", file=outputFile)
        print(string, file=outputFile)
        print(" " * 8 + "return embeddedTypes[fieldName]", file=outputFile)
        print(file=outputFile)

    def write(self, outputFile):
        """
        Writes the class definition to the specified file.
        """
        superclass = "ProtocolElement"
        if isinstance(self.schema, avro.schema.EnumSchema):
            superclass = "object"
        string = "\n\nclass {0}({1}):".format(self.schema.name, superclass)
        print(string, file=outputFile)
        doc = self.schema.doc
        if doc is None:
            doc = "No documentation"
        string = '    """\n{0}\n    """'.format(doc)
        print(string, file=outputFile)
        if isinstance(self.schema, avro.schema.RecordSchema):
            string = '    _schemaSource = """\n{0}"""'.format(
                self.formatSchema())
            print(string, file=outputFile)
            string = '    schema = avro.schema.parse(_schemaSource)'
            print(string, file=outputFile)
            string = '    requiredFields = {0}'.format(
                self.formatRequiredFields())
            print(string, file=outputFile)
            print(file=outputFile)
            self.writeEmbeddedTypesClassMethods(outputFile)
            self.writeConstructor(outputFile)
        elif isinstance(self.schema, avro.schema.EnumSchema):
            # TODO make a proper Python enum here using the Python 3.4 enum?
            for symbol in self.schema.symbols:
                string = '    {0} = "{0}"'.format(symbol, symbol)
                print(string, file=outputFile)


class SchemaGenerator(object):
    """
    Class that generates a schema in Python code from Avro definitions.
    """
    def __init__(self, version, schemaDir, outputFile):
        self.version = version
        self.schemaDir = schemaDir
        self.outputFile = outputFile
        self.classes = []
        for avscFile in glob.glob(os.path.join(self.schemaDir, "*.avsc")):
            self.classes.append(SchemaClass(avscFile))
        self.requestClassNames = [
            cls.name for cls in self.classes
            if re.search('Search.+Request', cls.name)]
        self.responseClassNames = [
            cls.name for cls in self.classes
            if re.search('Search.+Response', cls.name)]
        self.postSignatures = []
        for request, response in zip(
                self.requestClassNames, self.responseClassNames):
            objname = re.search('Search(.+)Request', request).groups()[0]
            url = '/{0}/search'.format(objname.lower())
            tup = (url, request, response)
            self.postSignatures.append(tup)

    def writeHeader(self, outputFile):
        """
        Writes the header information to the output file.
        """
        print('"""{0}"""'.format(HEADER_COMMENT), file=outputFile)
        print("from protocol import ProtocolElement", file=outputFile)
        print("import avro.schema", file=outputFile)
        print(file=outputFile)
        versionStr = self.version[1:]  # Strip off leading 'v'
        print("version = '{0}'".format(versionStr), file=outputFile)

    def write(self):
        """
        Writes the generated schema classes to the output file.
        """
        with open(self.outputFile, "w") as outputFile:
            self.writeHeader(outputFile)
            # Get the classnames and sort them to get consistent ordering.
            names = [cls.name for cls in self.classes]
            classes = dict([(cls.name, cls) for cls in self.classes])
            for name in sorted(names):
                cls = classes[name]
                cls.write(outputFile)

            # can't just use pprint library because
            # pep8 will complain about formatting
            outputFile.write('\npostMethods = \\\n    [(\'')
            for i, tup in enumerate(self.postSignatures):
                url, request, response = tup
                if i != 0:
                    outputFile.write('     (\'')
                outputFile.write(url)
                outputFile.write('\',\n      ')
                outputFile.write(request)
                outputFile.write(',\n      ')
                outputFile.write(response)
                outputFile.write(')')
                if i == len(self.postSignatures) - 1:
                    outputFile.write(']\n')
                else:
                    outputFile.write(',\n')


class SchemaProcessor(object):
    """
    Class to download GA4GH schema definitions from github and process
    these into Python code.
    """
    def __init__(self, args):
        self.version = args.version
        self.destinationFile = args.outputFile
        self.verbosity = args.verbose
        self.tmpDir = tempfile.mkdtemp(prefix="ga4gh_")
        self.sourceTar = os.path.join(self.tmpDir, "schemas.tar.gz")
        self.avroJarPath = args.avro_tools_jar
        # Note! The tarball does not contain the leading v
        string = "schemas-{0}".format(self.version[1:])
        self.schemaDir = os.path.join(self.tmpDir, string)
        self.avroJar = os.path.join(self.schemaDir, "avro-tools.jar")

    def cleanup(self):
        if self.verbosity > 1:
            print("Cleaning up tmp dir", self.tmpDir)
        shutil.rmtree(self.tmpDir)

    def download(self, url, destination):
        """
        Downloads the specified url and saves the result to the specified
        file.
        """
        if self.verbosity > 1:
            print("Downloading", url, end="")
        with open(destination, "wb") as outputFile:
            response = requests.get(url, stream=True)
            response.raise_for_status()
            for block in response.iter_content(8192):
                if self.verbosity > 1:
                    print(".", end="")
                    sys.stdout.flush()
                if len(block) > 0:
                    outputFile.write(block)
            if self.verbosity > 1:
                print("done")

    def convertAvro(self, avdlFile):
        """
        Converts the specified avdl file using the java tools.
        """
        args = ["java", "-jar", self.avroJar, "idl2schemata", avdlFile]
        if self.verbosity > 0:
            print("converting", avdlFile)
        if self.verbosity > 1:
            print("running:", " ".join(args))
        if self.verbosity > 1:
            subprocess.check_call(args)
        else:
            with open(os.devnull, 'w') as devnull:
                subprocess.check_call(args, stdout=devnull, stderr=devnull)

    def run(self):
        url = "https://github.com/ga4gh/schemas/archive/{0}.tar.gz".format(
            self.version)
        self.download(url, self.sourceTar)
        with tarfile.open(self.sourceTar, "r") as tarball:
            tarball.extractall(self.tmpDir)
        directory = os.path.join(self.schemaDir, "src/main/resources/avro")
        if self.avroJarPath is not None:
            self.avroJar = os.path.abspath(self.avroJarPath)
        else:
            url = "http://www.carfab.com/apachesoftware/avro/stable/java/"\
                "avro-tools-1.7.7.jar"
            self.download(url, self.avroJar)
        cwd = os.getcwd()
        os.chdir(directory)
        for avdlFile in glob.glob("*.avdl"):
            self.convertAvro(avdlFile)
        os.chdir(cwd)
        if self.verbosity > 0:
            print("Writing schemas to ", self.destinationFile)
        sg = SchemaGenerator(self.version, directory, self.destinationFile)
        sg.write()


def main():
    parser = argparse.ArgumentParser(
        description="Script to process GA4GH Avro schemas. Requires "
        "java and fmt external commands")
    parser.add_argument(
        "--outputFile", "-o", default="ga4gh/_protocol_definitions.py",
        help="The file to output the protocol definitions to.")
    parser.add_argument(
        "version",
        help="The tagged git release to process, e.g., v0.5.1")
    parser.add_argument(
        "--avro-tools-jar", "-j",
        help="The path to a local avro-tools.jar", default=None)
    # TODO is this the right approach? Maybe we should be noisy be
    # default and add in an option to be quiet.
    parser.add_argument('--verbose', '-v', action='count', default=0)
    # We don't support Python 3 right now because the Avro API is
    # different between the different versions.
    if sys.version_info >= (3, 0):
        print("We don't currently support Python 3, sorry...")
        sys.exit(1)
    args = parser.parse_args()
    sp = SchemaProcessor(args)
    try:
        sp.run()
    finally:
        sp.cleanup()


if __name__ == "__main__":
    main()
