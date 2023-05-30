#
# ----------------------------------------------------------------------------------------------------

# Copyright (c) 2021, Oracle and/or its affiliates. All rights reserved.
# DO NOT ALTER OR REMOVE COPYRIGHT NOTICES OR THIS FILE HEADER.
#
# This code is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License version 2 only, as
# published by the Free Software Foundation.
#
# This code is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License
# version 2 for more details (a copy is included in the LICENSE file that
# accompanied this code).
#
# You should have received a copy of the GNU General Public License version
# 2 along with this work; if not, write to the Free Software Foundation,
# Inc., 51 Franklin St, Fifth Floor, Boston, MA 02110-1301 USA.
#
# Please contact Oracle, 500 Oracle Parkway, Redwood Shores, CA 94065 USA
# or visit www.oracle.com if you need additional information or have any
# questions.
#
# ----------------------------------------------------------------------------------------------------

import copy
import io
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import zipfile
from abc import ABCMeta, abstractmethod
from argparse import ArgumentParser, Action, OPTIONAL, RawTextHelpFormatter, REMAINDER
from itertools import islice
from typing import Optional, NamedTuple, Iterable
from xml.etree import ElementTree
from zipfile import ZipFile

import mx
import mx_benchmark
import mx_logcompilation

try:
    # import into the global scope but don't complain if it's not there.  The commands themselves
    # will perform the check again and produce a helpful error message if it's not available.
    import capstone
except ImportError:
    pass

def vm_has_bb_dumping(java_command=None, vm=None, bb_option='PrintBBInfo'):
    assert (java_command is None and vm) or (vm is None and java_command), "Only one should be provited not both"
    args = ['-XX:+UnlockExperimentalVMOptions', '-XX:+EnableJVMCI', '-XX:+EagerJVMCI', '-XX:+JVMCIPrintProperties', '--version']
    if java_command:
        out = subprocess.check_output([java_command] + args)
        return out.find(bb_option) >= 0
    else:
        out = mx.OutputCapture()
        vm.run_java(args, out=out)
        return out.data.find(bb_option) >= 0

def check_capstone_import(name):
    try:
        import capstone  # pylint: disable=unused-variable, unused-import
    except ImportError as e:
        mx.abort(
            f'{e}\nThe capstone module is required to support \'{name}\'. Try installing it with `pip install capstone`')


# File header format
filetag = b"JVMTIASM"
MajorVersion = 1
MinorVersion = 0

# Marker values for various data sections
DynamicCodeTag, = struct.unpack('>i', b'DYNC')
CompiledMethodLoadTag, = struct.unpack('>i', b'CMLT')
MethodsTag, = struct.unpack('>i', b'MTHT')
DebugInfoTag, = struct.unpack('>i', b'DEBI')
CompiledMethodUnloadTag, = struct.unpack('>i', b'CMUT')


class ExperimentFiles(object, metaclass=ABCMeta):
    """A collection of data files from a performance data collection experiment."""

    def __init__(self):
        pass

    @staticmethod
    def open_experiment(filename):
        if os.path.isdir(filename):
            return FlatExperimentFiles(directory=filename)
        elif zipfile.is_zipfile(filename):
            return ZipExperimentFiles(filename)
        return None

    @staticmethod
    def open(options):
        if options.experiment is None:
            mx.abort('Must specify an experiment')
        experiment = ExperimentFiles.open_experiment(options.experiment)
        if experiment is None:
            mx.abort(f'Experiment \'{options.experiment}\' does not exist')
        if hasattr(options, 'block_info') and options.block_info:
            experiment.force_block_info(options.block_info)
        return experiment

    @abstractmethod
    def open_jvmti_asm_file(self):
        raise NotImplementedError()

    @abstractmethod
    def has_assembly(self):
        raise NotImplementedError()

    @abstractmethod
    def get_jvmti_asm_filename(self):
        raise NotImplementedError()

    @abstractmethod
    def get_perf_binary_filename(self):
        raise NotImplementedError()

    @abstractmethod
    def ensure_perf_output(self):
        raise NotImplementedError()

    @abstractmethod
    def open_perf_output_file(self, mode='r'):
        raise NotImplementedError()

    @abstractmethod
    def has_log_compilation(self):
        raise NotImplementedError()

    @abstractmethod
    def get_log_compilation_filename(self):
        raise NotImplementedError()

    @abstractmethod
    def open_log_compilation_file(self):
        raise NotImplementedError()

    @abstractmethod
    def force_block_info(self, forced_block_info_dir):
        raise NotImplementedError()

    @abstractmethod
    def has_block_info(self, compilation_id=None):
        raise NotImplementedError()

    @abstractmethod
    def open_block_info(self, compilation_id):
        raise NotImplementedError()

    def is_native_image_experiment(self) -> bool:
        """Infers and returns whether the experiment was executed using Native Image."""
        return not self.has_log_compilation() and not self.has_assembly()


def find_basic_block_info_filename(compilation_id, files, block_extension='blocks'):
    if compilation_id[-1] == '%':
        # It is an OSR compilation id
        reg = re.compile(f'HotSpotOSRCompilation-{compilation_id[:-1]}\\[.*\\]\\.{block_extension}')
    else:
        # Normal compilation
        reg = re.compile(f'HotSpotCompilation-{compilation_id}\\[.*\\]\\.{block_extension}')
    for f in files:
        if reg.search(f):
            return f

def has_basic_block_info_file(files, block_extension='blocks'):
    """Check that at least one file in the given collection is a .blocks file."""
    for f in files:
        if re.search(f'\\.{block_extension}', f):
            return True
    return False

class FlatExperimentFiles(ExperimentFiles):
    """A collection of data files from a performance data collection experiment."""

    def __init__(self, directory, jvmti_asm_name='jvmti_asm_file', perf_binary_name='perf_binary_file',
                 perf_output_name='perf_output_file', log_compilation_name='log_compilation'):
        super(FlatExperimentFiles, self).__init__()
        if not os.path.isdir(directory):
            raise AssertionError('Must be directory')
        self.directory = os.path.abspath(directory)
        self.jvmti_asm_filename = os.path.join(self.directory, jvmti_asm_name)
        self.perf_binary_filename = os.path.join(self.directory, perf_binary_name)
        self.perf_output_filename = os.path.join(self.directory, perf_output_name)
        self.log_compilation_filename = os.path.join(self.directory, log_compilation_name)

        self.dump_path = None
        path = os.path.join(self.directory, 'graal_dump')
        if os.path.exists(path):
            assert os.path.isdir(path), f"{path} must be a directory"
            self.dump_path = path

    @staticmethod
    def create(experiment, overwrite=False):
        experiment = os.path.abspath(experiment)
        if os.path.exists(experiment):
            if not overwrite:
                mx.abort(f'Experiment file already exists: {experiment}')
            shutil.rmtree(experiment)
        os.mkdir(experiment)
        return FlatExperimentFiles(directory=experiment)

    def open_jvmti_asm_file(self):
        return open(self.jvmti_asm_filename, 'rb')

    def has_assembly(self):
        return self.jvmti_asm_filename and os.path.exists(self.jvmti_asm_filename)

    def open_perf_output_file(self, mode='r'):
        return open(self.perf_output_filename, mode)

    def get_jvmti_asm_filename(self):
        return self.jvmti_asm_filename

    def get_perf_binary_filename(self):
        return self.perf_binary_filename

    def has_perf_binary(self):
        return self.perf_binary_filename and os.path.exists(self.perf_binary_filename)

    def get_perf_output_filename(self):
        return self.perf_output_filename

    def has_perf_output(self):
        return self.perf_output_filename and os.path.exists(self.perf_output_filename)

    def get_log_compilation_filename(self):
        return self.log_compilation_filename

    def open_log_compilation_file(self):
        return open(self.log_compilation_filename, mode='r', encoding='utf-8')

    def has_log_compilation(self):
        return self.log_compilation_filename and os.path.exists(self.log_compilation_filename)

    def create_dump_dir(self):
        if self.dump_path:
            return self.dump_path
        if self.directory:
            self.dump_path = os.path.join(self.directory, 'graal_dump')
            os.mkdir(self.dump_path)
            return self.dump_path
        else:
            raise AssertionError('Unhandled')

    def ensure_perf_output(self):
        """Convert the binary perf output into the text form if it doesn't already exist."""
        if not self.has_perf_output():
            if not PerfOutput.is_supported():
                mx.abort('perf output parsing must be done on a system which supports the perf command')
            if not self.has_perf_binary():
                mx.abort(f'perf data file \'{self.perf_binary_filename}\' is missing')
            convert_cmd = PerfOutput.perf_convert_binary_command(self, self.is_native_image_experiment())
            # convert the perf binary data into text format
            with self.open_perf_output_file(mode='w') as fp:
                mx.run(convert_cmd, out=fp)
            print(f'Created perf output file in {self.directory}')

    def package(self, name=None):
        self.ensure_perf_output()

        directory_name = os.path.basename(self.directory)
        parent = os.path.dirname(self.directory)
        if not name:
            name = directory_name
        return shutil.make_archive(name, 'zip', root_dir=parent, base_dir=directory_name)

    def force_block_info(self, forced_block_info_dir):
        assert os.path.isdir(forced_block_info_dir), "Must be directory"
        self.dump_path = os.path.abspath(forced_block_info_dir)

    def has_block_info(self, compilation_id=None):
        if self.dump_path is None:
            return False

        assert os.path.isdir(self.dump_path), f"{self.dump_path} either does not exist or is not a directory"
        if compilation_id is None:
            return has_basic_block_info_file(os.listdir(self.dump_path))

        filename = find_basic_block_info_filename(compilation_id, os.listdir(self.dump_path))
        if filename is None:
            return False

        filename = os.path.join(self.dump_path, filename)
        return filename is not None and os.path.isfile(filename)

    def open_block_info(self, compilation_id):
        assert compilation_id is not None, "Must provide a compilation id"
        assert self.has_block_info(compilation_id), f"Must have block information for compliation id {compilation_id}"
        filename = find_basic_block_info_filename(compilation_id, os.listdir(self.dump_path))
        filename = os.path.join(self.dump_path, filename)
        return open(filename, mode='r')

class ZipExperimentFiles(ExperimentFiles):
    """A collection of data files from a performance data collection experiment."""

    def __init__(self, filename):
        super(ZipExperimentFiles, self).__init__()
        self.experiment_file = ZipFile(filename)
        self.jvmti_asm_file = self.find_file('jvmti_asm_file', error=False)
        self.perf_output_filename = self.find_file('perf_output_file')
        self.log_compilation_filename = self.find_file('log_compilation', error=False)
        self.dump_path = self.find_file('graal_dump' + os.sep, error=False)

    def find_file(self, name, error=True):
        for f in self.experiment_file.namelist():
            if f.endswith(os.sep + name):
                return f
        if error:
            mx.abort('Missing file ' + name)

    def open_jvmti_asm_file(self):
        with self.experiment_file.open(self.jvmti_asm_file, 'r') as fp:
            # These files can be large and zip i/o is somewhat slow, so
            # reading the whole file at once significantly improves
            # the processing speed.
            return io.BytesIO(fp.read())

    def has_assembly(self):
        return self.jvmti_asm_file is not None

    def ensure_perf_output(self):
        if self.perf_output_filename is None:
            mx.abort('perf output missing in archive')

    def open_perf_output_file(self, mode='r'):
        return io.TextIOWrapper(self.experiment_file.open(self.perf_output_filename, mode), encoding='utf-8')

    def open_log_compilation_file(self):
        return io.TextIOWrapper(self.experiment_file.open(self.log_compilation_filename, 'r'), encoding='utf-8')

    def has_log_compilation(self):
        return self.log_compilation_filename is not None

    def get_jvmti_asm_filename(self):
        mx.abort('Unable to output directly to zip file')

    def get_perf_binary_filename(self):
        mx.abort('Unable to output directly to zip file')

    def get_log_compilation_filename(self):
        mx.abort('Unable to output directly to zip file')

    def force_block_info(self, forced_block_info_dir):
        mx.abort('Unable to provide blocks directory when experiment is in a zip archive')

    def has_block_info(self, compilation_id=None):
        if self.dump_path is None:
            return False

        if compilation_id is None:
            return has_basic_block_info_file(self.experiment_file.namelist())

        return find_basic_block_info_filename(compilation_id, self.experiment_file.namelist())

    def open_block_info(self, compilation_id):
        assert compilation_id is not None, "Must provide a compilation id"
        assert self.has_block_info(compilation_id), f"Must have block information for compilation id {compilation_id}"
        filename = find_basic_block_info_filename(compilation_id, self.experiment_file.namelist())
        return io.TextIOWrapper(self.experiment_file.open(filename, 'r'), encoding='utf-8')

class Instruction:
    """A simple wrapper around a CapStone instruction to support data instructions."""

    def __init__(self, address, mnemonic, operand, instruction_bytes, size, insn=None):
        self.address = address
        self.mnemonic = mnemonic
        self.operand = operand
        self.bytes = instruction_bytes
        self.size = size
        self.insn = insn
        self.prefix = None
        self.comments = None

    def groups(self):
        if self.insn and self.insn.groups:
            return [self.insn.group_name(g) for g in self.insn.groups]
        return []


class DisassemblyBlock:
    """A chunk of disassembly with associated annotations"""

    def __init__(self, instructions):
        self.instructions = instructions


class DisassemblyDecoder:
    """A lightweight wrapper around the CapStone disassembly providing some extra functionality."""

    def __init__(self, decoder, fp):
        decoder.detail = True
        self.decoder = decoder
        self.annotators = []
        self.hex_bytes = False
        self.fp = fp

    def print(self, string):
        print(string, file=self.fp)

    def add_annotator(self, annotator):
        self.annotators.append(annotator)

    def successors(self, instruction):
        raise NotImplementedError()

    def disassemble_with_skip(self, code, code_addr):
        instructions = [Instruction(i.address, i.mnemonic, i.op_str, i.bytes, i.size, i) for i in
                        self.decoder.disasm(code, code_addr)]
        total_size = len(code)
        if instructions:
            last = instructions[-1]
            decoded_bytes = last.address + last.size - code_addr
        else:
            decoded_bytes = 0
        while decoded_bytes != total_size:
            new_instructions = [Instruction(i.address, i.mnemonic, i.op_str, i.bytes, i.size, i) for i in
                                self.decoder.disasm(code[decoded_bytes:], code_addr + decoded_bytes)]
            if new_instructions:
                instructions.extend(new_instructions)
                last = instructions[-1]
                decoded_bytes = last.address + last.size - code_addr
            else:
                instructions.append(Instruction(code_addr + decoded_bytes, '.byte', f'{code[decoded_bytes]:0x}',
                                                code[decoded_bytes:decoded_bytes + 1], 1))
                decoded_bytes += 1
        return instructions

    def find_jump_targets(self, instructions):
        targets = set()
        for i in instructions:
            if i.insn:
                successors = self.successors(i.insn)
                if successors:
                    for successor in successors:
                        if successor:
                            targets.add(successor)
        targets = list(targets)
        targets.sort()
        return targets

    def get_annotations(self, instruction):
        preannotations = []
        postannotations = []
        for x in self.annotators:
            a = x(instruction)
            if a is None:
                continue
            if isinstance(a, list):
                postannotations.extend(a)
            elif isinstance(a, tuple):
                post, pre = x(instruction)
                if pre:
                    preannotations.append(pre)
                if post:
                    postannotations.extend(post)
            elif isinstance(a, str):
                postannotations.append(a)
            else:
                message = f'Unexpected annotation: {a}'
                mx.abort(message)
        return preannotations[0] if preannotations else None, postannotations

    def filter_by_hot_region(self, instructions, hotpc, threshold, context_size=16):
        index = 0
        begin = None
        skip = 0
        regions = []
        for index in range(len(instructions)):
            instruction = instructions[index]
            if instruction.address in hotpc:
                event = hotpc.pop(instruction.address)
                if threshold:
                    if event.percent < threshold:
                        continue
                skip = 0
                if not begin:
                    begin = max(index - context_size, 0)
            else:
                skip += 1
            if begin and skip > context_size:
                regions.append((begin, index))
                begin = None
                skip = 0
        if begin:
            regions.append((begin, index))
        if len(hotpc) != 0:
            print(f"Unattributed pcs {[f'{x:x}' for x in list(hotpc)]}")
        return regions

    def disassemble(self, code, hotpc, short_class_names=False, threshold=0.001):
        instructions = self.disassemble_with_skip(code.code, code.code_addr)
        if threshold == 0:
            regions = [(0, len(instructions))]
        else:
            regions = self.filter_by_hot_region(instructions, hotpc, threshold)
        instructions = [(i,) + self.get_annotations(i) for i in instructions]
        prefix_width = max(len(p) if p else 0 for i, p, a in instructions) + 1
        prefix_format = '{:' + str(prefix_width) + '}'
        region = 1

        for begin, end in regions:
            if threshold != 0:
                if region != 1:
                    self.print(code.format_name(short_class_names=short_class_names))
                self.print(f"Hot region {region}")
            for i, prefix, annotations in instructions[begin:end]:
                hex_bytes = ''
                if self.hex_bytes:
                    hex_bytes = ' '.join([f'{b:02x}' for b in i.bytes])
                if prefix is None:
                    prefix = ' ' * prefix_width
                else:
                    prefix = prefix_format.format(prefix)
                assert len(prefix) == prefix_width, f'{prefix} {prefix_width}'
                line = f'{prefix}0x{i.address:x}:\t{i.mnemonic}\t{i.operand}\t{hex_bytes}'
                line = line.expandtabs()
                if annotations:
                    padding = ' ' * len(line)
                    lines = [padding] * len(annotations)
                    lines[0] = line
                    for a, b in zip(lines, annotations):
                        self.print(f'{a}; {b}')
                else:
                    self.print(line)
            if threshold != 0:
                self.print(f"End of hot region {region}")
            self.print('')
            region += 1

        last, _, _ = instructions[-1]
        decode_end = last.address + last.size
        buffer_end = code.code_addr + len(code.code)
        if decode_end != buffer_end:
            self.print(f'Skipping {buffer_end - decode_end} bytes {buffer_end:x} {decode_end:x} ')


class AMD64DisassemblerDecoder(DisassemblyDecoder):
    def __init__(self, fp):
        DisassemblyDecoder.__init__(self, capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64), fp)

    def successors(self, i):
        if len(i.groups) > 0:
            groups = [i.group_name(g) for g in i.groups]
            if 'branch_relative' in groups:
                assert len(i.operands) == 1
                if i.op_str == 'jmp':
                    return [i.operands[0].imm]
                else:
                    return [i.operands[0].imm, i.address + i.size]
            elif 'jump' in groups:
                # how should an unknown successor be represented
                return [None]
        else:
            # true is intended to mean fall through
            return True


class AArch64DisassemblyDecoder(DisassemblyDecoder):
    def __init__(self, fp):
        DisassemblyDecoder.__init__(self, capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_ARM), fp)

    def successors(self, i):
        if len(i.groups) > 0:
            groups = [i.group_name(g) for g in i.groups]
            if 'branch_relative' in groups:
                assert len(i.operands) == 1
                return i.operands[0].imm
            elif 'jump' in groups:
                return [None]
        else:
            return True


method_signature_re = re.compile(r'((?:\[*[VIJFDSCBZ])|(?:\[*L[^;]+;))')
primitive_types = {'I': 'int', 'J': 'long', 'V': 'void', 'F': 'float', 'D': 'double',
                   'S': 'short', 'C': 'char', 'B': 'byte', 'Z': 'boolean'}

class BasicBlock:
    """A cfg basic block"""

    def __init__(self, bb_id, start, end, freq):
        self.id = bb_id
        self.start = start
        self.end = end
        self.freq = freq
        self.period = 0
        self.samples = 0

class Method:
    """A Java Method decoded from a JVMTI assembly dump."""

    def __init__(self, class_signature, name, method_signature, source_file, line_number_table):
        self.line_number_table = line_number_table
        self.name = name
        args, return_type = method_signature[1:].split(')')
        arguments = re.findall(method_signature_re, args)
        self.method_arguments = [Method.decode_type(x) for x in arguments]
        self.return_type = Method.decode_type(return_type)
        self.source_file = source_file
        self.class_signature = Method.decode_class_signature(class_signature)

    @staticmethod
    def format_type(typestr, short_class_names):
        if short_class_names:
            return typestr.rsplit('.', 1)[-1]
        else:
            return typestr

    @staticmethod
    def format_types(types, short_class_names):
        if short_class_names:
            return [Method.format_type(x, short_class_names) for x in types]
        else:
            return types

    def format_name(self, with_arguments=True, short_class_names=False):
        return Method.format_type(self.class_signature, short_class_names) + '.' + self.name +\
               (('(' + ', '.join(Method.format_types(self.method_arguments, short_class_names)) + ')') if with_arguments else '')

    def method_filter_format(self, with_arguments=False):
        return self.format_name(with_arguments=with_arguments)

    def __repr__(self):
        return self.format_name()

    @staticmethod
    def decode_type(argument_type):
        result = argument_type
        arrays = ''
        while result[0] == '[':
            arrays = arrays + '[]'
            result = result[1:]
        if len(result) == 1:
            result = primitive_types[result]
        else:
            result = Method.decode_class_signature(result)
        return result + arrays

    @staticmethod
    def decode_class_signature(signature):
        if signature[0] == 'L' and signature[-1] == ';':
            return signature[1:-1].replace('/', '.')
        raise AssertionError('Bad signature: ' + signature)


class DebugFrame:
    def __init__(self, method, bci):
        self.method = method
        self.bci = bci

    def format(self, short_class_names=False):
        return f'{self.method.format_name(with_arguments=False, short_class_names=short_class_names)}:{self.bci}'


class DebugInfo:
    def __init__(self, pc, frames):
        self.frames = frames
        self.pc = pc


class CompiledCodeInfo:
    """A generated chunk of HotSpot assembly, including any metadata"""

    def __init__(self, name, timestamp, code_addr, code_size,
                 code, generated, debug_info=None, methods=None):
        self.timestamp = timestamp
        self.code = code
        self.code_size = code_size
        self.code_addr = code_addr
        self.name = name
        self.debug_info = debug_info
        self.debug_info_map = None
        self.unload_time = None
        self.generated = generated
        self.events = []
        self.event_map = None
        self.total_period = 0
        self.total_samples = 0
        self.methods = methods
        self.nmethod = None
        self.basic_blocks = None

    def __str__(self):
        return f"0x{self.code_begin():x}-0x{self.code_end():x} {self.name} {self.timestamp}-{self.unload_time or ''}"

    def format_name(self, short_class_names=False):
        if self.generated or not short_class_names:
            return self.name
        if self.nmethod:
            return self.nmethod.format(short_class_names=short_class_names)
        return self.methods[0].format_name(short_class_names=short_class_names)

    def get_compile_id(self):
        if self.nmethod is None:
            return None
        return self.nmethod.get_compile_id()

    def set_nmethod(self, nmethod):
        self.nmethod = nmethod
        nmethod_name = nmethod.format_name(with_arguments=True)
        if nmethod_name != self.name:
            # LogCompilation output doesn't seem to handle anonymous classes consistently so correct the names
            # based on what JVMTI recorded.
            assert '$$Lambda$' in self.name or \
                   self.name.startswith('java.lang.invoke.MethodHandle.linkToStatic') or \
                   self.name.startswith('java.lang.invoke.LambdaForm'), f'{self.name} != {nmethod_name}'
            # correct the method naming
            nmethod.method = self.methods[0]
        # update the name to include the LogCompilation id and any truffle names
        self.name = str(nmethod)

    def set_basic_blocks(self, basic_blocks):
        self.basic_blocks = basic_blocks

    def set_unload_time(self, timestamp):
        self.unload_time = timestamp

    def code_begin(self):
        return self.code_addr

    def code_end(self):
        return self.code_addr + self.code_size

    def contains(self, pc, timestamp=None):
        if self.code_addr <= pc < self.code_end():
            # early stubs have a timestamp that is after their actual creation time
            # so treat any code which was never unloaded as persistent.
            return self.generated or timestamp is None or self.contains_timestamp(timestamp)
        return False

    def add(self, event):
        assert self.code_addr <= event.pc < self.code_end()
        self.events.append(event)
        self.total_period += event.period
        self.total_samples += event.samples
        if self.basic_blocks:
            # if we have basic block information, we search for the basic block the sample belongs to
            for b in self.basic_blocks:
                if self.code_begin() + b.start <= event.pc < self.code_begin() + b.end:
                    b.period += event.period
                    b.samples += event.samples

    def contains_timestamp(self, timestamp):
        return timestamp >= self.timestamp and \
               (self.unload_time is None or self.unload_time > timestamp)

    def get_event_map(self):
        if self.event_map is None:
            self.event_map = {}
            for event in self.events:
                self.event_map[event.pc] = event
        return self.event_map

    def get_debug_info_map(self):
        """

        :return:
        :rtype: dict[int, DebugInfo]
        """
        if self.debug_info_map is None:
            self.debug_info_map = {}
            for debug_info in self.debug_info:
                self.debug_info_map[debug_info.pc] = debug_info
        return self.debug_info_map

    def get_code_annotations(self, pc, show_call_stack_depth=None, hide_perf=False, short_class_names=False):
        annotations = []
        prefix = None
        if not hide_perf:
            event = self.get_event_map().get(pc)
            if event:
                prefix = f'{100.0 * event.period / float(self.total_period):5.2f}%'

        if self.debug_info and show_call_stack_depth != 0:
            debug_info = self.get_debug_info_map().get(pc)
            if debug_info:
                frames = debug_info.frames
                if show_call_stack_depth:
                    frames = frames[:show_call_stack_depth]
                for frame in frames:
                    annotations.append(frame.format(short_class_names))

        return annotations, prefix

    def disassemble(self, decoder, short_class_names=False, threshold=0.001):
        """

        :type decoder: DisassemblyDecoder
        """
        decoder.print(self.format_name(short_class_names=short_class_names))
        decoder.print(f'0x{self.code_begin():x}-0x{self.code_end():x} (samples={self.total_samples}, period={self.total_period})')
        hotpc = {}
        for event in self.events:
            event = copy.copy(event)
            event.percent = event.period * 100 / self.total_period
            hotpc[event.pc] = event
        decoder.disassemble(self, hotpc, short_class_names=short_class_names, threshold=threshold)
        decoder.print('')

    def check_basic_blocks_0_rel_freq(self, fp=sys.stdout):
        """Check the relative frequencies of each block with respect to block 0"""
        assert self.basic_blocks and len(self.basic_blocks) > 0, "Must have basic blocks information"
        b0 = self.basic_blocks[0]
        assert b0.id == 0, "The first block must have id 0"
        if b0.samples == 0:
            print(f'[WARRNING] In method {self.format_name(short_class_names=True)}\n\tblock 0 got {b0.samples} samples', file=fp)
            return

        for b in self.basic_blocks[1:]:
            perf_freq = b.period / b0.period
            if not compare_freq(b.freq, perf_freq):
                print(f'[ERROR] In method {self.format_name(short_class_names=True)}\n\tblock id {b.id:5}, relative frequencies with respect to first block diverge, graal freq {b.freq:.6e}, perf freq {perf_freq:.6e}', file=fp)


    def check_basic_blocks_rel_freq_most(self, fp=sys.stdout):
        """Check the relative frequencies of each block with respect to the most frequent block"""
        assert self.basic_blocks and len(self.basic_blocks) > 0, "Must have basic blocks information"

        bmax_graal = sorted(self.basic_blocks, key=lambda b: b.freq, reverse=True)
        bmax_perf = sorted(self.basic_blocks, key=lambda b: b.period, reverse=True)

        if bmax_graal[0].id != bmax_perf[0].id:
            print(f'[WARRNING] In method {self.format_name(short_class_names=True)}\n\tmost frequent basic block measured with perf (id={bmax_perf[0].id:3}) differs from most frequent basic block from graal (id={bmax_graal[0].id:3})', file=fp)
            print(f'\tTop 5 basic blocks from graal {[(b.id, b.freq) for b in bmax_graal[:5]]}\n\tTop 5 basic blocks from perf {[(b.id, b.samples, b.period) for b in bmax_perf[:5]]}', file=fp)

            graal_most_frequent = {b.id for b in bmax_graal[:5]}
            if all([b.id not in graal_most_frequent for b in bmax_perf[:5]]):
                print('[ERROR] Top 5 most frequent basic blocks from graal is disjoint from top 5 most frequent basic blocks from perf', file=fp)
            return

        bmax = bmax_graal[0]

        for b in [bloop for bloop in self.basic_blocks if bloop.id != bmax.id]:
            graal_freq = b.freq / bmax.freq
            perf_freq = b.period / bmax.period

            if not compare_freq(graal_freq, perf_freq):
                print(f'[ERROR] In method {self.format_name(short_class_names=True)}\n\tblock id {b.id:5}, relative frequencies with respect to most frequent basic block diverge, graal freq {graal_freq:.6e}, perf freq {perf_freq:.6e}', file=fp)

def compare_freq(graal_freq, perf_freq, epsilon=1E-10):
    """
    Compare frequencies computed by graal and measured using perf.

    For low frequencies computed by graal perf has less chance to get a sample in that block so the range gets bigger.
    """
    factor = 100 if graal_freq < 1 else 10 if graal_freq < 10 else 1.5
    return 1 / factor <= (graal_freq + epsilon) / (perf_freq + epsilon) <= factor


class PerfEvent:
    """A simple wrapper around a single recorded even from the perf command"""

    def __init__(self, timestamp, events, period, pc, symbol, dso):
        self.dso = dso
        self.period = int(period)
        self.symbol = symbol
        self.pc = int(pc, 16)
        self.events = events
        self.timestamp = float(timestamp)
        self.samples = 1

    def __str__(self):
        return f'{self.timestamp} {self.pc:x} {self.events} {self.period} {self.symbol} {self.dso}'

    def symbol_name(self):
        if self.symbol == '[unknown]':
            return self.symbol + ' in ' + self.dso
        return self.symbol


class PerfMethod(NamedTuple):
    """Aggregated perf samples for a single method."""
    symbol: str
    dso: str
    total_period: int
    samples: int

    def demangled_name(self, short_class_names: bool = False):
        """Demangles and returns the symbol name."""
        if self.symbol is None or not NativeImageBFDDemangler.is_mangled_name(self.symbol):
            return self.symbol
        try:
            return NativeImageBFDDemangler().format_mangled_name(self.symbol, short_class_names)
        except ValueError:
            out = mx.OutputCapture()
            mx.run(['c++filt', '-n', self.symbol], out=out)
            return repr(out).strip('\n')


class NativeImageBFDDemangler:
    """
    Demangles Java method names created by Native Image.

    The demangling may fail for names not mangled by Native Image (e.g., C++ symbols). The format is described in:
    https://github.com/oracle/graal/blob/master/substratevm/src/com.oracle.svm.hosted/src/com/oracle/svm/hosted/image/NativeImageBFDNameProvider.java
    """

    _primitive_encoding = {'b': 'bool',
                           'a': 'byte',
                           's': 'short',
                           't': 'char',
                           'i': 'int',
                           'l': 'long',
                           'f': 'float',
                           'd': 'double',
                           'v': 'void'}
    """Maps encoded primitive types to their Java equivalents."""

    def __init__(self):
        self._method_encoding: Optional[list[str]] = None
        """Parsed package, class, and method names."""
        self._return_type: Optional[str] = None
        """A parsed and formatted return type."""
        self._parameter_encodings: Optional[list[str]] = None
        """Parsed and formatted parameter types."""
        self._rest: Optional[str] = None
        """The unparsed remainder of the mangled name."""

    @classmethod
    def is_mangled_name(cls, name: Optional[str]) -> bool:
        """Returns whether the provided name is a mangled name."""
        return name and name.startswith('_Z')

    def format_mangled_name(self, mangled: str, short_class_names: bool) -> str:
        """
        Formats the given mangled Java method name.

        The name is formatted using the format: package.Class.method(Classes). If short_class_names is True, the package
        name is omitted.

        For example, _ZN4java4lang6String10startsWithEJbPN4java4lang6StringEi is decoded as
        java.lang.String.startsWith(String, int) (or String.startsWith(String, int) with short_class_names). If the
        provided name was not mangled by the Native Image BFD mangler, the demangling may fail.
        """
        self._read_mangled_name(mangled)
        params = [param.split('.')[-1] for param in self._parameter_encodings]
        method_name = self._method_encoding
        if short_class_names and len(method_name) >= 2:
            method_name = self._method_encoding[:]
            method_name[-2] = method_name[-2].split('.')[-1]
        return f"{'.'.join(method_name)}({', '.join(params)})"

    def _error(self, cause: str):
        """Raises an error with the given cause."""
        raise ValueError(f"Failed to parse mangled a name.\n\n"
                         f"Input: {self._mangled}\n"
                         f"Cause: {cause}\n"
                         f"Position: {self._mangled[:-len(self._rest)]} <HERE> {self._rest}")

    def _read_mangled_name(self, mangled: str):
        """Parses and partially formats the provided mangled name."""
        self._mangled = mangled
        self._rest = mangled
        self._remove_prefix('_Z')
        self._method_encoding = self._read_method_encoding()
        self._return_type = self._read_return_type()
        self._parameter_encodings = self._read_parameter_encodings()

    def _read_base_symbol(self) -> str:
        """
        Reads and returns a length-encoded symbol from the unparsed remainder of the mangled name.

        Reads a number (length) and the following symbol with that length. For example, returns "foo" if the unparsed
        remainder of the mangled name starts with "3foo".
        """
        str_len = 0
        prefix_len = 0
        for ch in self._rest:
            if ch.isdigit():
                str_len = 10 * str_len + int(ch)
                prefix_len += 1
            else:
                break
        if prefix_len == 0:
            self._error('Expected a number.')
        base_symbol = self._rest[prefix_len:prefix_len + str_len]
        self._rest = self._rest[prefix_len + str_len:]
        return base_symbol

    def _remove_prefix(self, prefix: str):
        """
        Removes the provided prefix from the unparsed remainder of the mangled name.

        Checks that the unparsed remainder of the mangled name starts with the given prefix. Raises an error otherwise.
        """
        if not self._rest.startswith(prefix):
            self._error(f"'{prefix}' expected next.")
        self._rest = self._rest[len(prefix):]

    def _read_method_encoding(self, ) -> list[str]:
        """Reads a method encoding from the unparsed remainder of the mangled name, i.e., a package name,
        a class name, and a method name. """
        self._remove_prefix('N')
        method_encoding = []
        while not self._rest.startswith('E'):
            method_encoding.append(self._read_base_symbol())
        self._remove_prefix('E')
        return method_encoding

    def _read_return_type(self) -> Optional[str]:
        """Reads a return type from the unparsed remainder of the mangled name (starting with a 'J')."""
        if self._rest and self._rest.startswith('J'):
            self._remove_prefix('J')
            return self._read_type()
        return None

    def _read_type(self) -> str:
        """Reads and formats a type name from the unparsed remainder of the mangled name."""
        if not self._rest:
            self._error('Expected a type.')
        peek = self._rest[0]
        if peek == 'N':
            self._remove_prefix(peek)
            result = ''
            while not self._rest.startswith('E'):
                result += self._read_type()
            return result
        elif peek == 'P':
            self._remove_prefix(peek)
            return self._read_type()
        elif peek == 'S':
            self._remove_prefix(peek)
            index = self._read_base_36_number()
            if index < 0 or index >= len(self._method_encoding):
                self._error(f'Index out of bounds: {index}')
            return self._method_encoding[index]
        elif peek in self._primitive_encoding:
            self._remove_prefix(peek)
            return self._primitive_encoding[peek]
        else:
            return self._read_base_symbol()

    def _read_base_36_number(self) -> int:
        """Reads a base 36 number from the unparsed remainder of the mangled name, terminated with an underscore."""
        number = 0
        prefix_len = 0
        for ch in self._rest:
            prefix_len += 1
            if ch == '_':
                self._rest = self._rest[prefix_len + 1:]
                return 0 if prefix_len == 1 else number + 1
            elif ch.isdigit():
                number = 36 * number + int(ch)
            else:
                number = 36 * number + ord(ch) - ord('A') + 10
        self._error('Invalid base 36 number.')

    def _read_parameter_encodings(self) -> list[str]:
        """Reads and formats parameter encodings from the unparsed remainder of the mangled name."""
        parameters = []
        while self._rest:
            parameters.append(self._read_type())
        if len(parameters) == 1 and parameters[0] == 'void':
            return []
        return parameters


def _which(executable):
    for path in os.environ['PATH'].split(os.pathsep):
        f = os.path.join(path.strip('"'), executable)
        if os.path.isfile(f) and os.access(f, os.X_OK):
            return f
    return None


class PerfOutput:
    """The decoded output of a perf record execution"""

    _perf_available = None

    def __init__(self, files):
        self.events = []
        self.raw_events = []
        self.total_samples = 0
        self.total_period = 0
        self.top_methods = None
        with files.open_perf_output_file() as fp:
            self.read_perf_output(fp)

        self.merge_perf_events()

    @staticmethod
    def is_supported():
        if PerfOutput._perf_available is None:
            PerfOutput._perf_available = _which('perf') is not None
        return PerfOutput._perf_available

    @staticmethod
    def supports_dash_k_option():
        return subprocess.call(['perf', 'record', '-q', '-k', '1', 'echo'],
                               stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL) == 0

    @staticmethod
    def perf_convert_binary_command(files, is_native_image: bool = False):
        """
        Returns a command to convert a perf binary to a textual file.

        We disable name demangling for executables compiled by Native Image. This is because proftool demangles the
        names itself so that Java method names are formatted as expected.
        """
        convert_cmd = ['perf', 'script', '--fields', 'sym,time,event,dso,ip,sym,period', '-i',
                       files.get_perf_binary_filename()]
        if is_native_image:
            convert_cmd.append('--no-demangle')
        return convert_cmd

    def read_perf_output(self, fp):
        """Parse the perf script output"""
        perf_re = re.compile(
            r'(?P<timestamp>[0-9]+\.[0-9]*):\s+(?P<period>[0-9]*)\s+(?P<events>[^\s]*):\s+'
            r'(?P<pc>[a-fA-F0-9]+)\s+(?P<symbol>.*)\s+\((?P<dso>.*)\)\s*')
        for line in fp.readlines():
            line = line.strip()
            m = perf_re.match(line)
            if m:
                event = PerfEvent(m.group('timestamp'), m.group('events'), m.group('period'),
                                  m.group('pc'), m.group('symbol'), m.group('dso'))
                self.events.append(event)
                self.total_period += event.period
            else:
                raise AssertionError('Unable to parse perf output: ' + line)
        self.total_samples = len(self.events)

    def merge_perf_events(self):
        """Collect repeated events at the same pc into a single PerfEvent."""
        self.raw_events = self.events
        events_by_address = {}
        for event in self.events:
            e = events_by_address.get(event.pc)
            if e:
                e.period = e.period + event.period
                e.samples = e.samples + event.samples
            else:
                # avoid mutating the underlying raw event
                events_by_address[event.pc] = copy.copy(event)
        self.events = events_by_address.values()

    def get_top_methods(self):
        """Get a list of symbols and event counts sorted by hottest first."""
        if not self.top_methods:
            hot_symbols = {}
            for event in self.events:
                key = (event.symbol, event.dso)
                count = hot_symbols.get(key)
                if count is None:
                    count = 0
                count = count + event.period
                hot_symbols[key] = count
            entries = [(s, d, c) for (s, d), c in hot_symbols.items()]

            def count_func(v):
                _, _, c = v
                return c

            entries.sort(key=count_func, reverse=True)
            self.top_methods = entries
        return self.top_methods

    def get_perf_methods(self) -> Iterable[PerfMethod]:
        """Aggregates the samples by (symbol, dso) pairs."""
        methods = {}
        for event in self.events:
            key = (event.symbol, event.dso)
            period_count = methods.get(key)
            if period_count is None:
                methods[key] = [event.period, event.samples]
            else:
                period_count[0] += event.period
                period_count[1] += event.samples
        for key, period_count in methods.items():
            yield PerfMethod(symbol=key[0], dso=key[1], total_period=period_count[0], samples=period_count[1])


class GeneratedAssembly:
    """
    All the assembly generated by the HotSpot JIT including any helpers and the interpreter

    :type code_info: list[CompiledCodeInfo]
    """

    def __init__(self, files, verbose=False):
        """

        :type files: ExperimentFiles
        """
        self.execution_id = None
        self.code_info = []
        self.low_address = None
        self.high_address = None
        self.code_by_address = {}
        self.code_by_id = {}
        self.map = {}
        self.bucket_size = 8192
        with files.open_jvmti_asm_file() as fp:
            self.fp = fp
            tag = self.fp.read(8)
            if tag != filetag:
                raise AssertionError(f'Wrong magic number: Found {tag} but expected {filetag}')
            self.major_version = self.read_jint()
            self.minor_version = self.read_jint()
            self.arch = self.read_string()
            self.timestamp = self.read_timestamp()
            self.java_nano_time = self.read_unsigned_jlong()
            self.read(fp, verbose)
            self.fp = None

        if files.has_log_compilation():
            # try to attribute the nmethods to the JVMTI output so that compile ids are available
            with files.open_log_compilation_file() as fp:
                tree = ElementTree.parse(fp)
                self.execution_id = tree.getroot().get('process')
                # build a map from the entry pc to the nmethod information
                nmethods = {}
                for nmethod in mx_logcompilation.collect_nmethods(tree):
                    current = nmethods.get(nmethod.entry_pc)
                    if current is None:
                        current = list()
                        nmethods[nmethod.entry_pc] = current
                    current.append(nmethod)

            # multiple pieces of code could end up with the same entry point but both the LogCompilation output
            # and the JVMTI asm dump should have the same linear ordering of nmethod definitions.  This mean the
            # first nmethod with an entry pc is also the first code info with that pc, so it suffices to just pick
            # the nmethod at the head of the list.
            for code in self.code_info:
                if code.generated:
                    # stubs aren't mentioned in the LogCompilation output
                    continue

                matches = nmethods.get(code.code_begin())
                if matches:
                    found = matches.pop(0)
                    code.set_nmethod(found)
                    self.code_by_id[code.get_compile_id()] = code
                    continue
                mx.abort(f'Unable to find matching nmethod for code {code}')

        if files.has_block_info():
            for code in self.code_info:
                if not code.nmethod:
                    continue

                compile_id = code.get_compile_id()

                if not files.has_block_info(compile_id):
                    # methods that are not compiled with graal don't have a block info file
                    continue

                with files.open_block_info(compile_id) as block_file:
                    blocks = []
                    for line in block_file:
                        [block_id, start, end, freq] = line.split(',')[:4]
                        blocks.append(BasicBlock(int(block_id), int(start), int(end), float(freq)))
                    code.set_basic_blocks(blocks)

    def decoder(self, fp=sys.stdout):
        if self.arch == 'amd64':
            return AMD64DisassemblerDecoder(fp)
        if self.arch == 'aarch64':
            return AArch64DisassemblyDecoder(fp)
        raise AssertionError('Unknown arch ' + self.arch)

    def round_up(self, value):
        return self.bucket_size * int((value + self.bucket_size - 1) / self.bucket_size)

    def round_down(self, value):
        return self.bucket_size * int(value / self.bucket_size)

    def build_search_map(self):
        for code in self.code_info:
            for pc in range(self.round_down(code.code_begin()), self.round_up(code.code_end()), self.bucket_size):
                entries = self.map.get(pc)
                if not entries:
                    entries = []
                    self.map[pc] = entries
                entries.append(code)

    def add(self, code_info):
        self.code_info.append(code_info)
        if not self.low_address:
            self.low_address = code_info.code_begin()
            self.high_address = code_info.code_end()
        else:
            self.low_address = min(self.low_address, code_info.code_begin())
            self.high_address = max(self.high_address, code_info.code_end())
        self.code_by_address[code_info.code_addr] = code_info

    def read(self, fp, verbose=False):
        while True:
            tag = self.read_jint()
            if not tag:
                return
            if tag == DynamicCodeTag:
                timestamp = self.read_timestamp()
                name = self.read_string()
                code_addr = self.read_unsigned_jlong()
                code_size = self.read_jint()
                code = fp.read(code_size)
                code_info = CompiledCodeInfo(name, timestamp, code_addr, code_size, code, True)
                self.add(code_info)
                if verbose:
                    print(f'Parsed DynamicCode {code_info}')
            elif tag == CompiledMethodUnloadTag:
                timestamp = self.read_timestamp()
                code_addr = self.read_unsigned_jlong()
                nmethod = self.code_by_address[code_addr]
                if not nmethod:
                    message = f"missing code for {code_addr}"
                    mx.abort(message)
                nmethod.set_unload_time(timestamp)
                if verbose:
                    print(f'Parsed CompiledMethodUnload {code_info}')
            elif tag == CompiledMethodLoadTag:
                timestamp = self.read_timestamp()
                code_addr = self.read_unsigned_jlong()
                code_size = self.read_jint()
                code = fp.read(code_size)
                tag = self.read_jint()
                if tag != MethodsTag:
                    mx.abort("Expected MethodsTag")
                methods_count = self.read_jint()
                methods = []
                for _ in range(methods_count):
                    class_signature = self.read_string()
                    method_name = self.read_string()
                    method_signature = self.read_string()
                    source_file = self.read_string()

                    line_number_table_count = self.read_jint()
                    line_number_table = []
                    for _ in range(line_number_table_count):
                        line_number_table.append((self.read_unsigned_jlong(), self.read_jint()))
                    method = Method(class_signature, method_name, method_signature, source_file, line_number_table)
                    methods.append(method)

                tag = self.read_jint()
                if tag != DebugInfoTag:
                    mx.abort("Expected DebugInfoTag")

                numpcs = self.read_jint()
                debug_infos = []
                for _ in range(numpcs):
                    pc = self.read_unsigned_jlong()
                    numstackframes = self.read_jint()
                    frames = []
                    for _ in range(numstackframes):
                        frames.append(DebugFrame(methods[self.read_jint()], self.read_jint()))
                    debug_infos.append(DebugInfo(pc, frames))
                nmethod = CompiledCodeInfo(methods[0].format_name(), timestamp, code_addr, code_size, code,
                                           False, debug_infos, methods)
                self.add(nmethod)
                if verbose:
                    print(f'Parsed CompiledMethod {nmethod}')
            else:
                raise AssertionError(f"Unexpected tag {tag}")

    def attribute_events(self, perf_data):
        assert self.low_address is not None and self.high_address is not None
        attributed = 0
        unknown = 0
        missing = 0
        for event in perf_data.events:
            if self.low_address <= event.pc < self.high_address:
                if self.add_event(event):
                    attributed += 1
                else:
                    missing += 1
            elif event.symbol == '[Unknown]':
                unknown += 1
        if missing > 50:
            # some versions of JVMTI leave out the stubs section of nmethod which occassionally gets ticks
            # so a small number of missing ticks should be ignored.
            mx.warn(f'{missing} events of {attributed + missing} could not be mapped to generated code')

    def add_event(self, event):
        code_info = self.find(event.pc, event.timestamp)
        if code_info:
            code_info.add(event)
            if code_info.generated:
                event.dso = '[Generated]'
            else:
                event.dso = '[JIT]'
            event.symbol = code_info.name
            return True
        else:
            return False

    def search(self, pc):
        matches = []
        for code in self.code_info:
            if code.contains(pc):
                matches.append(code)
        return matches

    def get_stub_name(self, pc):
        """Map a pc to the name of a stub plus an offset."""
        for x in self.search(pc):
            if x.generated:
                offset = pc - x.code_addr
                if offset:
                    return f'{x.name}+0x{offset:x}'
                return x.name
        return None

    def find(self, pc, timestamp):
        if not self.map:
            self.build_search_map()
        index = self.round_down(pc)
        entries = self.map.get(index)
        if entries:
            entries = [x for x in entries if x.contains(pc)]
        if not entries:
            m = self.search(pc)
            if m:
                raise AssertionError(
                    f'find has no hits for pc {pc:x} and timestamp {timestamp} but search found: {str([str(x) for x in m])}')
            return None

        # only a single PC match so don't bother checking the timestamp
        if len(entries) == 1:
            return entries[0]

        # check for an exact match first
        for x in entries:
            if x.contains(pc, timestamp):
                return x

        # events can occur before HotSpot has notified about the assembly so pick
        # the earliest method that was unloaded after the timestamp
        for x in entries:
            if x.unload_time is None or x.unload_time > timestamp:
                return x
        return None

    def print_all(self, codes=None, fp=sys.stdout, show_call_stack_depth=None, hide_perf=False,
                  threshold=None, short_class_names=False):
        stub_name_cache = {}
        for h in codes or self.code_info:
            if h.name == 'Interpreter':
                continue
            decoder = self.decoder(fp=fp)

            def get_call_annotations(instruction):
                return h.get_code_annotations(instruction.address, show_call_stack_depth=show_call_stack_depth,
                                              hide_perf=hide_perf, short_class_names=short_class_names)

            def get_stub_call_name(instruction):
                if 'call' in instruction.groups():
                    call_pc = instruction.insn.operands[0].imm
                    result = stub_name_cache.get(call_pc)
                    if result:
                        return None if result == stub_name_cache else result
                    result = self.get_stub_name(call_pc)
                    stub_name_cache[call_pc] = result or stub_name_cache
                    return result
                return None

            decoder.add_annotator(get_stub_call_name)
            decoder.add_annotator(get_call_annotations)

            h.disassemble(decoder, short_class_names=short_class_names, threshold=threshold)

    def read_jint(self):
        b = self.fp.read(4)
        if not b:
            return None
        assert b[3] is not None, 'input truncated'
        return int.from_bytes(b, byteorder='big', signed=True)

    def read_unsigned_jlong(self):
        b = self.fp.read(8)
        if not b:
            return None
        assert b[7] is not None, 'input truncated'
        return int.from_bytes(b, byteorder='big', signed=False)

    def read_string(self):
        length = self.read_jint()
        if length == -1:
            return None
        if length == 0:
            return ''
        body = self.fp.read(length)
        return body.decode('utf-8')

    def read_timestamp(self):
        sec = self.read_unsigned_jlong()
        nsec = self.read_unsigned_jlong()
        return sec + (nsec / 1000000000.0)

    def top_methods(self, include=None):
        entries = self.code_info
        if include:
            entries = [x for x in entries if include(x)]
        entries.sort(key=lambda x: x.total_period, reverse=True)
        return entries


def find_jvmti_asm_agent():
    """Find the path the JVMTI agent that records the disassembly"""
    d = mx.dependency('com.oracle.jvmtiasmagent')
    for source_file, _ in d.getArchivableResults(single=True):
        if not os.path.exists(source_file):
            mx.warn(f'jvmciasmagent hasn\'t been built yet, attempting to build it')
            mx.build(['--dependencies', 'com.oracle.jvmtiasmagent'])
            # if mx.buildbuild fails then it will abort so control shouldn't reach here
            # but it's best to ensure it actually exists.
            if not os.path.exists(source_file):
                mx.abort('Unable to find com.oracle.jvmtiasmagent')
        return source_file
    return None


def is_executable_compiled_by_native_image(command: str) -> bool:
    """
    Infers whether the provided command is an executable compiled by Native Image.

    This is done by locating the executable and checking whether it contains a section named ".svm_heap".
    """
    executable_path = mx.OutputCapture()
    sections = mx.OutputCapture()
    if mx.run(['which', command], nonZeroIsFatal=False, out=executable_path) != 0 or \
       mx.run(['readelf', '--section-headers', repr(executable_path).strip('\n')],
              nonZeroIsFatal=False, out=sections) != 0:
        mx.warn(f'Could not find out whether "{command}" is an executable compiled by Native Image.')
        return False
    return '.svm_heap' in repr(sections)


@mx.command('mx', 'profrecord', '[options]')
@mx.suite_context_free
def profrecord(args):
    """
    Capture the profile of a Java program.

    The command also works with executables compiled by Native Image. The type of executable is automatically inferred.
    """
    # capstone is not required for the capture step
    parser = ArgumentParser(description='Capture a profile of a Java program.', prog='mx profrecord')
    parser.add_argument('-s', '--script', help='Emit a script to run and capture annotated assembly',
                        action='store_true')
    parser.add_argument('-E', '--experiment',
                        help='The directory containing the data files from the experiment',
                        action='store', required=True)
    parser.add_argument('-O', '--overwrite', help='Overwrite an existing dump directory',
                        action='store_true')
    parser.add_argument('-B', '--with-bb-info',
                        help='Enables dumping of the basic block information used by the checkblocks command',
                        action='store_true')
    parser.add_argument('-D', '--dump-hot',
                        help='Run the program and then rerun it with dump options enabled for the hottest methods',
                        action='store_true')
    parser.add_argument('-l', '--dump-level', help='The Graal dump level to use with the --dump-hot option',
                        action='store', default=1)
    parser.add_argument('-L', '--limit', help='The number of hot methods to dump with the --dump-hot option',
                        action='store', default=5)
    parser.add_argument('-F', '--frequency', help='Frequency argument passed to perf',
                        action='store', default=1000)
    parser.add_argument('-e', '--event', help='Event argument passed to perf.\n'
                                              'Valid values can found with \'perf list\'',
                        action='store', default='cycles')
    parser.add_argument('command', nargs=REMAINDER, default=[], metavar='java arg [arg ...]')
    options = parser.parse_args(args)
    if len(options.command) > 0 and options.command[0] == '--':
        options.command = options.command[1:]
    if len(options.command) == 0:
        mx.abort('Command to execute is required')

    files = FlatExperimentFiles.create(options.experiment, options.overwrite)

    if not PerfOutput.is_supported() and not options.script:
        mx.abort('Linux perf is unsupported on this platform')

    is_native_image = is_executable_compiled_by_native_image(options.command[0])
    vm_extra_args = None
    if options.with_bb_info:
        if is_native_image or not vm_has_bb_dumping(options.command[0]):
            mx.abort('The given vm does not allow dumpling of basic block information!')
        vm_extra_args = [f'-Dgraal.DumpPath={files.create_dump_dir()}', '-Dgraal.PrintBBInfo=true']

    if is_native_image:
        full_cmd = build_capture_args(files, options=options, is_native_image=True)[0] + options.command
    else:
        full_cmd = build_capture_command(files, options.command, extra_vm_args=vm_extra_args, options=options)
    convert_cmd = PerfOutput.perf_convert_binary_command(files, is_native_image)
    if options.script:
        print(mx.list_to_cmd_line(full_cmd))
        print(f'{mx.list_to_cmd_line(convert_cmd)} > {files.get_perf_output_filename()}')
    else:
        mx.run(full_cmd, nonZeroIsFatal=False)
        if not files.has_perf_binary():
            mx.abort('No perf binary file found')

        # convert the perf binary data into text format
        with files.open_perf_output_file(mode='w') as fp:
            mx.run(convert_cmd, out=fp)

        if options.dump_hot:
            if is_native_image:
                mx.abort('The option "dump hot" is not available for native executables.')
            assembly = GeneratedAssembly(files)
            perf = PerfOutput(files)
            assembly.attribute_events(perf)
            top = assembly.top_methods(include=lambda x: not x.generated and x.total_period > 0)[:options.limit]
            dump_path = files.create_dump_dir()
            method_filter = ','.join([x.methods[0].method_filter_format() for x in top])
            dump_arguments = [f'-Dgraal.Dump=:{options.dump_level}',
                              '-Dgraal.MethodFilter=' + method_filter,
                              '-Dgraal.DumpPath=' + dump_path]
            if options.with_bb_info:
                dump_arguments.append('-Dgraal.PrintBBInfo=true')

            # rerun the program with the new options capturing the dump in the experiment directory.
            # This overwrites the original profile information with a new profile that might be different
            # because of the effects of dumping.  This command might need to be smarter about the side effects
            # of dumping on the performance since the overhead of dumping might perturb the execution.  It's not
            # entirely clear how to cope with that though.
            full_cmd = build_capture_command(files, options.command, extra_vm_args=dump_arguments, options=options)
            convert_cmd = PerfOutput.perf_convert_binary_command(files)
            mx.run(full_cmd)
            with files.open_perf_output_file(mode='w') as fp:
                mx.run(convert_cmd, out=fp)


@mx.command('mx', 'profpackage', '[options]')
@mx.suite_context_free
def profpackage(args):
    """Package a directory based proftool experiment into a zip."""
    # capstone is not required for packaging
    parser = ArgumentParser(description='Ensure a directory based proftool experiment has perf output and '
                                        'then package the directory into a zip.',
                            prog='mx profpackage')
    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument('-D', '--delete',
                       help='Delete the directory after creating the zip',
                       action='store_true')
    group.add_argument('-n', '--no-zip',
                       help='Don\'t create the zip file',
                       action='store_true')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('-E', '--experiment',
                       help='The directory containing the data files from an experiment',
                       action='store')
    group.add_argument('experiments',
                       help='One or more directories containing the data files from experiments',
                       action='store', nargs='*', default=[])
    options = parser.parse_args(args)
    if options.experiment:
        options.experiments = [options.experiment]
    for experiment in options.experiments:
        files = FlatExperimentFiles(directory=experiment)
        files.ensure_perf_output()
        if not options.no_zip:
            name = files.package()
            print(f'Created {name}')
        if options.delete:
            shutil.rmtree(experiment)


def build_capture_args(files, extra_vm_args=None, options=None, is_native_image=False):
    perf_binary_file = files.get_perf_binary_filename()
    perf_cmd = ['perf', 'record']
    if not PerfOutput.is_supported() or PerfOutput.supports_dash_k_option():
        perf_cmd += ['-k', '1']
    if options:
        frequency = options.frequency
        event = options.event
    else:
        frequency = 1000
        event = 'cycles'

    perf_cmd += ['--freq', str(frequency), '--event', event, '--output', perf_binary_file]
    if is_native_image:
        vm_args = ['-Dnative-image.benchmark.extra-image-build-argument=-H:-DeleteLocalSymbols',
                   '-Dnative-image.benchmark.extra-image-build-argument=-H:+SourceLevelDebug']
    else:
        jvmti_asm_file = files.get_jvmti_asm_filename()
        vm_args = [f'-agentpath:{find_jvmti_asm_agent()}={jvmti_asm_file}', '-XX:+UnlockDiagnosticVMOptions',
                   '-XX:+DebugNonSafepoints', '-Dgraal.TrackNodeSourcePosition=true', '-XX:+LogCompilation',
                   f'-XX:LogFile={files.get_log_compilation_filename()}']
    if extra_vm_args:
        vm_args += extra_vm_args
    return perf_cmd, vm_args


def build_capture_command(files, command_line, extra_vm_args=None, options=None):
    executable = command_line[0]
    user_args = command_line[1:]
    perf_cmd, vm_args = build_capture_args(files, extra_vm_args, options)

    # Transform JVM options for Truffle language launchers
    if os.path.exists(executable) and re.search(r'/languages/\w+/bin/', os.path.realpath(executable)):
        for i in range(len(vm_args)):
            vm_args[i] = '--vm.' + vm_args[i][1:]

    full_cmd = perf_cmd + [executable] + vm_args + user_args
    return full_cmd


class SuppressNoneArgs(Action):
    """
    Mixing positionals and explicit arguments can result in overwriting the value with None so suppress writes of None.
    """

    def __call__(self, parser, namespace, values, option_string=None):
        if values:
            setattr(namespace, self.dest, values)


@mx.command('mx', 'profhot', '[options]')
@mx.suite_context_free
def profhot(args):
    """Display the top hot methods and their annotated disassembly"""
    parser = ArgumentParser(prog='mx profhot',
                            description='Display the top hot methods and their annotated disassembly',
                            formatter_class=RawTextHelpFormatter)

    parser.add_argument('-n', '--limit', help='Show the top n entries', action='store', default=10, type=int)
    parser.add_argument('-t', '--threshold',
                        help='Minimum percentage for a pc to be considered hot when building regions.\n'
                        'A threshold of 0 shows the all the generated code instead of just the hot regions.',
                        action='store', type=float, default=0.001)
    parser.add_argument('-o', '--output', help='Write output to named file.  Writes to stdout by default.',
                        action='store')
    parser.add_argument('-c', '--call-stack-depth', help='Limit the number of Java frames printed from debug info.',
                        type=int, default=None)
    parser.add_argument('-s', '--short-class-names', help='Drop package names from class names',
                        action='store_true')
    parser.add_argument('-H', '--hide-perf', help='Don\'t display perf information in the output.\n'
                        'This can be useful when comparing the assembly from different runs.')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('-E', '--experiment',
                       help='The directory containing the data files from the experiment',
                       action='store', required=False)
    group.add_argument('experiment',
                       help='The directory containing the data files from the experiment',
                       action=SuppressNoneArgs, nargs=OPTIONAL)
    options = parser.parse_args(args)
    files = ExperimentFiles.open(options)
    files.ensure_perf_output()
    perf_data = PerfOutput(files)
    fp = sys.stdout
    if options.output:
        fp = open(options.output, 'w')
    if files.is_native_image_experiment():
        print('Hot code:', file=fp)
        print('  Percent   Name', file=fp)
        perf_methods = sorted(perf_data.get_perf_methods(), key=lambda method: method.total_period, reverse=True)
        for code in islice(perf_methods, options.limit):
            print(f'   {100 * (float(code.total_period) / perf_data.total_period):5.2f}%   {code.demangled_name(options.short_class_names)}',
                  file=fp)
        if isinstance(files, FlatExperimentFiles):
            perf_report = f'perf report -Mintel --sort symbol -i {files.perf_binary_filename}'
            print(f'\nDisplay annotated code by running:\n  {perf_report}', file=fp)
        else:
            print(f'\nPlease unzip the experiment display annotated code.', file=fp)
    else:
        check_capstone_import('profhot')
        assembly = GeneratedAssembly(files)
        assembly.attribute_events(perf_data)
        entries = perf_data.get_top_methods()
        non_jit_entries = [(s, d, c) for s, d, c in entries if d not in ('[JIT]', '[Generated]')]
        print('Hot C functions:', file=fp)
        print('  Percent   Name', file=fp)
        for symbol, _, count in non_jit_entries[:options.limit]:
            print(f'   {100 * (float(count) / perf_data.total_period):5.2f}%   {symbol}', file=fp)
        print('', file=fp)

        hot = assembly.top_methods(lambda x: x.total_period > 0)
        hot = hot[:options.limit]
        print('Hot generated code:', file=fp)
        print('  Percent   Name', file=fp)
        for code in hot:
            print(f'   {100 * (float(code.total_period) / perf_data.total_period):5.2f}%   {code.format_name(options.short_class_names)}', file=fp)
        print('', file=fp)

        assembly.print_all(hot, fp=fp, show_call_stack_depth=options.call_stack_depth,
                           hide_perf=options.hide_perf, threshold=options.threshold,
                           short_class_names=options.short_class_names)
    if fp != sys.stdout:
        fp.close()

@mx.command('mx', 'checkblocks', '[options]')
@mx.suite_context_free
def checkblocks(args):
    """Check that block frequencies computed by graal match frequecies measured using pref"""
    parser = ArgumentParser(description='Check that block frequencies computed by graal match frequecies measured using pref', prog='mx checkblocks')
    parser.add_argument('-n', '--limit', help='Check block frequencies for the top n functions;', action='store', default=10, type=int)
    parser.add_argument('-o', '--output', help='Write output to named file.  Writes to stdout by default.',
                        action='store')
    parser.add_argument('experiment',
                       help='The directory containing the data files from the experiment',
                       action='store')
    parser.add_argument('-b', '--block_info',
                       help='The directory containing the block information data files from the experiment if the given experiment does not have a graal_dump directory with basic block info files in it',
                       action='store', default=None)
    parser.add_argument('-r', '--raw',
                        help='Write the raw frequencies of the basic blocks to the output',
                        action='store_true')
    options = parser.parse_args(args)
    files = ExperimentFiles.open(options)
    files.ensure_perf_output()
    if not files.has_block_info():
        mx.abort('No directory containing basic block information found!')
    perf_data = PerfOutput(files)
    assembly = GeneratedAssembly(files)
    assembly.attribute_events(perf_data)
    fp = sys.stdout
    if options.output:
        fp = open(options.output, 'w')

    hot = assembly.top_methods(lambda x: x.total_period > 0 and x.basic_blocks)
    hot = hot[:options.limit]

    for code in hot:
        print(f"for hot method {code.name} with {len(code.basic_blocks)} basic blocks, got {code.total_samples} samples", file=fp)
        if code.basic_blocks:
            code.check_basic_blocks_0_rel_freq(fp=fp)
            code.check_basic_blocks_rel_freq_most(fp=fp)

    if options.raw:
        for code in hot:
            print(f'\nBasic blocks info for {code.name}')
            for b in code.basic_blocks:
                print(f'id = {b.id:4}, graal freq = {b.freq:.6e}, samples = {b.samples:10}, period = {b.period:15}, period normalized = {b.period / code.total_period:.5f}')
            print('')

    if fp != sys.stdout:
        fp.close()

@mx.command('mx', 'profasm', '[options]')
@mx.suite_context_free
def profasm(args):
    """Dump the assembly from a jvmtiasmagent dump"""
    check_capstone_import('profasm')
    parser = ArgumentParser(description='Dump the assembly from a jvmtiasmagent dump', prog='mx profasm')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('-E', '--experiment',
                       help='The directory containing the data files from the experiment',
                       action='store', required=False)
    group.add_argument('experiment',
                       help='The directory containing the data files from the experiment',
                       action=SuppressNoneArgs, nargs='?')
    options = parser.parse_args(args)
    files = ExperimentFiles.open(options)
    assembly = GeneratedAssembly(files)
    assembly.print_all(threshold=0)


@mx.command('mx', 'profjson', '[options]')
@mx.suite_context_free
def profjson(args):
    """Dump executed methods to JSON."""
    parser = ArgumentParser(description='Dump executed methods to JSON.', prog='mx profjson')
    parser.add_argument('-o', '--output', help='Write output to named file.  Writes to stdout by default.',
                        action='store')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('-E', '--experiment',
                       help='The directory containing the data files from the experiment.',
                       action='store', required=False)
    group.add_argument('experiment',
                       help='The directory containing the data files from the experiment.',
                       action=SuppressNoneArgs, nargs='?')
    options = parser.parse_args(args)
    files = ExperimentFiles.open(options)
    files.ensure_perf_output()
    perf_data = PerfOutput(files)
    fp = sys.stdout
    if options.output:
        fp = open(options.output, 'w')
    if files.is_native_image_experiment():
        perf_data.merge_perf_events()
        out = {
            'compilationKind': 'AOT',
            'totalPeriod': perf_data.total_period,
            'code': [
                {
                    'name': method.demangled_name(),
                    'period': method.total_period,
                }
                for method in perf_data.get_perf_methods()
            ]
        }
    else:
        assembly = GeneratedAssembly(files)
        assembly.attribute_events(perf_data)
        out = {
            'compilationKind': 'JIT',
            'totalPeriod': perf_data.total_period,
            'executionId': assembly.execution_id,
            'code': [
                {
                    'compileId': code.get_compile_id(),
                    'name': code.format_name(),
                    'level': code.nmethod.level if code.nmethod else None,
                    'period': code.total_period,
                }
                for code in assembly.code_info
                if code.total_period > 0
            ]
        }
    json.dump(out, fp=fp, indent=4)


class ProftoolProfiler(mx_benchmark.JVMProfiler):
    """
    Use perf on linux and a JVMTI agent to capture Java profiles.
    """

    def __init__(self, with_bb_info=False):
        super(ProftoolProfiler, self).__init__()
        self.filename = None
        self.with_bb_info = with_bb_info
        self.vm = None

    def name(self):
        if self.with_bb_info:
            return "proftool-with-bb"
        else:
            return "proftool"

    def version(self):
        return "1.0"

    def libraryPath(self):
        return find_jvmti_asm_agent()

    def sets_vm_prefix(self):
        return True

    def additional_options(self, dump_path):
        if not self.nextItemName:
            return [], []
        directory = os.path.join(dump_path, self.filename)
        files = FlatExperimentFiles.create(directory, overwrite=True)
        if self.vm.name() == 'native-image':
            perf_cmd, vm_args = build_capture_args(files, is_native_image=True)
        else:
            extra_vm_args = ["-Dgraal.PrintBBInfo=true",
                             f"-Dgraal.DumpPath={files.create_dump_dir()}"] if self.with_bb_info else None
            perf_cmd, vm_args = build_capture_args(files, extra_vm_args=extra_vm_args)

        # reset the next item name since it has just been consumed
        self.nextItemName = None
        return vm_args, perf_cmd

    def setup(self, benchmarks, bmSuiteArgs):
        super(ProftoolProfiler, self).setup(benchmarks, bmSuiteArgs)
        self.vm = mx_benchmark.java_vm_registry.get_vm_from_suite_args(bmSuiteArgs)
        if self.with_bb_info:
            # check that the vm have the PrintBBInfo option availible
            if not vm_has_bb_dumping(vm=self.vm):
                mx.abort("The vm does not allow dumping of basic block information.")

        import datetime
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
        if self.nextItemName:
            self.filename = f"proftool_{self.nextItemName}_{timestamp}"
        else:
            self.filename = f"proftool_{timestamp}"


if PerfOutput.is_supported():
    try:
        mx_benchmark.register_profiler(ProftoolProfiler())
        mx_benchmark.register_profiler(ProftoolProfiler(with_bb_info=True))
    except AttributeError:
        mx.warn('proftool unable to register profiler')
