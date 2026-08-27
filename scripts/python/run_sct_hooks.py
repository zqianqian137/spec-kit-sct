#!/usr/bin/env python3
"""
run_sct_hooks.py
作为 Speckit hook 调用的统一入口
- Speckit 通过 .specify/extensions.yml 调用此脚本
- 实际逻辑委托给 sct_hooks.py 的子命令
"""
import sys
from pathlib import Path

# 把 sct_hooks.py 加到路径
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import sct_hooks  # noqa: E402

if __name__ == "__main__":
    sct_hooks.main()
