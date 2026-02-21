# -*- coding: utf-8 -*-
import sys
import io

# Set UTF-8 encoding for stdout
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Now import and run the app
from app import main

if __name__ == "__main__":
    main()
