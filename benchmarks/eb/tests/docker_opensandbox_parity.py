#!/usr/bin/env python3
"""
Docker vs OpenSandbox Parity Test.
Runs the same deterministic workflow on both backends and compares results.
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "eb"))

from eb.sandbox.docker import DockerSandbox
from eb.sandbox.opensandbox import OpenSandboxBackend
from eb.sandbox.security import SecurityPolicy


async def run_workflow_docker():
    """Run workflow with Docker backend."""
    sb = DockerSandbox()
    policy = SecurityPolicy(network_enabled=False)
    
    sid = await sb.create("python:3.11-slim", policy)
    await sb.start(sid)
    
    # Execute Python
    r1 = await sb.exec(sid, ["python3", "-c", "print(42)"])
    
    # Write file
    await sb.exec(sid, ["sh", "-c", "echo 'parity-test' > /tmp/parity.txt"])
    
    # Read file
    r2 = await sb.exec(sid, ["cat", "/tmp/parity.txt"])
    
    # Non-zero exit
    r3 = await sb.exec(sid, ["sh", "-c", "exit 7"])
    
    await sb.destroy(sid)
    
    return {
        "backend": "docker",
        "python_output": r1.stdout.strip(),
        "python_exit": r1.exit_code,
        "file_content": r2.stdout.strip(),
        "error_exit": r3.exit_code,
    }


async def run_workflow_opensandbox():
    """Run workflow with OpenSandbox backend."""
    sb = OpenSandboxBackend()
    policy = SecurityPolicy(network_enabled=False)
    
    sid = await sb.create("python:3.11-slim", policy)
    await sb.start(sid)
    
    # Execute Python
    r1 = await sb.exec(sid, ["python3", "-c", "print(42)"])
    
    # Write file
    await sb.exec(sid, ["sh", "-c", "echo 'parity-test' > /tmp/parity.txt"])
    
    # Read file
    r2 = await sb.exec(sid, ["cat", "/tmp/parity.txt"])
    
    # Non-zero exit
    r3 = await sb.exec(sid, ["sh", "-c", "exit 7"])
    
    await sb.destroy(sid)
    
    return {
        "backend": "opensandbox",
        "python_output": r1.stdout.strip(),
        "python_exit": r1.exit_code,
        "file_content": r2.stdout.strip(),
        "error_exit": r3.exit_code,
    }


async def main():
    print("=" * 60)
    print("Docker vs OpenSandbox Parity Test")
    print("=" * 60)
    
    print("\n--- Running Docker workflow ---")
    docker_result = await run_workflow_docker()
    print(f"Docker: python={docker_result['python_output']} (exit={docker_result['python_exit']})")
    print(f"Docker: file='{docker_result['file_content']}'")
    print(f"Docker: error_exit={docker_result['error_exit']}")
    
    print("\n--- Running OpenSandbox workflow ---")
    os_result = await run_workflow_opensandbox()
    print(f"OS: python={os_result['python_output']} (exit={os_result['python_exit']})")
    print(f"OS: file='{os_result['file_content']}'")
    print(f"OS: error_exit={os_result['error_exit']}")
    
    print("\n--- Parity Check ---")
    checks = [
        ("python exit code", docker_result["python_exit"], os_result["python_exit"]),
        ("python output", docker_result["python_output"], os_result["python_output"]),
        ("file content", docker_result["file_content"], os_result["file_content"]),
        ("error exit code", docker_result["error_exit"], os_result["error_exit"]),
    ]
    
    all_pass = True
    for name, d, o in checks:
        match = "✓" if d == o else "✗"
        if d != o:
            all_pass = False
        print(f"  {match} {name}: docker={d!r}, opensandbox={o!r}")
    
    print("\n" + "=" * 60)
    if all_pass:
        print("RESULT: PASS — Behavioral parity confirmed")
    else:
        print("RESULT: FAIL — Parity mismatch detected")
    print("=" * 60)
    
    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    asyncio.run(main())
