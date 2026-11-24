#!/usr/bin/env python3
"""Note an event in a recording made with vmrec.py (for make-video.py).

  vmmark.py <rec-dir> keep-start | keep-end          a stretch worth keeping (the rest is cut)
  vmmark.py <rec-dir> caption <png>                  show this caption from now on
  vmmark.py <rec-dir> speed <factor>                 play from now on at this speed (1 = normal)
  vmmark.py <rec-dir> sound <file>                   a sound was heard now
Each line in <rec-dir>/marks.jsonl is [milliseconds since recording started, kind, value].
"""
import json
import os
import sys
import time


def main():
    d, kind, *val = sys.argv[1:]
    t0 = float(open(os.path.join(d, "t0.txt")).read())
    ms = int((time.time() - t0) * 1000)
    with open(os.path.join(d, "marks.jsonl"), "a") as f:
        f.write(json.dumps([ms, kind, val[0] if val else None]) + "\n")


if __name__ == "__main__":
    main()
