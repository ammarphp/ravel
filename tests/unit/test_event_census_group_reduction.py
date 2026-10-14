"""Portable structural-census arithmetic tests; invented source records only."""
import gzip
from pathlib import Path
import tempfile
import unittest
from ravel.physics import event_census


def frame(event, weights):
    return f'''E {event} -1 1 0 0 0 -1 1 1 2 0 2 {' '.join(weights)}
N 2 "Default" "variation"
U GEV MM
V -1 0 0 0 0 0 2 1 0
P 1 2212 0 0 4000 4000 .938 4 0 0 -1 0
P 2 2212 0 0 -4000 4000 .938 4 0 0 -1 0
P 3 13 0 0 0 1 .1 1 0 0 0 0
'''


class GroupReduction(unittest.TestCase):
    def evaluate(self, frames, nominal=None):
        raw = ('HepMC::Version 2.06.09\nHepMC::IO_GenEvent-START_EVENT_LISTING\n' +
               ''.join(frames) + 'HepMC::IO_GenEvent-END_EVENT_LISTING\n').encode()
        with tempfile.TemporaryDirectory(prefix='census-arithmetic-') as directory:
            path = Path(directory) / 'invented.hepmc.gz'
            path.write_bytes(gzip.compress(raw, mtime=0)); before = path.read_bytes()
            metadata = {'schema_version': 1, 'event_level': 'hadron', 'beam_pdg': [2212, 2212],
                        'beam_energy_gev': [4000, 4000], 'weight_names': ['Default', 'variation'],
                        'events': len(frames), 'groups': 'correlated_event_number', 'cross_section_pb': 1,
                        'source': 'invented structural parser fixture; no physical event simulation'}
            result = event_census.census(path, metadata, nominal_weight=nominal)
            self.assertEqual(path.read_bytes(), before)
            return result

    def test_contiguous_group_cancellation_uses_all_original_marks(self):
        result = self.evaluate([frame(1, (w, '0')) for w in ('1e16', '1', '-1e16', '2')])
        self.assertEqual(result['sumw'], [3, 0])
        self.assertEqual(result['group_weight_second_moments'], [[9, 0], [0, 0]])
        self.assertEqual(result['events'], 4)
        self.assertEqual(result['negative_nominal_subevents'], 1)

    def test_complete_cross_weight_group_moments(self):
        frames = [frame(1, (w, '2')) for w in ('1e16', '1', '-1e16', '2')]
        result = self.evaluate(frames + [frame(2, ('-1', '-3'))])
        self.assertEqual(result['sumw'], [2, 5])
        self.assertEqual(result['group_weight_second_moments'], [[10, 27], [27, 73]])

    def test_named_nominal_does_not_reorder_or_change_native_denominator(self):
        result = self.evaluate([frame(1, ('-2', '3'))], nominal='variation')
        self.assertEqual(result['weight_names'], ['Default', 'variation'])
        self.assertEqual(result['nominal_sumw'], 3)
        self.assertEqual(result['native_normalization_sumw'], -2)
        self.assertFalse(result['nominal_weight_selection']['native_effective_weights_observed'])

    def test_finite_marks_with_nonfinite_full_gram_refuse(self):
        with self.assertRaisesRegex(ValueError, 'second moment'):
            self.evaluate([frame(1, ('1e200', '1'))])
