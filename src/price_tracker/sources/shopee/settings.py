"""Shopee constants that hold for every SKU.

Things only Shopee has, and that do NOT depend on any particular SKU.

Kept out of the shared config.py so that when TikTok or Logitech is added,
each source gets its own settings.py without stepping on the others.

This file used to hard-code TARGET_ITEM_ID/PRODUCT_URL for a single SKU, read
from skus.yaml at import time. That does not scale: a module-level constant has
exactly one value per process, so scraping a second SKU meant editing code.
Listing config is now passed in as an argument (see extract.fetch_one_listing),
and only the SKU-independent parts remain here.
"""

# The internal Shopee API that returns the price. We capture the response of
# this path instead of reading CSS selectors -- see ADR 0002 and
# docs/issues.md Issue 5.
PDP_API_PATH = "pdp/get_pc"

# Raw filename prefix. Shared by extract.py (when writing) and transform.py
# (when globbing for it back), so it has to live in one place: a one-character
# drift between the two means transform finds nothing, with no error explaining
# why.
RAW_FILE_PREFIX = "shopee_raw"
