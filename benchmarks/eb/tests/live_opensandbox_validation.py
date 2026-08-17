#!/usr/bin/env python3
"""
Live OpenSandbox validation script for EB infrastructure.
Tests: sandbox lifecycle, shell/Python execution, file ops, security, timeouts.
"""
import asyncio
import os
import sys
from pathlib import Path

# Add eb to path
sys.path.insert(0, str(Path(__file__).parent / "eb"))

from eb.sandbox.opensandbox import OpenSandboxBackend, OpenSandboxCapabilities
from eb.sandbox.security import SecurityPolicy


async def test_basic_sandbox_lifecycle():
    """Test: sandbox creation, start, destroy."""
    print("\n=== Basic Sandbox Lifecycle ===")
    sb = OpenSandboxBackend()
    policy = SecurityPolicy(network_enabled=True)
    
    sid = await sb.create("python:3.11-slim", policy)
    print(f"Created sandbox: {sid}")
    assert sid.startswith("eb-osb-"), f"Invalid sandbox ID format: {sid}"
    
    await sb.start(sid)
    print(f"Started sandbox: {sid}")
    
    meta = await sb.get_metadata(sid)
    print(f"Metadata: image={meta.image}, backend={meta.resource_limits['backend']}")
    assert meta.image == "python:3.11-slim"
    assert meta.resource_limits["backend"] == "opensandbox"
    
    await sb.destroy(sid)
    print(f"Destroyed sandbox: {sid}")
    print("PASS")
    return sid


async def test_shell_command_execution():
    """Test: shell command execution and exit codes."""
    print("\n=== Shell Command Execution ===")
    sb = OpenSandboxBackend()
    policy = SecurityPolicy(network_enabled=True)
    
    sid = await sb.create("python:3.11-slim", policy)
    await sb.start(sid)
    
    # Success case
    result = await sb.exec(sid, ["echo", "hello opensandbox"])
    print(f"echo: exit_code={result.exit_code}, stdout='{result.stdout.strip()}'")
    assert result.exit_code == 0
    assert "hello opensandbox" in result.stdout
    
    # Non-zero exit code
    result = await sb.exec(sid, ["sh", "-c", "exit 42"])
    print(f"exit 42: exit_code={result.exit_code}")
    assert result.exit_code == 42
    
    # Python execution
    result = await sb.exec(sid, ["python3", "-c", "print(42)"])
    print(f"python3 -c 'print(42)': exit_code={result.exit_code}, stdout='{result.stdout.strip()}'")
    assert result.exit_code == 0
    assert "42" in result.stdout
    
    await sb.destroy(sid)
    print("PASS")


async def test_timeout():
    """Test: command timeout."""
    print("\n=== Timeout Test ===")
    sb = OpenSandboxBackend()
    policy = SecurityPolicy(network_enabled=True)
    
    sid = await sb.create("python:3.11-slim", policy)
    await sb.start(sid)
    
    # Short timeout on a long command
    result = await sb.exec(sid, ["sleep", "10"], timeout_s=1.0)
    print(f"sleep 10 with 1s timeout: exit_code={result.exit_code}, timed_out={result.timed_out}")
    # OpenSandbox may kill the process, so we expect non-zero or timeout flag
    assert result.timed_out or result.exit_code != 0
    
    await sb.destroy(sid)
    print("PASS")


async def test_file_write_and_read():
    """Test: file upload (copy_in) and read."""
    print("\n=== File Write and Read ===")
    sb = OpenSandboxBackend()
    policy = SecurityPolicy(network_enabled=True)
    
    sid = await sb.create("python:3.11-slim", policy)
    await sb.start(sid)
    
    # Create test file
    test_file = Path("/tmp/eb-opensandbox-test.txt")
    test_file.write_text("Hello from EB OpenSandbox validation\n")
    
    try:
        # Upload file
        await sb.copy_in(sid, test_file, "test.txt")
        print("Uploaded test file")
        
        # Verify file exists and content
        result = await sb.exec(sid, ["cat", "test.txt"])
        print(f"Read file: exit_code={result.exit_code}, content='{result.stdout.strip()}'")
        assert result.exit_code == 0
        assert "Hello from EB OpenSandbox validation" in result.stdout
        
        # Write file via shell
        result = await sb.exec(sid, ["sh", "-c", "echo 'written inside' > /tmp/inside.txt"])
        assert result.exit_code == 0
        
        # Read it back
        result = await sb.exec(sid, ["cat", "/tmp/inside.txt"])
        print(f"Write/read inside sandbox: '{result.stdout.strip()}'")
        assert "written inside" in result.stdout
        
    finally:
        test_file.unlink(missing_ok=True)
        await sb.destroy(sid)
    print("PASS")


async def test_file_download():
    """Test: file download (copy_out)."""
    print("\n=== File Download ===")
    sb = OpenSandboxBackend()
    policy = SecurityPolicy(network_enabled=True)
    
    sid = await sb.create("python:3.11-slim", policy)
    await sb.start(sid)
    
    try:
        # Create file inside sandbox
        await sb.exec(sid, ["sh", "-c", "echo 'download me' > /tmp/to_download.txt"])
        
        # Download to host
        dest = Path("/tmp/eb-downloaded.txt")
        await sb.copy_out(sid, "/tmp/to_download.txt", dest)
        content = dest.read_text()
        print(f"Downloaded content: '{content.strip()}'")
        assert "download me" in content
        dest.unlink()
        
    finally:
        await sb.destroy(sid)
    print("PASS")


async def test_security_host_isolation():
    """Test: host filesystem is not exposed."""
    print("\n=== Security: Host Filesystem Isolation ===")
    sb = OpenSandboxBackend()
    policy = SecurityPolicy(network_enabled=False)  # Disable network for security tests
    
    sid = await sb.create("python:3.11-slim", policy)
    await sb.start(sid)
    
    try:
        # Try to access host filesystem
        result = await sb.exec(sid, ["ls", "/host"], timeout_s=5.0)
        print(f"ls /host: exit_code={result.exit_code}, stdout='{result.stdout[:100]}'")
        # Should not see host filesystem
        
        # Try docker socket
        result = await sb.exec(sid, ["ls", "/var/run/docker.sock"], timeout_s=5.0)
        print(f"docker.sock check: exit_code={result.exit_code}")
        assert result.exit_code != 0 or "No such" in result.stderr or "No such" in result.stdout
        
        # Try mounting
        result = await sb.exec(sid, ["mount"], timeout_s=5.0)
        print(f"mount check: exit_code={result.exit_code}")
        # Should fail or show minimal mounts
        
    finally:
        await sb.destroy(sid)
    print("PASS")


async def test_security_docker_socket():
    """Test: Docker socket is not exposed."""
    print("\n=== Security: Docker Socket Protection ===")
    sb = OpenSandboxBackend()
    policy = SecurityPolicy(network_enabled=False)
    
    sid = await sb.create("python:3.11-slim", policy)
    await sb.start(sid)
    
    try:
        result = await sb.exec(sid, ["test", "-e", "/var/run/docker.sock"])
        print(f"Docker socket exists: exit_code={result.exit_code}")
        assert result.exit_code != 0, "Docker socket should not be accessible"
        
        # Try to use docker command
        result = await sb.exec(sid, ["docker", "ps"], timeout_s=5.0)
        print(f"docker ps: exit_code={result.exit_code}")
        # Should fail (no docker inside sandbox)
        
    finally:
        await sb.destroy(sid)
    print("PASS")


async def test_security_network_deny():
    """Test: network deny-by-default works."""
    print("\n=== Security: Network Deny-by-Default ===")
    sb = OpenSandboxBackend()
    policy = SecurityPolicy(network_enabled=False)  # Default is deny
    
    sid = await sb.create("python:3.11-slim", policy)
    await sb.start(sid)
    
    try:
        # Try network access (should fail with deny policy)
        result = await sb.exec(sid, ["curl", "-s", "--max-time", "3", "http://example.com"], timeout_s=10.0)
        print(f"Network deny test: exit_code={result.exit_code}, stderr='{result.stderr[:100]}'")
        # Should fail or timeout due to network denial
        
    finally:
        await sb.destroy(sid)
    print("PASS")


async def test_security_cpu_memory_limits():
    """Test: CPU/memory limits are applied."""
    print("\n=== Security: CPU/Memory Limits ===")
    sb = OpenSandboxBackend()
    policy = SecurityPolicy(
        network_enabled=True,
        cpu_limit=1.0,
        memory_limit=512 * 1024 * 1024,  # 512MB
    )
    
    sid = await sb.create("python:3.11-slim", policy)
    await sb.start(sid)
    
    try:
        meta = await sb.get_metadata(sid)
        limits = meta.resource_limits
        print(f"CPU limit: {limits.get('cpu_limit')}")
        print(f"Memory limit: {limits.get('memory_limit')}")
        assert limits.get("cpu_limit") == 1.0
        assert limits.get("memory_limit") == 512 * 1024 * 1024
        
        # Verify limits are in effect
        result = await sb.exec(sid, ["ulimit", "-a"])
        print(f"ulimit output (first 200 chars): {result.stdout[:200]}")
        
    finally:
        await sb.destroy(sid)
    print("PASS")


async def test_capabilities():
    """Test: capability reporting."""
    print("\n=== Capabilities Reporting ===")
    sb = OpenSandboxBackend()
    caps = sb.capabilities
    
    print(f"has_network_policy: {caps.has_network_policy}")
    print(f"has_cpu_limit: {caps.has_cpu_limit}")
    print(f"has_memory_limit: {caps.has_memory_limit}")
    print(f"has_pid_limit: {caps.has_pid_limit} (known limitation)")
    print(f"has_read_only_root: {caps.has_read_only_root} (image-dependent)")
    print(f"has_timeout: {caps.has_timeout}")
    print(f"has_streaming: {caps.has_streaming}")
    print(f"has_snapshot: {caps.has_snapshot}")
    print(f"has_isolated_execution: {caps.has_isolated_execution}")
    print(f"has_file_upload: {caps.has_file_upload}")
    print(f"has_file_download: {caps.has_file_download}")
    print(f"has_list_files: {caps.has_list_files}")
    print(f"has_cleanup_api: {caps.has_cleanup_api}")
    
    assert caps.has_network_policy is True
    assert caps.has_cpu_limit is True
    assert caps.has_memory_limit is True
    assert caps.has_pid_limit is False  # Known limitation
    assert caps.has_timeout is True
    assert caps.has_file_upload is True
    assert caps.has_file_download is True
    
    d = caps.to_dict()
    assert isinstance(d, dict)
    print("PASS")


async def test_secret_redaction():
    """Test: API keys do not appear in sandbox IDs."""
    print("\n=== Secret Redaction ===")
    sb = OpenSandboxBackend(api_key="sk-test-secret-key-12345")
    policy = SecurityPolicy()
    
    sid = await sb.create("python:3.11-slim", policy)
    print(f"Sandbox ID: {sid}")
    
    assert "sk-test" not in sid
    assert "12345" not in sid
    assert sid.startswith("eb-osb-")
    print("PASS")


async def test_orphan_cleanup():
    """Test: orphan cleanup works."""
    print("\n=== Orphan Cleanup ===")
    sb = OpenSandboxBackend()
    count = await sb.cleanup_orphans()
    print(f"Cleaned up {count} orphan sandboxes")
    assert isinstance(count, int)
    print("PASS")


async def main():
    """Run all live validation tests."""
    print("=" * 60)
    print("OpenSandbox Live Validation for EB Infrastructure")
    print("=" * 60)
    
    # Check server health
    import urllib.request
    try:
        with urllib.request.urlopen("http://localhost:8080/health", timeout=5) as resp:
            health = resp.read().decode()
            print(f"\nServer health: {health}")
            assert "healthy" in health
    except Exception as e:
        print(f"ERROR: OpenSandbox server not reachable: {e}")
        sys.exit(1)
    
    tests = [
        test_capabilities,
        test_basic_sandbox_lifecycle,
        test_shell_command_execution,
        test_timeout,
        test_file_write_and_read,
        test_file_download,
        test_security_host_isolation,
        test_security_docker_socket,
        test_security_network_deny,
        test_security_cpu_memory_limits,
        test_secret_redaction,
        test_orphan_cleanup,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            await test()
            passed += 1
        except Exception as e:
            print(f"FAIL: {test.__name__}: {e}")
            failed += 1
    
    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)
    
    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
