"""Events Radar scraper package.

This file marks `scraper/` as a regular Python package so test runners
(pytest) can resolve `from scraper.scraper import ...` without
ambiguity against the sibling `scraper.py` module. Namespace-package
resolution worked at runtime but broke pytest's rootdir-based import
when `scraper/tests/__init__.py` existed.
"""
