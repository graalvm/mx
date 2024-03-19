import mx
import os

import mx_subst


class NinjaToolchainTemplate(mx.Project):
    def __init__(self, suite, name, deps, workingSets, theLicense, template, output_file, **kwArgs):
        super(NinjaToolchainTemplate, self).__init__(suite, name, subDir=None, srcDirs=[], deps=deps, workingSets=workingSets, d=suite.dir, theLicense=theLicense, **kwArgs)
        self.template = os.path.join(mx.suite('mx').dir, template)
        self.output_file = os.path.join(self.get_output_base(), output_file)

    def isJDKDependent(self):
        return False

    def getArchivableResults(self, use_relpath=True, single=False):
        out = self.output_file
        yield out, os.path.basename(out)

    def getBuildTask(self, args):
        return NinjaToolchainTemplateBuildTask(self, args)


class NinjaToolchainTemplateBuildTask(mx.BuildTask):
    def __init__(self, subject, args):
        super(NinjaToolchainTemplateBuildTask, self).__init__(subject, args, 1)

    def __str__(self):
        return "Generating " + self.subject.name

    def newestOutput(self):
        return mx.TimeStampFile(self.subject.output_file)

    def needsBuild(self, newestInput):
        sup = super(NinjaToolchainTemplateBuildTask, self).needsBuild(newestInput)
        if sup[0]:
            return sup

        output_file = self.subject.output_file
        if not os.path.exists(output_file):
            return True, output_file + ' does not exist'
        with open(output_file, "r") as f:
            on_disk = f.read()
        if on_disk != self.contents():
            return True, f'the content of {output_file} changed'

        return False, 'up to date'

    def build(self):
        mx.ensure_dir_exists(self.subject.get_output_root())
        with open(self.subject.output_file, "w") as f:
            f.write(self.contents())

    def clean(self, forBuild=False):
        output_root = self.subject.get_output_root()
        if os.path.exists(output_root):
            mx.rmtree(output_root)

    def contents(self):
        substitutions = mx_subst.SubstitutionEngine()
        # Windows
        substitutions.register_with_arg('cl', lambda s: getattr(self.args, 'alt_cl', '') or s)
        substitutions.register_with_arg('link', lambda s: getattr(self.args, 'alt_link', '') or s)
        substitutions.register_with_arg('lib', lambda s: getattr(self.args, 'alt_lib', '') or s)
        substitutions.register_with_arg('ml', lambda s: getattr(self.args, 'alt_ml', '') or s)
        # Other platforms
        substitutions.register_with_arg('cc', lambda s: getattr(self.args, 'alt_cc', '') or s)
        substitutions.register_with_arg('cxx', lambda s: getattr(self.args, 'alt_cxx', '') or s)
        substitutions.register_with_arg('ar', lambda s: getattr(self.args, 'alt_ar', '') or s)
        # Common
        substitutions.register_with_arg('cflags', lambda s: getattr(self.args, 'alt_cflags', '') or s)
        substitutions.register_with_arg('cxxflags', lambda s: getattr(self.args, 'alt_cxxflags', '') or s)
        substitutions.register_with_arg('ldflags', lambda s: getattr(self.args, 'alt_ldflags', '') or s)

        with open(self.subject.template, "r") as f:
            template = f.read()

        return substitutions.substitute(template)
