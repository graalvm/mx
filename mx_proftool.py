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
import os
import re
import shutil
import struct
import subprocess
import sys
import zipfile
from abc import ABCMeta, abstractmethod
from argparse import ArgumentParser, Action, OPTIONAL, RawTextHelpFormatter, REMAINDER
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


def check_capstone_import(name):
    try:
        import capstone  # pylint: disable=unused-variable, unused-import
    except ImportError as e:
        mx.abort(
            '{}\nThe capstone module is required to support \'{}\'. Try installing it with `pip install capstone`'.format(
                e, name))


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


class ExperimentFiles(mx._with_metaclass(ABCMeta), object):
    """A collection of data files from a performance data collection experiment."""

    def __init__(self):  # pylint: disable=super-init-not-called
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
            mx.abort('Experiment \'{}\' does not exist'.format(options.experiment))
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


class FlatExperimentFiles(ExperimentFiles):
    """A collection of data files from a performance data collection experiment."""

    def __init__(self, directory, block_info=None, jvmti_asm_name='jvmti_asm_file', perf_binary_name='perf_binary_file',
                 perf_output_name='perf_output_file', log_compilation_name='log_compilation'):
        super(FlatExperimentFiles, self).__init__()
        self.dump_path = None
        if not os.path.isdir(directory):
            raise AssertionError('Must be directory')
        self.directory = os.path.abspath(directory)
        assert block_info is None or os.path.isdir(block_info), "Must be directory"
        self.block_info = os.path.abspath(block_info) if block_info else None
        self.jvmti_asm_filename = os.path.join(directory, jvmti_asm_name)
        self.perf_binary_filename = os.path.join(directory, perf_binary_name)
        self.perf_output_filename = os.path.join(directory, perf_output_name)
        self.log_compilation_filename = os.path.join(directory, log_compilation_name)


    @staticmethod
    def create(experiment, overwrite=False):
        experiment = os.path.abspath(experiment)
        if os.path.exists(experiment):
            if not overwrite:
                mx.abort('Experiment file already exists: {}'.format(experiment))
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
            self.dump_path = os.path.join(self.directory, 'dump')
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
                mx.abort('perf data file \'{}\' is missing'.format(self.perf_binary_filename))
            convert_cmd = PerfOutput.perf_convert_binary_command(self)
            # convert the perf binary data into text format
            with self.open_perf_output_file(mode='w') as fp:
                mx.run(convert_cmd, out=fp)
            print('Created perf output file in {}'.format(self.directory))

    def package(self, name=None):
        self.ensure_perf_output()

        directory_name = os.path.basename(self.directory)
        parent = os.path.dirname(self.directory)
        if not name:
            name = directory_name
        return shutil.make_archive(name, 'zip', root_dir=parent, base_dir=directory_name)

    def has_block_info(self):
        return self.block_info and os.path.isdir(self.block_info)

    def find_block_info(self, compilation_id):
        assert self.has_block_info(), "Must have block information"
        reg = re.compile('^HotSpot(OSR)?Compilation-{}\\[.*\\]$'.format(compilation_id))
        dirs = os.listdir(self.block_info)
        found = [d for d in dirs if re.search(reg, d)]
        assert len(found) <= 1, "Multiple block information file found for compilation id {}".format(compilation_id)
        if not found:
            return None
        else:
            return found[0]

    def open_block_info(self, compilation_id, block_info_file_name='block_info'):
        found = self.find_block_info(compilation_id)
        path = os.path.join(self.block_info, found, block_info_file_name)
        assert os.path.isfile(path), "Block info file missing for {}".format(found)
        return open(path)


class ZipExperimentFiles(ExperimentFiles):
    """A collection of data files from a performance data collection experiment."""

    def __init__(self, filename):
        super(ZipExperimentFiles, self).__init__()
        self.experiment_file = ZipFile(filename)
        self.jvmti_asm_file = self.find_file('jvmti_asm_file')
        self.perf_output_filename = self.find_file('perf_output_file')
        self.log_compilation_filename = self.find_file('log_compilation', error=False)

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
                instructions.append(Instruction(code_addr + decoded_bytes, '.byte', '{:0x}'.format(code[decoded_bytes]),
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
                message = 'Unexpected annotation: {}'.format(a)
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
            print('Unattributed pcs {}'.format(['{:x}'.format(x) for x in list(hotpc)]))
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
                self.print("Hot region {}".format(region))
            for i, prefix, annotations in instructions[begin:end]:
                hex_bytes = ''
                if self.hex_bytes:
                    hex_bytes = ' '.join(['{:02x}'.format(b) for b in i.bytes])
                if prefix is None:
                    prefix = ' ' * prefix_width
                else:
                    prefix = prefix_format.format(prefix)
                assert len(prefix) == prefix_width, '{} {}'.format(prefix, prefix_width)
                line = '{}0x{:x}:\t{}\t{}\t{}'.format(prefix, i.address, i.mnemonic, i.operand, hex_bytes)
                line = line.expandtabs()
                if annotations:
                    padding = ' ' * len(line)
                    lines = [padding] * len(annotations)
                    lines[0] = line
                    for a, b in zip(lines, annotations):
                        self.print('{}; {}'.format(a, b))
                else:
                    self.print(line)
            if threshold != 0:
                self.print("End of hot region {}".format(region))
            self.print('')
            region += 1

        last, _, _ = instructions[-1]
        decode_end = last.address + last.size
        buffer_end = code.code_addr + len(code.code)
        if decode_end != buffer_end:
            self.print('Skipping {} bytes {:x} {:x} '.format(buffer_end - decode_end, buffer_end, decode_end))


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

class Block:
    """A cfg block"""

    def __init__(self, block_id, start, end, freq):
        self.id = block_id
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
        return '{}:{}'.format(self.method.format_name(with_arguments=False, short_class_names=short_class_names), self.bci)


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
        self.blocks = None

    def __str__(self):
        return '0x{:x}-0x{:x} {} {}-{}'.format(self.code_begin(), self.code_end(), self.name, self.timestamp,
                                               self.unload_time or '')

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
                   self.name.startswith('java.lang.invoke.LambdaForm'), '{} != {}'.format(self.name,
                                                                                          nmethod_name)
            # correct the method naming
            nmethod.method = self.methods[0]
        # update the name to include the LogCompilation id and any truffle names
        self.name = str(nmethod)

    def set_blocks(self, blocks):
        self.blocks = blocks

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
        if self.blocks:
            # block_found = False
            for b in self.blocks:
                if self.code_begin() + b.start <= event.pc < self.code_begin() + b.end:
                    # block_found = True
                    b.period += event.period
                    b.samples += event.samples
            # if not block_found:
            #     print('Sample not in a block !! method {}, sample {}'.format(self, event))

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
                prefix = '{:5.2f}%'.format(100.0 * event.period / float(self.total_period))

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
        decoder.print('0x{:x}-0x{:x} (samples={}, period={})'.format(self.code_begin(), self.code_end(),
                                                                     self.total_samples, self.total_period))
        hotpc = {}
        for event in self.events:
            event = copy.copy(event)
            event.percent = event.period * 100 / self.total_period
            hotpc[event.pc] = event
        decoder.disassemble(self, hotpc, short_class_names=short_class_names, threshold=threshold)
        decoder.print('')

    def check_blocks_0_rel_freq(self, fp=sys.stdout):
        """Check the relative frequencies of each block with respect to block 0"""
        assert self.blocks and len(self.blocks) > 0, "Must have blocks information"
        b0 = self.blocks[0]
        if b0.samples == 0:
            print(f'[WARRNING] In method {self.format_name(short_class_names=True)}\n\tblock 0 got {b0.samples} samples', file=fp)
            return

        # error = 0
        # error_sample = 0
        # samples_in_blocks = 0
        average_samples_per_block = self.total_samples / len(self.blocks)
        # average_period_per_block = self.total_period  / len(self.blocks)
        for b in [b for b in self.blocks if b.id != b0.id and b.samples >= average_samples_per_block]:
            # samples_in_blocks += b.samples
            perf_freq = b.period / b0.period
            if not compare_freq(b.freq, perf_freq):
                print(f'[ERROR] In method {self.format_name(short_class_names=True)}\n\tblock id {b.id:5}, relative frequencies with respect to first block diverge, graal freq {b.freq:.2e}, perf freq {perf_freq:.2e}', file=fp)


            # if b.freq >= 10 and len(self.blocks) < self.total_samples:
            #     print('High frequency block {}, found {}, block period {}, block samples {}, total_period {}, total_samples {}, #blocks in method {}'.format(b.freq, perf_freq, b.period, b.samples, self.total_period, self.total_samples, len(self.blocks)), file=fp)
            # if (b.freq < perf_freq / 10 or perf_freq * 10 < b.freq) and b.freq >= 1:
            #     print('In method {} block {}, graal_freq={}, perf_freq={}'.format(self.name, b.id, b.freq, perf_freq), file=fp)
                # error += 1
                # error_sample += b.samples
        # if error > 0:
        #         print('Error {} in method with total_period {}, total_samples {}, #blocks in method {}, {} samples in blocks, {} samples used in error blocks'.format(error, self.total_period, self.total_samples, len(self.blocks), samples_in_blocks, error_sample), file=fp)

    def check_blocks_rel_freq_most(self, fp=sys.stdout):
        """Check the relative frequencies of each block with respect to the most frequent block"""
        assert self.blocks and len(self.blocks) > 0, "Must have blocks information"

        # blocks_by_graal_freq = sorted(self.blocks, key=lambda b: b.freq,          reverse=True)
        # blocks_by_perf_freq  = sorted(self.blocks, key=lambda b: b.total_period,  reverse=True)

        # b0_graal = blocks_by_graal_freq.pop(0)
        # b0_perf = blocks_by_perf_freq.pop(0)

        bmax_graal = sorted(self.blocks, key=lambda b: b.freq, reverse=True)
        bmax_perf = sorted(self.blocks, key=lambda b: b.period, reverse=True)

        if bmax_graal[0].id != bmax_perf[0].id:
            print(f'[WARRNING] In method {self.format_name(short_class_names=True)}\n\tmost frequent block measured with perf (id={bmax_perf[0].id:3}) differs from most frequent block from graal (id={bmax_graal[0].id:3})', file=fp)
            print(f'\tTop 5 blocks from graal {[(b.id, b.freq) for b in bmax_graal[:5]]}\n\tTop 5 blocks from perf {[(b.id, b.samples, b.period) for b in bmax_perf[:5]]}', file=fp)
            return

        bmax = bmax_graal[0]

        for b in [b for b in self.blocks if b.id != bmax.id]:
            graal_freq = b.freq / bmax.freq
            perf_freq = b.period / bmax.period

            if not compare_freq(graal_freq, perf_freq):
                print(f'[ERROR] In method {self.format_name(short_class_names=True)}\n\tblock id {b.id:5}, relative frequencies with respect to most frequent block diverge, graal freq {graal_freq:.2e}, perf freq {perf_freq:.2e}', file=fp)

        # else:
        #     print('Got no samples for method {}'.format(self.name))

def compare_freq(graal_freq, perf_freq, epsilon=3E-151):
    factor = 100 if graal_freq < 1 else 10 if graal_freq < 10 else 1.5
    return 1 / factor <= graal_freq / (perf_freq + epsilon) <= factor


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
        return '{} {:x} {} {} {} {}'.format(self.timestamp, self.pc, self.events, self.period, self.symbol, self.dso)

    def symbol_name(self):
        if self.symbol == '[unknown]':
            return self.symbol + ' in ' + self.dso
        return self.symbol


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
    def perf_convert_binary_command(files):
        return ['perf', 'script', '--fields', 'sym,time,event,dso,ip,sym,period', '-i',
                files.get_perf_binary_filename()]

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


class GeneratedAssembly:
    """
    All the assembly generated by the HotSpot JIT including any helpers and the interpreter

    :type code_info: list[CompiledCodeInfo]
    """

    def __init__(self, files, verbose=False):
        """

        :type files: ExperimentFiles
        """
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
                raise AssertionError('Wrong magic number: Found {} but expected {}'.format(tag, filetag))
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
                # build a map from the entry pc to the nmethod information
                nmethods = {}
                for nmethod in mx_logcompilation.find_nmethods(fp):
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
                mx.abort('Unable to find matching nmethod for code {}'.format(code))

        if files.has_block_info():
            reg = re.compile(
                r'HotSpot(?P<is_osr>(OSR)?)Compilation-(?P<id>[0-9]*)\[(?P<sig>.*)\]'
            )
            for compil in os.listdir(files.block_info):
                res = reg.match(compil)
                if not res:
                    continue
                compile_id, is_osr = res.group('id'), res.group('is_osr')
                code = self.code_by_id[compile_id + ('%' if is_osr else '')]
                with files.open_block_info(compile_id) as block_file:
                    blocks = []
                    for line in block_file:
                        [block_id, start, end, freq] = line.split(',')
                        blocks.append(Block(int(block_id), int(start), int(end), float(freq)))
                    code.set_blocks(blocks)

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
                    print('Parsed DynamicCode {}'.format(code_info))
            elif tag == CompiledMethodUnloadTag:
                timestamp = self.read_timestamp()
                code_addr = self.read_unsigned_jlong()
                nmethod = self.code_by_address[code_addr]
                if not nmethod:
                    message = "missing code for {}".format(code_addr)
                    mx.abort(message)
                nmethod.set_unload_time(timestamp)
                if verbose:
                    print('Parsed CompiledMethodUnload {}'.format(code_info))
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
                    print('Parsed CompiledMethod {}'.format(nmethod))
            else:
                raise AssertionError("Unexpected tag {}".format(tag))

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
            mx.warn('{} events of {} could not be mapped to generated code'.format(missing, attributed + missing))

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
                    return '{}+0x{:x}'.format(x.name, offset)
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
                    'find has no hits for pc {:x} and timestamp {} but search found: {}'.format(pc, timestamp, str(
                        [str(x) for x in m])))
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
            mx.abort('{} hasn\'t been built yet'.format(source_file))
        return source_file
    return None


@mx.command('mx', 'profrecord', '[options]')
@mx.suite_context_free
def profrecord(args):
    """Capture the profile of a Java program."""
    # capstone is not required for the capture step
    parser = ArgumentParser(description='Capture a profile of a Java program.', prog='mx profrecord')
    parser.add_argument('-s', '--script', help='Emit a script to run and capture annotated assembly',
                        action='store_true')
    parser.add_argument('-E', '--experiment',
                        help='The directory containing the data files from the experiment',
                        action='store', required=True)
    parser.add_argument('-O', '--overwrite', help='Overwrite an existing dump directory',
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

    full_cmd = build_capture_command(files, options.command, options=options)
    convert_cmd = PerfOutput.perf_convert_binary_command(files)
    if options.script:
        print(mx.list_to_cmd_line(full_cmd))
        print('{} > {}'.format(mx.list_to_cmd_line(convert_cmd), files.get_perf_output_filename()))
    else:
        mx.run(full_cmd, nonZeroIsFatal=False)
        if not files.has_perf_binary():
            mx.abort('No perf binary file found')

        # convert the perf binary data into text format
        with files.open_perf_output_file(mode='w') as fp:
            mx.run(convert_cmd, out=fp)

        if options.dump_hot:
            assembly = GeneratedAssembly(files)
            perf = PerfOutput(files)
            assembly.attribute_events(perf)
            top = assembly.top_methods(include=lambda x: not x.generated and x.total_period > 0)[:options.limit]
            dump_path = files.create_dump_dir()
            method_filter = ','.join([x.methods[0].method_filter_format() for x in top])
            dump_arguments = ['-Dgraal.Dump=:{}'.format(options.dump_level),
                              '-Dgraal.MethodFilter=' + method_filter,
                              '-Dgraal.DumpPath=' + dump_path]

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
            print('Created {}'.format(name))
        if options.delete:
            shutil.rmtree(experiment)


def build_capture_args(files, extra_vm_args=None, options=None):
    jvmti_asm_file = files.get_jvmti_asm_filename()
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
    vm_args = ['-agentpath:{}={}'.format(find_jvmti_asm_agent(), jvmti_asm_file), '-XX:+UnlockDiagnosticVMOptions',
               '-XX:+DebugNonSafepoints', '-Dgraal.TrackNodeSourcePosition=true', '-XX:+LogCompilation',
               '-XX:LogFile={}'.format(files.get_log_compilation_filename())]
    if extra_vm_args:
        vm_args += extra_vm_args
    return perf_cmd, vm_args


def build_capture_command(files, command_line, extra_vm_args=None, options=None):
    java_cmd = command_line[0]
    java_args = command_line[1:]
    perf_cmd, vm_args = build_capture_args(files, extra_vm_args, options)
    full_cmd = perf_cmd + [java_cmd] + vm_args + java_args
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
    check_capstone_import('profhot')
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
    perf_data = PerfOutput(files)
    assembly = GeneratedAssembly(files)
    assembly.attribute_events(perf_data)
    entries = perf_data.get_top_methods()
    non_jit_entries = [(s, d, c) for s, d, c in entries if d not in ('[JIT]', '[Generated]')]
    fp = sys.stdout
    if options.output:
        fp = open(options.output, 'w')
    print('Hot C functions:', file=fp)
    print('  Percent   Name', file=fp)
    for symbol, _, count in non_jit_entries[:options.limit]:
        print('   {:5.2f}%   {}'.format(100 * (float(count) / perf_data.total_period), symbol), file=fp)
    print('', file=fp)

    hot = assembly.top_methods(lambda x: x.total_period > 0)
    hot = hot[:options.limit]
    print('Hot generated code:', file=fp)
    print('  Percent   Name', file=fp)
    for code in hot:
        print('   {:5.2f}%   {}'.format(100 * (float(code.total_period) / perf_data.total_period),
                                        code.format_name(options.short_class_names)), file=fp)
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
    check_capstone_import('checkblocks')
    parser = ArgumentParser(description='Check that block frequencies computed by graal match frequecies measured using pref', prog='mx checkblocks')
    parser.add_argument('-n', '--limit', help='Check block frequencies for the top n functions;', action='store', default=10, type=int)
    parser.add_argument('-t', '--threshold',
                        help='Minimum percentage for a pc to be considered hot when building regions.\n'
                        'A threshold of 0 shows the all the generated code instead of just the hot regions.',
                        action='store', type=float, default=0.001)
    parser.add_argument('-o', '--output', help='Write output to named file.  Writes to stdout by default.',
                        action='store')
    parser.add_argument('-s', '--short-class-names', help='Drop package names from class names',
                        action='store_true')
    parser.add_argument('-E', '--experiment',
                       help='The directory containing the data files from the experiment',
                       action='store', required=True)
    parser.add_argument('-b', '--block-info',
                       help='The directory containing the block information data files from the experiment',
                       action='store', required=True)
    options = parser.parse_args(args)
    files = FlatExperimentFiles(directory=options.experiment, block_info=options.block_info)
    files.ensure_perf_output()
    perf_data = PerfOutput(files)
    assembly = GeneratedAssembly(files)
    assembly.attribute_events(perf_data)
    fp = sys.stdout
    if options.output:
        fp = open(options.output, 'w')

    hot = assembly.top_methods(lambda x: x.total_period > 0 and x.blocks and x.total_samples > len(x.blocks))
    hot = hot[:options.limit]

    for code in hot:
        print("for hot method {} with {} blocks, got {} samples".format(code.name, len(code.blocks or []), code.total_samples), file=fp)
        if code.blocks:
            code.check_blocks_0_rel_freq(fp=fp)
            code.check_blocks_rel_freq_most(fp=fp)

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
    assembly.print_all()


class ProftoolProfiler(mx_benchmark.JVMProfiler):
    """
    Use perf on linux and a JVMTI agent to capture Java profiles.
    """

    def __init__(self):
        super(ProftoolProfiler, self).__init__()
        self.filename = None

    def name(self):
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
        perf_cmd, vm_args = build_capture_args(files)

        # reset the next item name since it has just been consumed
        self.nextItemName = None
        return vm_args, perf_cmd

    def setup(self, benchmarks, bmSuiteArgs):
        super(ProftoolProfiler, self).setup(benchmarks, bmSuiteArgs)
        import datetime
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
        if self.nextItemName:
            self.filename = "proftool_{}_{}".format(self.nextItemName, timestamp)
        else:
            self.filename = "proftool_{}".format(timestamp)


if PerfOutput.is_supported():
    try:
        mx_benchmark.register_profiler(ProftoolProfiler())
    except AttributeError:
        mx.warn('proftool unable to register profiler')
