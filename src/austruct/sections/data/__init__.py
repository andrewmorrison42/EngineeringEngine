"""Reference data for sections.

Held here rather than under ``materials/data`` because a section catalogue is
not a material property -- it belongs with the sections. The shared loader in
``materials/_data.py`` searches both packages, so a caller asks for a filename
and does not have to know which one holds it.
"""
