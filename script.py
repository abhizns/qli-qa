import subprocess
import json
import re
import datetime
import os
import argparse

DEFAULT_TEST_DEFINITIONS_FILE = "test_cases.json"
DEFAULT_REPORT_DIR = "test_reports"

def load_test_cases_from_json(file_path):
    """Loads test case definitions from a JSON file."""
    try:
        with open(file_path, 'r') as f:
            data = json.load(f)
            if "test_cases" not in data or not isinstance(data["test_cases"], list):
                print(f"ERROR: JSON file '{file_path}' must contain a top-level list key 'test_cases'.")
                exit(1)
            return data["test_cases"]
    except FileNotFoundError:
        print(f"ERROR: Test definitions JSON file not found: {file_path}")
        exit(1)
    except json.JSONDecodeError as e:
        print(f"ERROR: Could not parse JSON file '{file_path}': {e}")
        exit(1)
    except Exception as e:
        print(f"ERROR: An unexpected error occurred while loading '{file_path}': {e}")
        exit(1)


def execute_command(command_str, timeout=60):
    """Executes a shell command and returns its output."""
    try:
        process = subprocess.run(
            command_str,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        return {
            "stdout": process.stdout.strip(),
            "stderr": process.stderr.strip(),
            "returncode": process.returncode,
            "error": None
        }
    except subprocess.TimeoutExpired:
        return {
            "stdout": "",
            "stderr": f"Command timed out after {timeout} seconds.",
            "returncode": -1, # Custom code for timeout
            "error": "TimeoutExpired"
        }
    except Exception as e:
        return {
            "stdout": "",
            "stderr": str(e),
            "returncode": -2, # Custom code for other execution errors
            "error": str(e)
        }

def validate_output(actual, expected, mode):
    """Validates actual output against expected based on mode."""
    if mode == "ignore" or expected is None:
        return True, "Ignored"
    if actual is None:
        return False, "Actual output was None"

    if mode == "exact":
        is_match = actual == expected
        details = f"Exact match: {is_match}"
    elif mode == "contains":
        is_match = expected in actual
        details = f"Contains '{expected}': {is_match}"
    elif mode == "regex":
        try:
            is_match = bool(re.search(str(expected), str(actual)))
            details = f"Regex '{expected}' match: {is_match}"
        except re.error as e:
            return False, f"Invalid regex '{expected}': {e}"
    else:
        return False, f"Unknown validation mode: {mode}"
    return is_match, details


def run_tests(test_cases):
    """Runs all defined test cases and collects results."""
    results = []
    passed_count = 0
    failed_count = 0

    print("Starting test execution...\n")

    for i, test_case in enumerate(test_cases):
        print(f"Running test {i+1}/{len(test_cases)}: {test_case.get('name', 'Unnamed Test')}...")
        command = test_case.get('command')
        if not command:
            print("  ERROR: Test case missing 'command'. Skipping.")
            results.append({
                "name": test_case.get('name', 'Unnamed Test'),
                "command": "N/A",
                "status": "ERROR",
                "status_reason": "Test case definition missing 'command'."
            })
            failed_count +=1 # Count as failure
            continue

        print(f"  Command: {command}")

        command_output = execute_command(
            command,
            timeout=test_case.get("timeout", 60)
        )

        test_result = {
            "name": test_case.get('name', 'Unnamed Test'),
            "command": command,
            "actual_stdout": command_output["stdout"],
            "actual_stderr": command_output["stderr"],
            "actual_returncode": command_output["returncode"],
            "expected_stdout": test_case.get("expected_stdout"),
            "expected_stderr": test_case.get("expected_stderr"),
            "expected_returncode": test_case.get("expected_returncode", 0),
            "stdout_mode": test_case.get("stdout_mode", "exact"),
            "stderr_mode": test_case.get("stderr_mode", "exact"),
            "status": "FAIL", # Default to FAIL
            "stdout_validation_details": "",
            "stderr_validation_details": "",
            "returncode_validation_details": ""
        }

        if command_output["error"]:
            test_result["status_reason"] = f"Command execution error: {command_output['error']}"
            failed_count +=1
            results.append(test_result)
            print(f"  Status: FAIL ({test_result['status_reason']})\n")
            continue

        all_checks_passed = True

        # 1. Return Code
        expected_rc = test_result["expected_returncode"]
        actual_rc = test_result["actual_returncode"]
        if actual_rc == expected_rc:
            test_result["returncode_validation_details"] = f"Return code matched: {actual_rc}"
        else:
            all_checks_passed = False
            test_result["returncode_validation_details"] = f"Return code MISMATCH. Expected: {expected_rc}, Got: {actual_rc}"

        # 2. Stdout
        if test_case.get("expected_stdout") is not None or test_case.get("stdout_mode", "exact") != "ignore":
            stdout_passed, details = validate_output(
                command_output["stdout"],
                test_case.get("expected_stdout"),
                test_case.get("stdout_mode", "exact")
            )
            test_result["stdout_validation_details"] = details
            if not stdout_passed:
                all_checks_passed = False
        else:
             test_result["stdout_validation_details"] = "Stdout validation not configured or ignored."


        # 3. Stderr
        if test_case.get("expected_stderr") is not None or test_case.get("stderr_mode", "exact") != "ignore":
            stderr_passed, details = validate_output(
                command_output["stderr"],
                test_case.get("expected_stderr"),
                test_case.get("stderr_mode", "exact")
            )
            test_result["stderr_validation_details"] = details
            if not stderr_passed:
                all_checks_passed = False
        else:
            test_result["stderr_validation_details"] = "Stderr validation not configured or ignored."


        if all_checks_passed:
            test_result["status"] = "PASS"
            passed_count += 1
            print("  Status: PASS\n")
        else:
            failed_count += 1
            print("  Status: FAIL")
            if test_result["returncode_validation_details"] and "MISMATCH" in test_result["returncode_validation_details"]:
                 print(f"    - {test_result['returncode_validation_details']}")

            stdout_check_configured = test_case.get("expected_stdout") is not None or test_case.get("stdout_mode", "exact") != "ignore"
            if stdout_check_configured and not validate_output(command_output["stdout"], test_case.get("expected_stdout"), test_case.get("stdout_mode", "exact"))[0]:
                 print(f"    - Stdout MISMATCH: {test_result['stdout_validation_details']}")
                 print(f"      Expected ({test_case.get('stdout_mode', 'exact')}): '{test_case.get('expected_stdout')}'")
                 print(f"      Actual:   '{command_output['stdout']}'")

            stderr_check_configured = test_case.get("expected_stderr") is not None or test_case.get("stderr_mode", "exact") != "ignore"
            if stderr_check_configured and not validate_output(command_output["stderr"], test_case.get("expected_stderr"), test_case.get("stderr_mode", "exact"))[0]:
                 print(f"    - Stderr MISMATCH: {test_result['stderr_validation_details']}")
                 print(f"      Expected ({test_case.get('stderr_mode', 'exact')}): '{test_case.get('expected_stderr')}'")
                 print(f"      Actual:   '{command_output['stderr']}'")
            print("")

        results.append(test_result)

    return results, passed_count, failed_count

def generate_html_report(results, passed_count, failed_count, report_dir):
    """Generates an HTML report from the test results."""
    if not os.path.exists(report_dir):
        os.makedirs(report_dir)

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = os.path.join(report_dir, f"test_report_{timestamp}.html")

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Test Execution Report - {timestamp}</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 20px; }}
            h1 {{ color: #333; }}
            h2 {{ color: #555; }}
            table {{ width: 100%; border-collapse: collapse; margin-bottom: 20px; }}
            th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; vertical-align: top; }}
            th {{ background-color: #f2f2f2; }}
            .pass {{ background-color: #d4edda; color: #155724; }}
            .fail {{ background-color: #f8d7da; color: #721c24; }}
            .error {{ background-color: #fff3cd; color: #856404; }} /* For test definition errors */
            .details-box {{ background-color: #f0f0f0; border: 1px solid #ccc; padding: 10px; margin-top: 5px; font-family: monospace; white-space: pre-wrap; word-wrap: break-word; }}
            .summary {{ margin-bottom: 20px; padding: 10px; border: 1px solid #ccc; background-color: #e9ecef; }}
            .summary p {{ margin: 5px 0; }}
        </style>
    </head>
    <body>
        <h1>Test Execution Report</h1>
        <div class="summary">
            <h2>Summary</h2>
            <p><strong>Total Tests:</strong> {len(results)}</p>
            <p><strong>Passed:</strong> <span style="color: green;">{passed_count}</span></p>
            <p><strong>Failed:</strong> <span style="color: red;">{failed_count}</span></p>
            <p><strong>Report Generated:</strong> {timestamp}</p>
        </div>

        <h2>Test Case Details</h2>
        <table>
            <thead>
                <tr>
                    <th>#</th>
                    <th>Test Name</th>
                    <th>Status</th>
                    <th>Command</th>
                    <th>Details</th>
                </tr>
            </thead>
            <tbody>
    """

    for i, result in enumerate(results):
        status_class = "pass" if result["status"] == "PASS" else ("error" if result["status"] == "ERROR" else "fail")
        html_content += f"""
                <tr class="{status_class}">
                    <td>{i+1}</td>
                    <td>{result['name']}</td>
                    <td><strong>{result['status']}</strong></td>
                    <td><div class="details-box">{result.get('command', 'N/A')}</div></td>
                    <td>
        """
        if result.get("status_reason"):
             html_content += f"<p><strong>Reason:</strong> {result['status_reason']}</p>"

        if result["status"] != "ERROR": # Don't show validation details if test definition was bad
            html_content += f"<p><strong>Return Code:</strong> {result.get('returncode_validation_details', 'N/A')}</p>"
            html_content += f"<p><strong>Stdout Validation:</strong> {result.get('stdout_validation_details', 'N/A')}</p>"
            if result.get("expected_stdout") is not None and result.get("stdout_mode") != "ignore":
                html_content += f"""
                            <div class="details-box">
                                <strong>Expected STDOUT ({result.get('stdout_mode','N/A')}):</strong>
                                {result.get('expected_stdout', 'N/A')}
                                <hr>
                                <strong>Actual STDOUT:</strong>
                                {result.get('actual_stdout', 'N/A')}
                            </div>"""

            html_content += f"<p><strong>Stderr Validation:</strong> {result.get('stderr_validation_details', 'N/A')}</p>"
            if result.get("expected_stderr") is not None and result.get("stderr_mode") != "ignore":
                html_content += f"""
                            <div class="details-box">
                                <strong>Expected STDERR ({result.get('stderr_mode','N/A')}):</strong>
                                {result.get('expected_stderr', 'N/A')}
                                <hr>
                                <strong>Actual STDERR:</strong>
                                {result.get('actual_stderr', 'N/A')}
                            </div>"""
        html_content += "</td></tr>"

    html_content += """
            </tbody>
        </table>
    </body>
    </html>
    """

    with open(filename, "w") as f:
        f.write(html_content)
    print(f"\nHTML report generated: {os.path.abspath(filename)}")
    return os.path.abspath(filename)

def main():
    parser = argparse.ArgumentParser(description="Run commands on EC2 and validate output.")
    parser.add_argument(
        "--tests-file",
        default=DEFAULT_TEST_DEFINITIONS_FILE,
        help=f"Path to the JSON file containing test definitions (default: {DEFAULT_TEST_DEFINITIONS_FILE})"
    )
    parser.add_argument(
        "--report-dir",
        default=DEFAULT_REPORT_DIR,
        help=f"Directory to save HTML test reports (default: {DEFAULT_REPORT_DIR})"
    )
    args = parser.parse_args()

    print(f"Loading test cases from: {args.tests_file}")
    test_cases = load_test_cases_from_json(args.tests_file)


    if not test_cases: # load_test_cases_from_yaml will exit on error
        print("No test cases loaded. Exiting.")
        exit(1)

    results, passed, failed = run_tests(test_cases)
    report_file = generate_html_report(results, passed, failed, args.report_dir)

    print("\n--- Test Execution Summary ---")
    print(f"Total tests run: {len(results)}")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    print(f"Report available at: {report_file}")

    # Exit with a non-zero code if any tests failed
    if failed > 0:
        exit(1)

if __name__ == "__main__":
    main()
