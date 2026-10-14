"""ROC and calibration diagnostics for the complete declared arm/seed population."""
import json
from pathlib import Path


def render(receipt, output):
    import matplotlib.pyplot as plt
    from . import mplhep_style as house
    output = Path(output)
    receipts = []
    with plt.rc_context():
        house.apply_style('ROOT', required=True)
        plt.rcParams.update({'font.size': 11, 'axes.labelsize': 12,
                             'axes.titlesize': 12, 'xtick.labelsize': 10,
                             'ytick.labelsize': 10})
        for name in ('roc', 'reliability'):
            fig, ax = plt.subplots(figsize=(9, 5))
            fig.subplots_adjust(left=.11, right=.73, bottom=.15, top=.90)
            identities = list(dict.fromkeys(a['id'] for a in receipt['arms']))
            for row in receipt['arms']:
                color = house.STACK_CYCLE[identities.index(row['id']) % len(house.STACK_CYCLE)]
                if name == 'roc':
                    x, y = row['roc']['false_positive_rate'], row['roc']['true_positive_rate']
                else:
                    bins = json.loads(Path(row['calibration']['reliability']['path']).read_text())
                    x = [b['probability'] for b in bins if b['weight']]
                    y = [b['frequency'] for b in bins if b['weight']]
                first = next(a for a in receipt['arms'] if a['id'] == row['id']) is row
                ax.plot(x, y, color=color, alpha=.7, linewidth=1.5, zorder=3, clip_on=False,
                        label=f"{row['id']} ({row['kind']})" if first else None)
            ax.plot([0, 1], [0, 1], '--', color='grey', linewidth=1, zorder=3, clip_on=False)
            ax.set(xlim=(0, 1), ylim=(0, 1),
                   xlabel='Background efficiency' if name == 'roc' else 'Predicted signal probability',
                   ylabel='Signal efficiency' if name == 'roc' else 'Observed signal fraction',
                   title='Withheld test sample · all declared seeds')
            house.tick_hygiene(ax); ax.legend(fontsize=9, loc='upper left', bbox_to_anchor=(1.02, 1))
            violations = house.lint_figure(fig, saves_tight=False)
            if violations:
                plt.close(fig)
                raise ValueError('ML figure lint failed: ' + '; '.join(violations))
            files=[]
            for ext in ('png','pdf'):
                path=output/f'{name}.{ext}'; fig.savefig(path,dpi=160); files.append(path.name)
            plt.close(fig)
            receipts.append({'stem':name,'files':files,'quantity':name,
                             'scope':'Supplied test sample diagnostics, no physics certification'})
    (output/'figures.json').write_text(json.dumps({'figures':receipts},indent=2)+'\n')
    return receipts
