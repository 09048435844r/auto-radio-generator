# -*- coding: utf-8 -*-
import os

# Read the file with utf-8 encoding
with open('app.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Write it back with utf-8 encoding and BOM
with open('app.py', 'w', encoding='utf-8-sig') as f:
    f.write(content)

print("File encoding fixed")
