import json
import select
import subprocess
import tempfile


def run_workflow(command, fixture, call, *, cwd, env):
    with tempfile.TemporaryFile(mode="w+") as errors, subprocess.Popen(
        command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errors,
        cwd=cwd, env=env, text=True, bufsize=1,
    ) as child:
        try:
            child.stdin.write(json.dumps(fixture) + "\n")
            child.stdin.flush()
            while True:
                if not select.select([child.stdout], [], [], 30)[0]:
                    raise TimeoutError("Workflow fixture stopped responding")
                line = child.stdout.readline()
                if not line:
                    errors.seek(0)
                    raise AssertionError(errors.read() or "Workflow exited without a result")
                message = json.loads(line)
                if "result" in message:
                    child.stdin.close()
                    assert child.wait(timeout=5) == 0
                    return message["result"]
                result = call(message["call"])
                child.stdin.write(json.dumps({
                    "returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr,
                }) + "\n")
                child.stdin.flush()
        finally:
            if child.poll() is None:
                child.kill()
            child.wait()
