"""Render this audit's recorded differential; does not run event selection or a fit."""
import argparse
import json
from pathlib import Path


def render(audit_path, reference_path, output_dir):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np

    audit = json.loads(Path(audit_path).read_text())
    reference = json.loads(Path(reference_path).read_text())
    if audit['entries'] != reference['generated_events']:
        raise ValueError('Reference event-count scale does not match the audit')
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 10,
                         'axes.spines.top': False, 'axes.spines.right': False,
                         'pdf.fonttype': 42, 'ps.fonttype': 42})
    fig, axes = plt.subplots(1, 2, figsize=(12.4, 6.1), gridspec_kw={'width_ratios': [1.5, 1]})
    fig.subplots_adjust(left=.07, right=.98, bottom=.24, top=.75, wspace=.25)
    colors = ['#ab6b46', '#246c91', '#c6cbd0']
    labels = ['Historical mixed frame', 'Paper-defined common boost', 'ATLAS acceptance × 200,000']
    stages = audit['cutflow_order'][1:]
    xs = np.arange(len(stages))
    for offset, policy, color, label in zip([-.19, .19], ['historical', 'paper'], colors, labels):
        bars = axes[0].bar(xs+offset, [audit['cutflow'][policy][s] for s in stages], .36,
                           color=color, label=label)
        axes[0].bar_label(bars, padding=3, fontsize=9)
    axes[0].set_xticks(xs, ['Lepton pT\n+ jet veto', r'$H^{boost}$'+'\n> 250 GeV',
                           r'$p_T^{soft}$ fraction'+'\n< 0.05', r'$m_{eff}/H^{boost}$'+'\n> 0.9',
                           r'$m_T$'+'\n> 100 GeV'])
    axes[0].set_ylim(0, 385)
    axes[0].set_ylabel('Retained events')
    axes[0].set_title('SR-low selection stages', loc='left', pad=12)
    xs = np.arange(2)
    regions = ['SRlow', 'SRISR']
    for offset, policy, color, label in zip([-.26, 0], ['historical', 'paper'], colors, labels):
        bars = axes[1].bar(xs+offset, [audit['counts'][policy][s] for s in regions], .25,
                           color=color, label=label)
        axes[1].bar_label(bars, padding=3, fontsize=9)
    bars = axes[1].bar(xs+.26, [reference['regions'][s]['acceptance_times_efficiency']*audit['entries']
                              for s in regions], .25, color=colors[2], label=labels[2])
    axes[1].bar_label(bars, fmt='%.1f', padding=3, fontsize=9)
    axes[1].set_xticks(xs, ['SR-low', 'SR-ISR'])
    axes[1].set_ylim(0, 147)
    axes[1].set_title('Final signal regions', loc='left', pad=12)
    axes[1].set_ylabel('Events / equivalent ATLAS expectation')
    for ax in axes:
        ax.set_axisbelow(True)
        ax.yaxis.grid(True, color='#e5e5e5', linewidth=.6)
    fig.suptitle('Invisible-momentum boost correction', x=.07, y=.98, ha='left', fontsize=17)
    fig.text(.07, .916, 'C1N2 (300, 100) GeV · ATLAS-SUSY-2018-06 · same 200,000 retained detector events', fontsize=11)
    handles, legend_labels = axes[1].get_legend_handles_labels()
    fig.legend(handles, legend_labels, loc='upper left', bbox_to_anchor=(.063, .87),
               ncol=3, frameon=False, fontsize=9.5)
    pub = reference['regions']['SRlow']['acceptance_times_efficiency']
    old = abs(audit['acceptance']['historical']['SRlow']/pub-1)*100
    new = abs(audit['acceptance']['paper']['SRlow']/pub-1)*100
    fig.text(.07, .103, f'SR-low acceptance deficit: {old:.1f}% → {new:.1f}%. Still FAIL against the 15% tolerance.', fontsize=11)
    fig.text(.07, .05, 'Cached reconstruction audit only. No fresh generation, detector retuning, updated limit, or new certification.', fontsize=9.5, color='#444444')
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    fig.savefig(out/'cutflow-comparison.png', dpi=180)
    fig.savefig(out/'cutflow-comparison.pdf', metadata={'CreationDate': None, 'ModDate': None})
    plt.close(fig)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit', type=Path, default=Path(__file__).with_name('erjr_differential.json'))
    parser.add_argument('--reference', type=Path, default=Path(__file__).with_name('reference.json'))
    parser.add_argument('--out', type=Path, default=Path(__file__).parent)
    args = parser.parse_args()
    render(args.audit, args.reference, args.out)
