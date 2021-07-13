#!/usr/bin/env python3

from trails.trail import Trail

i = 0
for trail in Trail.load_all():
    print(i, trail.title)
    trail.save()
    i += 1
