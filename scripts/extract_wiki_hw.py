#!/usr/bin/env python3
"""Extract Wikipedia hardware/engineering articles for 05_hardware_engineering."""
import json, pyarrow.parquet as pq, sys
from huggingface_hub import hf_hub_download

HW_KW = [
    "hardware", "circuit", "electronic", "electrical", "computer hardware",
    "processor", "microprocessor", "central processing", "gpu", "graphics card",
    "motherboard", "printed circuit", "integrated circuit", "semiconductor",
    "transistor", "diode", "capacitor", "resistor", "inductor",
    "sensor", "actuator", "microcontroller", "fpga", "asic",
    "memory chip", "ram", "rom", "flash memory", "ssd", "hard drive",
    "power supply", "voltage regulator", "oscillator", "amplifier",
    "filter circuit", "analog", "digital signal", "embedded system",
    "system on chip", "bus architecture", "pci", "usb", "hdmi",
    "ethernet", "wifi", "bluetooth", "rfid", "nfc", "gps module",
    "antenna", "receiver", "transmitter", "modulator", "demodulator",
    "oscilloscope", "multimeter", "logic analyzer", "signal generator",
    "mechanical engineering", "machine design", "thermodynamics",
    "fluid mechanics", "solid mechanics", "material science",
    "manufacturing", "cnc", "3d printing", "additive manufacturing",
    "robotics", "servo", "stepper motor", "dc motor", "encoder",
    "hydraulic", "pneumatic", "pump", "valve", "actuator system",
    "structural engineering", "civil engineering", "bridge design",
    "load bearing", "steel structure", "reinforced concrete",
    "aerospace engineering", "propulsion", "turbine", "engine design",
    "combustion", "heat exchanger", "refrigeration", "hvac",
    "automotive engineering", "chassis", "transmission", "brake system",
    "suspension", "steering", "fuel injection", "exhaust system",
    "industrial engineering", "supply chain engineering",
    "quality control", "process engineering", "automation",
    "instrumentation", "control system", "plc", "scada",
    "power engineering", "generator", "transformer", "grid",
    "renewable energy", "solar panel", "wind turbine", "battery",
    "nanoengineering", "microelectromechanical", "optics",
    "photonics", "laser", "fiber optic", "telecommunication",
    "radio engineering", "radar", "sonar", "navigation system",
    "audio engineering", "acoustic", "speaker design", "microphone",
    "display technology", "lcd", "oled", "led", "screen",
    "peripheral", "keyboard", "mouse", "printer", "scanner"
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

KW_SET = set(kw.lower() for kw in HW_KW)

def is_hw(title, text):
    t = title.lower()
    content = text.lower()[:3000]
    return any(kw in t or kw in content for kw in KW_SET)

atlas = []
for i in range(total):
    title = data["title"][i]
    text = data["text"][i]
    if not title or not text:
        continue
    if is_hw(title, text):
        atlas.append({
            "id": f"wiki_hw_{SHARD}_{i:07d}",
            "category": "05_hardware_engineering",
            "subcategory": "engineering",
            "type": "document",
            "source": {"name": "wikimedia/wikipedia", "url": data["url"][i], "license": "CC-BY-SA-3.0"},
            "messages": [
                {"role": "user", "content": f"Explain: {title}"},
                {"role": "assistant", "content": text[:3000]}
            ],
            "language": "en",
            "difficulty": 2,
            "tags": ["wikipedia", "hardware", "engineering"],
            "quality_score": 7,
            "verified": False,
            "notes": ""
        })

output = f"raw/generated/wiki_hw_shard{SHARD}_atlas.jsonl"
with open(output, "w") as f:
    for rec in atlas:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

print(f"Hardware articles: {len(atlas)} -> {output}")
