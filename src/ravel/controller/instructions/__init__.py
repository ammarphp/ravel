"""Instruction delivery: every instruction a node owes its worker, verbatim, with a receipt and a
line-by-line acknowledgement.

The catalogue compiles every instruction-bearing file and effective role card into units with
stable ids and digests (``scripts/maintenance/build_instruction_catalogue.py``). A node builds
its ``manifest`` from the installed catalogue, renders the ``packet`` its worker receives, has
``check_packet`` refuse any altered packet before dispatch, records the delivery receipt and
accepts the worker's final record only when ``check_ack`` finds a complete acknowledgement.
Reviewers receive ``reviewer_items``. Delivery and acknowledgement are enforced; obedience to
the delivered text is reviewed, not proven.
"""
from .ack import (ack_properties, check_ack, check_item_verdicts, holds, output_schema, pin_schema, reviewer_items,
                  validate_record)
from .catalogue import installed
from .custody import observed_completion
from .delivery import (PacketBudgetExceeded, PacketRefused, check_packet, discharge, manifest, manifest_problems, obligations, packet,
                       receipt, record_delivery, reference_bytes, serve)

__all__ = ['PacketBudgetExceeded', 'PacketRefused', 'ack_properties', 'check_ack', 'check_item_verdicts', 'check_packet', 'discharge', 'holds',
           'installed', 'manifest', 'manifest_problems', 'obligations', 'output_schema', 'packet', 'pin_schema',
           'receipt', 'record_delivery', 'reference_bytes', 'reviewer_items', 'serve', 'validate_record', 'observed_completion']
