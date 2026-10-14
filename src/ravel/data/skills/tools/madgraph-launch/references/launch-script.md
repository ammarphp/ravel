# MadGraph 2.9.27 launch script shape

RAVEL's model-events mode writes two scripts for the pinned MadGraph tree
(`ravel.physics.model_events.render_scripts`).

The build script sets the interface options (`automatic_html_opening`,
`run_mode 0`, `nb_core 1`, compiler and tool paths from the configuration),
imports the model with the `-full` suffix so the model's default restriction is
not applied, replays the declared process lines and ends with `output <dir>`.

The launch script repeats the interface options, then:

```text ravel-block=typed-launch-shape
launch <process-dir> -n ravel
shower=PYTHIA8
madspin=OFF
reweight=OFF
detector=OFF
analysis=OFF
0
0
```

The switch lines answer the first prompt; the first `0` closes it. The second
prompt offers card edits; RAVEL answers `0` at once because the supplied cards
were copied in complete. NLO launches add `order=NLO` and `fixed_order=OFF`
and use `madanalysis=OFF` in place of the detector and analysis switches.

Upstream: `help launch` in the 2.9.27 interface, and the switch and card-edit
questions in its source (madgraph/interface/madevent_interface.py and
common_run_interface.py). Project page: https://launchpad.net/mg5amcnlo.
