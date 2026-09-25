"""Extraction: reader -> raw tables -> normalize() -> low-confidence rows flagged for review.

Scans go through ocr.py, which routes GETS screenshots to gets_grid and everything else to
generic_table.
"""
