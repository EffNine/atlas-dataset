#!/usr/bin/env python3
"""Extract Wikipedia system/OS articles for 03_system_engineering."""
import json, pyarrow.parquet as pq, sys
from huggingface_hub import hf_hub_download

SYS_KW = [
    "operating system", "linux", "unix", "windows", "macos", "kernel",
    "system call", "process management", "memory management",
    "file system", "device driver", "boot loader", "firmware",
    "bios", "uefi", "virtual memory", "paging", "segmentation",
    "multitasking", "scheduling", "interrupt", "system daemon",
    "system administration", "sysadmin", "server management",
    "configuration management", "ansible", "puppet", "chef",
    "network administration", "dns", "dhcp", "tcp/ip", "ip address",
    "subnet", "router", "switch", "firewall", "proxy", "load balancer",
    "vpn", "ssh", "ssl", "tls", "certificate", "authentication",
    "authorization", "ldap", "active directory", "single sign-on",
    "identity management", "access control", "permission",
    "security hardening", "patch management", "vulnerability",
    "intrusion detection", "antivirus", "malware", "ransomware",
    "backup", "disaster recovery", "high availability",
    "redundancy", "failover", "load balancing", "cluster",
    "monitoring", "logging", "alerting", "prometheus", "grafana",
    "nagios", "zabbix", "elk stack", "splunk", "datadog",
    "container", "docker", "kubernetes", "orchestration",
    "virtualization", "vmware", "hypervisor", "kvm", "xen",
    "cloud computing", "iaas", "paas", "saas", "aws", "azure",
    "gcp", "infrastructure", "terraform", "cloudformation",
    "ci/cd", "continuous integration", "continuous delivery",
    "jenkins", "gitlab ci", "github actions", "deployment pipeline",
    "artifact", "registry", "image", "container registry",
    "network topology", "lan", "wan", "vlan", "nat", "acl",
    "bandwidth", "latency", "throughput", "qos", "traffic shaping",
    "storage", "nas", "san", "raid", "lvm", "volume manager",
    "data center", "server rack", "power distribution",
    "cooling system", "ups", "generator", "sla", "uptime",
    "disaster recovery", "business continuity", "runbook",
    "incident response", "change management", "itil",
    "compliance", "audit log", "sox", "hipaa", "gdpr",
    "shell", "bash", "powershell", "command line", "terminal",
    "scripting", "automation", "cron", "systemd", "init",
    "package manager", "apt", "yum", "pacman", "homebrew",
    "repository", "dependency", "environment variable",
    "path", "library", "shared object", "dynamic linking",
    "performance tuning", "resource monitoring", "capacity planning",
    "cpu", "memory", "disk i/o", "network i/o", "benchmark",
    "kernel parameter", "sysctl", "ulimit", "cgroup", "namespace"
]

SHARD = int(sys.argv[1])
print(f"Loading Wikipedia shard {SHARD}...")
path = hf_hub_download(
    repo_id="wikimedia/wikipedia",
    repo_type="dataset",
    filename=f"20231101.en/train-{SHARD:05d}-of-00041.parquet"
)

t = pq.read_table(path)
data = t.to_pydict()
total = len(data["title"])
print(f"Total articles: {total}")

KW_SET = set(kw.lower() for kw in SYS_KW)

def is_sys(title, text):
    t = title.lower()
    content = text.lower()[:3000]
    return any(kw in t or kw in content for kw in KW_SET)

atlas = []
for i in range(total):
    title = data["title"][i]
    text = data["text"][i]
    if not title or not text:
        continue
    if is_sys(title, text):
        atlas.append({
            "id": f"wiki_sys_{SHARD}_{i:07d}",
            "category": "03_system_engineering",
            "subcategory": "systems",
            "type": "document",
            "source": {"name": "wikimedia/wikipedia", "url": data["url"][i], "license": "CC-BY-SA-3.0"},
            "messages": [
                {"role": "user", "content": f"Explain: {title}"},
                {"role": "assistant", "content": text[:3000]}
            ],
            "language": "en",
            "difficulty": 2,
            "tags": ["wikipedia", "systems"],
            "quality_score": 7,
            "verified": False,
            "notes": ""
        })

output = f"raw/generated/wiki_sys_shard{SHARD}_atlas.jsonl"
with open(output, "w") as f:
    for rec in atlas:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

print(f"System articles: {len(atlas)} -> {output}")
