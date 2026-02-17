import argparse
import re
import subprocess
import sys
import time
import logging as log
from pathlib import Path
from typing import Dict, List, Tuple, TypedDict, Optional

ANONYMOUS_MEMORY = "//anon"
CODE_SECTION_NAME = ".text"
IMAGE_HEAP_SECTION_NAME = ".svm_heap"

PAGEFAULT_TYPES = {"majfault": "major", "minfault": "minor"}


class Section(TypedDict):
    start: int
    end: int


Sections = Dict[str, Section]
NativeImagePageFaults = Dict[str, int]


class PagefaultResults(TypedDict):
    total: int
    anonymous_memory: int
    native_image: NativeImagePageFaults


class PagefaultResultsByType(TypedDict):
    major: PagefaultResults
    minor: PagefaultResults


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Counts page-faults using 'perf'")
    parser.add_argument("target_cmd", nargs=argparse.REMAINDER, help="Command to run and for tracing page faults")
    parser.add_argument(
        "--output-dir", type=str, help="Output directory where to dump intermediate files", required=True
    )
    parser.add_argument(
        "--native-image-app-executable",
        type=str,
        help=(
            "Full path to the native-image application executable to report page faults for."
            " If specified, the script will report the number of page faults attributed to this executable."
            " If omitted, only the total number of page faults for the entire command will be reported."
        ),
        default=None,
    )

    args = parser.parse_args()

    errors = []
    output_path = Path(args.output_dir)
    if not output_path.exists():
        errors.append(f"Output directory '{output_path}' does not exist.")
    elif not output_path.is_dir():
        errors.append(f"Output directory '{output_path}' is not a directory.")

    if args.native_image_app_executable:
        native_image_path = Path(args.native_image_app_executable)
        if not native_image_path.exists():
            errors.append(f"Native-image app executable '{native_image_path}' does not exist.")
        elif not native_image_path.is_file():
            errors.append(f"Native-image app executable '{native_image_path}' is not a file.")
        else:
            native_image_sections = extract_executable_sections(str(native_image_path))
            if not is_native_image(native_image_sections):
                errors.append(f"'{native_image_path}' is not a native-image executable file.")

    if errors:
        log.error("\n".join(errors))
        sys.exit(1)
    return args


def perf_cmd(target_cmd: List[str], output_file_path: Path) -> List[str]:
    """
    Constructs the perf command for tracing page faults.

    Args:
        target_cmd: Command to benchmark.
        output_file_path: Where to store perf output.

    Returns:
        List of command-line arguments for perf.
    """
    return ["perf", "trace", "-F", "all", "-o", str(output_file_path), "--"] + target_cmd


def check_command_access(command: str) -> bool:
    """
    Checks if the given system command is accessible.

    Args:
        command: Command to check.

    Returns:
        True if accessible, False otherwise.
    """
    try:
        result = subprocess.run(
            [command, "-v"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=5,
            check=True,
        )
        if result.returncode != 0:
            log.error("%s is not accessible. Exiting...", command)
            log.error("Standard Error: %s", result.stderr)
            log.error("Standard Output: %s", result.stdout)
            return False
    except Exception as e:  # pylint: disable=broad-except
        log.error("%s command failed. Exiting... (%s)", command, e)
        return False
    return True


def parse_perf_output(perf_output: str, native_image_app_executable: Optional[str]) -> PagefaultResultsByType:
    """
    Parse perf output and compute page faults.

    Args:
        perf_output: The captured output from perf.
        native_image_app_executable: The native-image app executable to match, if any.

    Returns:
        PagefaultResultsByType containing pagefault breakdown.
    """
    # Regex pattern for relevant perf lines.
    pagefault_pattern = re.compile(
        r"^\s*([0-9]+\.[0-9]+)\s*\(\s*([0-9]+\.[0-9]+)\s*ms\s*\):.*\/[0-9]+\s+(\S+)\s+\[(.*?)\+?0x([0-9a-fA-F]+)\]\s*=>\s*(\S*)@?0x([0-9a-fA-F]+)\s+\(.*\)"
    )

    results_by_type: PagefaultResultsByType = {
        "major": {
            "total": 0,
            "anonymous_memory": 0,
            "native_image": {"total": 0, CODE_SECTION_NAME: 0, IMAGE_HEAP_SECTION_NAME: 0},
        },
        "minor": {
            "total": 0,
            "anonymous_memory": 0,
            "native_image": {"total": 0, CODE_SECTION_NAME: 0, IMAGE_HEAP_SECTION_NAME: 0},
        },
    }

    if native_image_app_executable:
        native_image_sections = extract_executable_sections(native_image_app_executable)
    else:
        native_image_sections = {}

    for line in perf_output.splitlines():
        line = line.strip()
        if not line:
            continue
        match = pagefault_pattern.search(line)
        if not match:
            continue

        # Example capture: [time1, time2, pf_type, ?, ?, fault_to, fault_to_offset]
        _, _, pf_type, _, _, fault_to, fault_to_offset = match.groups()
        if pf_type not in PAGEFAULT_TYPES:
            continue
        pagefault_type_name = PAGEFAULT_TYPES[pf_type]
        fault_to = fault_to.replace("@", "")
        fault_to_offset = int(fault_to_offset, 16)
        pf_result = results_by_type[pagefault_type_name]

        pf_result["total"] += 1
        if fault_to == ANONYMOUS_MEMORY:
            pf_result["anonymous_memory"] += 1
        elif native_image_app_executable and fault_to == native_image_app_executable:
            pf_result["native_image"]["total"] += 1
            if is_in_executable_section(native_image_sections, CODE_SECTION_NAME, fault_to_offset):
                pf_result["native_image"][CODE_SECTION_NAME] += 1
            elif is_in_executable_section(native_image_sections, IMAGE_HEAP_SECTION_NAME, fault_to_offset):
                pf_result["native_image"][IMAGE_HEAP_SECTION_NAME] += 1

    if all(v["total"] == 0 for v in results_by_type.values()):
        log.error(perf_output)
        raise ValueError("No data could be parsed from perf output!")
    return results_by_type


def extract_executable_sections(file: str) -> Sections:
    """
    Uses `readelf` to inspect binary and extract section info.

    Args:
        file: Path to native binary.

    Returns:
        Dict of section name -> dict with start and end addresses.
    """
    readelf_process = subprocess.Popen(
        ["readelf", "-SW", file], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True
    )
    readelf_out, _ = readelf_process.communicate()

    # [ 1] section_name PROGBITS  address  offset  size
    section_re = re.compile(r"\s*\[\s*\d+\]\s+([^\s]+)\s+[A-Z_]+\s+([0-9a-fA-F]+)\s+[0-9a-fA-F]+\s+([0-9a-fA-F]+)")
    sections: Sections = {}
    for line in readelf_out.splitlines():
        m = section_re.search(line)
        if not m:
            continue
        name, start, size = m.groups()
        start = int(start, 16)
        size = int(size, 16)
        end = start + size
        sections[name] = {"start": start, "end": end}
    return sections


def is_native_image(sections: Sections) -> bool:
    """
    Determines if provided sections belong to a native-image binary.

    Args:
        sections: Section info for a binary.

    Returns:
        True if native-image, False otherwise.
    """
    return CODE_SECTION_NAME in sections and IMAGE_HEAP_SECTION_NAME in sections


def is_in_executable_section(sections: Sections, section_name: str, offset: int) -> bool:
    """
    Determines if address/offset is within a given section.

    Args:
        sections: Section info.
        section_name: Section name.
        offset: Address to check.

    Returns:
        True if offset is in section, False otherwise.
    """
    section = sections.get(section_name)
    if section is None:
        return False
    return section["start"] <= offset < section["end"]


def trace_benchmark_pagefaults(output_dir: str, target_cmd: List[str]) -> Tuple[Optional[str], int]:
    """
    Traces page faults while running the target benchmark command.

    Args:
        output_dir: Output directory.
        target_cmd: Command to benchmark.

    Returns:
        Tuple of (perf_output, process_returncode)
    """
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    output_file = Path(output_dir) / f"perf_output_{timestamp}.txt"
    cmd = perf_cmd(target_cmd, output_file)

    try:
        log.info("Tracing benchmark page faults with command: %s", " ".join(cmd))
        log.info("Storing perf output in file: %s", output_file)
        perf_process = subprocess.Popen(cmd)
        perf_process.wait()
        if perf_process.returncode not in [0, -15, -9]:
            log.error("Per output:\n%s", output_file.read_text())
            raise RuntimeError(f"Perf process exited with unexpected return code: {perf_process.returncode}")
        return output_file.read_text(), perf_process.returncode
    except OSError as e:
        log.error("Error starting 'perf' for benchmark command: %s", e)
        return None, 1


def main() -> int:
    log.basicConfig(
        level=log.INFO,
        datefmt="%Y-%m-%d %H:%M:%S",
        format="[%(asctime)s] %(message)s",
        handlers=[log.StreamHandler()],
    )
    args = parse_args()
    if not check_command_access("perf") or not check_command_access("readelf"):
        return 1

    perf_output, returncode = trace_benchmark_pagefaults(args.output_dir, args.target_cmd)
    if perf_output is None:
        log.error("Failed to capture perf output. Exiting...")
        return 1

    pagefaults_results_by_type = parse_perf_output(perf_output, args.native_image_app_executable)

    log.info("Benchmark results:")
    for type_name, pagefaults_results in pagefaults_results_by_type.items():
        cap_type = type_name.capitalize()
        total_pf = pagefaults_results["total"]
        anon_pf = pagefaults_results["anonymous_memory"]
        ni_pf = pagefaults_results["native_image"]

        log.info("")
        log.info("Total %s page faults caused by benchmark: %d", cap_type, total_pf)
        log.info("%s page faults caused by anonymous memory: %d", cap_type, anon_pf)
        if args.native_image_app_executable:
            log.info("%s page faults caused by the native-image: %d", cap_type, ni_pf["total"])
            log.info("%s page faults caused by the native-image code section: %d", cap_type, ni_pf[CODE_SECTION_NAME])
            log.info(
                "%s page faults caused by the native-image image-heap section: %d",
                cap_type,
                ni_pf[IMAGE_HEAP_SECTION_NAME],
            )
    return returncode


if __name__ == "__main__":
    sys.exit(main())
