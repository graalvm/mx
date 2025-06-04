import argparse
import os
import subprocess
import time
import sys
import re
import logging as log
import signal
from pathlib import Path

DEFAULT_SAMPLE_DELAY = 0.5
DEFAULT_BASELINE_DURATION = 60


def parse_args():
    parser = argparse.ArgumentParser(description="Capture energy and power consumption using 'powerstat'")
    parser.add_argument("target_cmd", nargs=argparse.REMAINDER, help="Command to run and poll for energy data")
    parser.add_argument(
        "--baseline-output-file",
        type=str,
        help="If provided, the measured average baseline power will be saved to this file for reuse in subsequent stages",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=DEFAULT_SAMPLE_DELAY,
        help="Delay between each sample in seconds (default: {DEFAULT_SAMPLE_DELAY})",
    )
    parser.add_argument(
        "--baseline-duration",
        type=int,
        default=DEFAULT_BASELINE_DURATION,
        help="Duration of the baseline computation in seconds (default: {DEFAULT_BASELINE_DURATION})",
    )
    parser.add_argument(
        "--avg-baseline-power",
        type=float,
        help="Power consumption, in watts, to be used as the baseline of the system. If not provided, a 'powerstat' measurement will be executed with no additional processes running to determine the system baseline",
    )

    args = parser.parse_args()

    if args.delay < 0.5:
        log.error("Sample delay must be greater or equal to 0.5 seconds")
        sys.exit(1)

    if args.baseline_duration < 60:
        log.error("Please increase the baseline duration to at least 60 seconds")
        sys.exit(1)

    return args


def powerstat_cmd(delay, duration):
    """
    Constructs the powerstat command

    Args:
        delay (float): Delay between each sample
        duration (float): Duration of the powerstat process

    Returns:
        list: Powerstat command
    """
    return ["powerstat", "-R", str(delay), str(duration / delay)]


def check_powerstat_access():
    if os.geteuid() != 0:
        log.error("Powerstat must run with sudo privileges! Exiting...")
        return False

    try:
        cmd = ["powerstat", "-h"]
        powerstat_process = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=5, check=False
        )

        if powerstat_process.returncode != 0:
            log.error("powerstat is not accessible. Exiting...")
            log.error("Standard Error: %s", powerstat_process.stderr)
            log.error("Standard Output: %s", powerstat_process.stdout)
            return False
    except subprocess.TimeoutExpired:
        log.error("powerstat command timed out. Exiting...")
        return False

    return True


def parse_powerstat_output(powerstat_output, delay, avg_baseline_power=None):
    """
    Parses powerstat output and computes the average power and total energy consumption
    Args:
        powerstat_output (str): The captured output from powerstat
        delay (float): The time in seconds between each energy sample
        avg_baseline_power (float, optional): The average baseline power consumption in watts.
            This value is used to calculate the compute energy for each iteration of the benchmark run.
            If not provided, compute energy calculations will be skipped.

    Returns:
        average power in watts, total energy in joules, total compute energy
    """
    total_energy = 0.0
    total_power = 0.0
    power_readings_count = 0
    header_found = False
    watts_column_index = None
    watts_header = "Watts"
    metric_iteration = 0
    total_compute_energy = 0.0

    # example line of the expected powerstat output
    # 04:52:41   0.0   0.0   0.0  99.9   0.0    1   4415    701    0    0    0  41.41
    powerstat_pattern = re.compile(r"^\d{2}:\d{2}:\d{2}\s+([\d.]+(?:\s+[\d.]+)*)$")

    for line in powerstat_output.splitlines():
        line = line.strip()

        if not line:
            continue

        # the start of the data section
        if watts_header in line:
            header_found = True
            header_columns = line.split()
            # getting the index of watts_header
            try:
                watts_column_index = header_columns.index(watts_header)
            except ValueError:
                raise ValueError(
                    "Powerstat output format does not match expectations: missing %s column" % watts_header
                )
            continue  # skipping the header

        if not header_found:
            continue

        match = powerstat_pattern.search(line)
        if not match:
            continue

        columns = match.group(0).split()
        if not (watts_column_index < len(columns) and re.match(r"\d{2}:\d{2}:\d{2}", columns[0])):
            continue

        if watts_column_index >= len(columns):
            log.warning("Skipping this line due to unexpected column index for %s: %s", watts_header, line)

        try:
            power_watt = float(columns[watts_column_index])  # extracting from watts_header column
            # accumulating the total power and the count readings
            total_power += power_watt
            power_readings_count += 1
            # print the sample power and energy if the second argument (avg_baseline_power) is passed
            if avg_baseline_power is not None:
                # power and energy consumed by the benchmark run for each iteration
                compute_power_sample = power_watt - avg_baseline_power
                compute_energy_sample = compute_power_sample * delay
                log.info(
                    "Iteration %d: Sample compute power: %.2f Watts",
                    metric_iteration,
                    compute_power_sample,
                )
                log.info(
                    "Iteration %d: Sample compute energy: %.2f Joules",
                    metric_iteration,
                    compute_energy_sample,
                )
                metric_iteration += 1
                total_compute_energy += compute_energy_sample
            # converting watts to joules
            total_energy += power_watt * delay
        except ValueError as e:
            raise ValueError("Failed to extract energy from powerstat output") from e

    if power_readings_count == 0:
        log.error(powerstat_output)
        raise ValueError("No data could be parsed from powerstat output!")

    avg_power = total_power / power_readings_count

    return avg_power, total_energy, total_compute_energy


def compute_baseline_energy(delay, duration):
    """
    Measures the system's idle energy consumption

    Args:
        delay (float): Time in seconds between each energy sample
        duration (float): Duration of the baseline computation

    Returns:
        tuple: (total_baseline_energy, avg_baseline_power)
    """
    cmd = powerstat_cmd(delay, duration)
    log.info("Computing baseline energy consumption for %d seconds with command: %s", duration, " ".join(cmd))

    try:
        powerstat_result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            timeout=duration + 5,
            check=False,
        )

        if powerstat_result.returncode != 0:
            log.error("Powerstat process exited with an unexpected return code %d", powerstat_result.returncode)
            if powerstat_result.stderr:
                log.error("%s", powerstat_result.stderr)
            return None, None

        avg_baseline_power, total_baseline_energy, _ = parse_powerstat_output(powerstat_result.stdout, delay)

        log.info("Baseline Energy used: %.2f Joules", total_baseline_energy)
        log.info("Average Baseline Power: %.2f Watts", avg_baseline_power)

        return total_baseline_energy, avg_baseline_power

    except subprocess.TimeoutExpired:
        log.error("Powerstat process timed out")
        return None, None
    except OSError as e:
        log.error("Error starting 'powerstat' for baseline measurement: %s", e)
        return None, None


def compute_benchmark_energy(target_cmd, delay):
    """
    Measures the energy consumption while running the benchmark command

    Args:
        target_cmd (list): Command to benchmark
        delay (float): Time in seconds between each energy sample

    Returns:
        str: Powerstat output or None if an error occurred
    """
    cmd = powerstat_cmd(delay, 3600)
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    output_file = Path(f"powerstat_output_{timestamp}.txt")

    try:
        with output_file.open("w") as f:
            log.info("Computing benchmark energy consumption with command: %s", " ".join(cmd))
            log.info("Storing powerstat output in file: %s", output_file)
            powerstat_process = subprocess.Popen(
                cmd, stdout=f, stderr=subprocess.STDOUT, universal_newlines=True, start_new_session=True
            )
    except OSError as e:
        log.error("Error starting 'powerstat' for benchmark measurement: %s", e)
        return None

    benchmark_start_time = time.time()

    try:
        benchmark_process = subprocess.Popen(target_cmd, universal_newlines=True)
    except OSError as e:
        log.error("Error starting the benchmark: %s", e)
        powerstat_process.kill()
        return None

    benchmark_process.wait()
    benchmark_end_time = time.time()

    # termination of the powerstat process
    os.killpg(os.getpgid(powerstat_process.pid), signal.SIGTERM)
    graceful_wait = 3

    try:
        # waiting for graceful termination
        powerstat_process.wait(timeout=graceful_wait)
    except subprocess.TimeoutExpired:
        # sending SIGKILL if it's still running
        log.warning(
            "Powerstat process did not terminate gracefully after %d seconds, forcing termination...", graceful_wait
        )
        os.killpg(os.getpgid(powerstat_process.pid), signal.SIGKILL)
        try:
            powerstat_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            raise RuntimeError("Failed to terminate powerstat process after SIGKILL")

    if powerstat_process.returncode not in [0, -15, -9]:  # -15 is SIGTERM, -9 is SIGKILL
        log.error("Powerstat output:\n%s", output_file.read_text())
        raise RuntimeError(f"Powerstat process exited with an unexpected return code: {powerstat_process.returncode}")

    benchmark_duration = benchmark_end_time - benchmark_start_time
    log.info("The benchmark ran for %.2f seconds", benchmark_duration)

    return output_file.read_text()


def main():
    log.basicConfig(
        level=log.INFO,
        format="[%(asctime)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[log.StreamHandler()],
    )
    args = parse_args()
    if not check_powerstat_access():
        return 1

    if args.baseline_output_file:
        log.info("Performing a fresh baseline power measurement")
        total_baseline_energy, avg_baseline_power = compute_baseline_energy(args.delay, args.baseline_duration)
        if total_baseline_energy is None or avg_baseline_power is None:
            log.error("Could not compute baseline energy. Exiting...")
            return 1
        try:
            baseline_output_file = Path(args.baseline_output_file)
            baseline_output_file.write_text(f"{avg_baseline_power:.2f}")
            log.info("Stored new baseline power: %.2f W", avg_baseline_power)
        except (OSError, IOError) as e:
            log.error("Failed to write baseline file: %s. Exiting...", e)
            return 1
    elif args.avg_baseline_power:
        avg_baseline_power = args.avg_baseline_power
        log.info("Using cached baseline power: %.2f W", avg_baseline_power)
    else:
        log.error("No baseline source provided. Exiting...")
        return 1

    powerstat_output = compute_benchmark_energy(args.target_cmd, args.delay)
    if powerstat_output is None:
        log.error("Failed to capture powerstat output. Exiting...")
        return 1

    avg_machine_power, total_machine_energy, total_compute_energy = parse_powerstat_output(
        powerstat_output, args.delay, avg_baseline_power
    )

    avg_compute_power = avg_machine_power - avg_baseline_power

    log.info("Benchmark results:")
    log.info("Total system energy consumption (including idle): %.2f Joules", total_machine_energy)
    log.info("Average system power (including idle): %.2f Watts", avg_machine_power)
    log.info("Total energy used by the benchmark (excluding idle): %.2f Joules", total_compute_energy)
    log.info("Average power used by benchmark: %.2f Watts", avg_compute_power)

    return 0


if __name__ == "__main__":
    sys.exit(main())
