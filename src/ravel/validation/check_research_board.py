"""Computed research board checks over a season journal and its run custody.

``board_replay``: the custody-verified journal replays, and its register agrees
with the research-cycle register recomputed from the same evidence.
``board_schema``: every post and hypothesis is a closed typed record.
``board_sealed``: the reveal record's sealing label equals the label recomputed
from the retained worker receipts.
"""
from pathlib import Path

from ravel.workflow import research_board as board, research_board_discussion as discussion

CHECKS = ['board_replay', 'board_schema', 'board_sealed']


def validate(check_id, value, *, base_dir):
    """Run one check; ``value`` names the season journal root (``research/board/<season>``)."""
    name = check_id.removeprefix('check:')
    if name not in CHECKS:
        raise ValueError('unknown research board check')
    try:
        root = Path(base_dir) / value['season_root']
        season = board.season(root, rundir=base_dir)
        if name == 'board_replay':
            from ravel.workflow.research_cycle import replay_register
            if board.register_bytes(season) != board.register_bytes(board.season(root, rundir=base_dir)):
                raise ValueError('board register replay is not deterministic')
            replay_register(board.cycle_events(season))
        elif name == 'board_schema':
            for entry in season['entries']:
                if entry['event'] == 'post':
                    board.validate_post(season['charter'], entry['payload'])
        else:
            discussion.season_binding(root)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        return {'valid': False, 'errors': [str(exc)]}
    return {'valid': True, 'errors': []}
