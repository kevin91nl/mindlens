#!/usr/bin/env python3
"""Add XML tool call parsing to yaml_agent.py"""
import pathlib, re

p = pathlib.Path("src/mindlens/agents/yaml_agent.py")
content = p.read_text()

# Find the return calls line in _extract_tool_calls
marker = "        return calls"
idx = content.find(marker)
if idx == -1:
    print("Marker not found")
    exit(1)

# Insert XML parsing before return calls
insert = """
        # 2. XML-style tool calls
        if not calls:
            xml_matches = re.findall(r'<function[._](\\w+)>(.*?)</function[._]\\1>', content, re.DOTALL)
            for tool_name, body in xml_matches:
                args = {}
                for param in re.finditer(r'<parameter\\\\s+name=\\"([^\\"]+)\\">(.*?)